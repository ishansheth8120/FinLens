"""Post-hoc numeric verification.

**The point of this module:** an LLM given a table of correct numbers will still
occasionally state a number that is not in it — a transposed digit, a growth
rate computed against the wrong base, a figure recalled from training rather
than read from the rows. The answer reads perfectly. Nobody catches it.

So every figure the model asserts is recomputed against the actual query
results, and anything that does not reconcile is flagged or redacted before the
answer is served. This is the difference between "the model was given good data"
and "the output has been checked".

What counts as reconciled:

1. **Direct match** — the value appears in the result rows, within tolerance.
2. **Scaled match** — it appears at a different magnitude. Models routinely
   report 383,285 as 383.3 (billions) or 0.441 as 44.1%. Both are correct
   restatements, not errors, so the checker is scale-aware.
3. **Derived match** — it equals a difference, ratio or percent change between
   two values that *are* present. Arithmetic on the given data is legitimate.

Anything else fails. The verifier never consults outside knowledge: a figure
that is true of the real world but absent from the rows is `unsupported`, and
that is deliberate — it is exactly the failure mode being hunted.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from finlens.agent.types import (
    ClaimVerdict,
    ClaimVerification,
    NumericClaim,
    SqlResult,
    VerificationReport,
)
from finlens.logging import get_logger

log = get_logger(__name__)

# Tolerance is inferred from the precision the claim was *stated* at, not fixed.
#
# A fixed relative tolerance cannot work here. Set it loose enough to accept
# "$383.3B" for 383,285,000,000 (0.004% off) and it also accepts 383,825 for
# 383,285 - a transposed digit, 0.14% off, and exactly the error this module
# exists to catch. Set it tight and every rounded figure fails.
#
# Reading precision from the claim resolves it: "383.3 billion" is 4 significant
# figures and gets a half-unit-in-last-place window of ±50 million, while
# "383,825" is 6 significant figures and gets ±0.5. The first reconciles, the
# second does not.
FLOAT_NOISE_FLOOR = 1e-9

# Magnitudes a model legitimately restates into: thousands, millions, billions,
# trillions, and the percent/fraction pair.
SCALE_FACTORS = (
    1.0,
    1e3, 1e-3,
    1e6, 1e-6,
    1e9, 1e-9,
    1e12, 1e-12,
    100.0, 0.01,
)  # fmt: skip

# Above this many numeric cells, the pairwise derivation search is skipped: it
# is O(n^2) and a result set that large is a listing, not a figure the answer
# is deriving from.
MAX_CELLS_FOR_DERIVATION = 400


def _numeric_cells(result: SqlResult) -> list[float]:
    """Every finite number in the result set, flattened.

    Booleans are excluded: `True` is `1` in Python, and a `has_financial_data`
    column would otherwise "verify" any claim of 1.
    """
    values: list[float] = []
    for row in result.rows:
        for cell in row:
            if isinstance(cell, bool) or cell is None:
                continue
            if isinstance(cell, (int, float)):
                number = float(cell)
                if math.isfinite(number):
                    values.append(number)
    return values


def significant_digits(value: float) -> int:
    """How many significant figures a number was written to.

    Read off the shortest decimal representation, with trailing zeros in the
    integer part discarded: ``383.3`` is 4, ``383300000000.0`` is also 4, and
    ``383825.0`` is 6. That difference is what separates a rounded restatement
    from a wrong number.
    """
    if value == 0 or not math.isfinite(value):
        return 1
    digits = f"{abs(value):.15g}"
    if "e" in digits:
        digits = digits.split("e")[0]
    digits = digits.replace(".", "").replace("-", "").lstrip("0")
    stripped = digits.rstrip("0")
    return max(1, len(stripped))


def tolerance_for(value: float, override: float | None = None) -> float:
    """Absolute tolerance for a claimed value.

    ``override`` is interpreted as a relative tolerance, for callers that want
    a fixed band (the eval harness uses one when comparing against hand-written
    expected answers).
    """
    if override is not None:
        return abs(value) * override
    if value == 0 or not math.isfinite(value):
        return FLOAT_NOISE_FLOOR

    exponent = math.floor(math.log10(abs(value)))
    ulp = 10.0 ** (exponent - significant_digits(value) + 1)
    return max(ulp / 2.0, abs(value) * FLOAT_NOISE_FLOOR)


def _close(claim_value: float, candidate: float, tolerance: float | None) -> bool:
    """Whether ``candidate`` is within the claim's stated precision."""
    return abs(claim_value - candidate) <= tolerance_for(claim_value, tolerance)


def _match_direct(
    claim_value: float, cells: list[float], tolerance: float | None
) -> tuple[float, float] | None:
    """Find a cell equal to the claim at any plausible scale."""
    best: tuple[float, float] | None = None

    for cell in cells:
        for factor in SCALE_FACTORS:
            scaled = cell * factor
            if _close(claim_value, scaled, tolerance):
                error = 0.0 if scaled == 0 else abs(claim_value - scaled) / abs(scaled)
                if best is None or error < best[1]:
                    best = (cell, error)
    return best


def _match_derived(
    claim_value: float, cells: list[float], tolerance: float | None
) -> tuple[float, float, str] | None:
    """Find a pair of cells whose difference, ratio or percent change matches.

    Covers the arithmetic a commentary genuinely performs: "grew by $12B",
    "a 15.2% increase", "a margin of 44%".
    """
    if len(cells) > MAX_CELLS_FOR_DERIVATION:
        return None

    unique = sorted({c for c in cells})
    for a, b in itertools.permutations(unique, 2):
        candidates: list[tuple[float, str]] = [(a - b, f"{a:,.4g} - {b:,.4g}")]
        if b != 0:
            ratio = a / b
            candidates.append((ratio, f"{a:,.4g} / {b:,.4g}"))
            candidates.append((ratio * 100.0, f"100 * {a:,.4g} / {b:,.4g}"))
            change = (a - b) / abs(b)
            candidates.append((change, f"({a:,.4g} - {b:,.4g}) / |{b:,.4g}|"))
            candidates.append((change * 100.0, f"100 * ({a:,.4g} - {b:,.4g}) / |{b:,.4g}|"))

        for value, derivation in candidates:
            if math.isfinite(value) and _close(claim_value, value, tolerance):
                error = 0.0 if value == 0 else abs(claim_value - value) / abs(value)
                return value, error, derivation
    return None


def verify_claim(
    claim: NumericClaim,
    result: SqlResult | None,
    *,
    tolerance: float | None = None,
) -> ClaimVerification:
    """Check one asserted figure against the query results."""
    if result is None or not result.ok or not result.rows:
        return ClaimVerification(
            claim=claim,
            verdict=ClaimVerdict.UNCHECKABLE,
            detail="no structured result set to reconcile against",
        )

    cells = _numeric_cells(result)
    if not cells:
        return ClaimVerification(
            claim=claim,
            verdict=ClaimVerdict.UNCHECKABLE,
            detail="result set contains no numeric columns",
        )

    direct = _match_direct(claim.value, cells, tolerance)
    if direct is not None:
        matched, error = direct
        return ClaimVerification(
            claim=claim,
            verdict=ClaimVerdict.RECONCILED,
            matched_value=matched,
            relative_error=error,
            detail="matches a value in the result set",
        )

    derived = _match_derived(claim.value, cells, tolerance)
    if derived is not None:
        value, error, derivation = derived
        return ClaimVerification(
            claim=claim,
            verdict=ClaimVerdict.RECONCILED,
            matched_value=value,
            relative_error=error,
            detail=f"derived: {derivation}",
        )

    # Distinguish "wrong number" from "number out of nowhere". A claim that is
    # within an order of magnitude of something real is probably a computation
    # error; one that is nowhere near anything is probably recalled.
    nearest = min(cells, key=lambda c: abs(c - claim.value), default=None)
    if nearest is not None and nearest != 0 and abs(claim.value / nearest) < 10:
        return ClaimVerification(
            claim=claim,
            verdict=ClaimVerdict.MISMATCH,
            matched_value=nearest,
            relative_error=abs(claim.value - nearest) / abs(nearest),
            detail=f"nearest value in the results is {nearest:,.4g}",
        )

    return ClaimVerification(
        claim=claim,
        verdict=ClaimVerdict.UNSUPPORTED,
        detail="no value in the result set corresponds to this figure at any scale",
    )


def verify(
    claims: list[NumericClaim],
    result: SqlResult | None,
    *,
    tolerance: float | None = None,
) -> VerificationReport:
    """Verify every numeric claim in an answer."""
    verifications = [verify_claim(claim, result, tolerance=tolerance) for claim in claims]

    report = VerificationReport(
        verifications=verifications,
        checked=sum(1 for v in verifications if v.verdict != ClaimVerdict.UNCHECKABLE),
        reconciled=sum(1 for v in verifications if v.verdict == ClaimVerdict.RECONCILED),
        failed=sum(1 for v in verifications if v.is_failure),
        unchecked=sum(1 for v in verifications if v.verdict == ClaimVerdict.UNCHECKABLE),
    )

    if report.has_failures:
        log.warning(
            "verifier.failures",
            failed=report.failed,
            checked=report.checked,
            claims=[v.claim.text[:80] for v in report.failures()],
        )
    return report


def redact_failures(commentary: str, report: VerificationReport) -> tuple[str, list[str]]:
    """Remove unreconciled sentences from the commentary.

    The alternative - serving the answer with a warning attached - assumes the
    reader looks at the warning. They do not. A sentence whose number could not
    be reconciled is replaced with an explicit marker, which is both honest and
    impossible to miss.

    Returns the edited commentary and the warnings to attach.
    """
    if not report.has_failures:
        return commentary, []

    edited = commentary
    warnings: list[str] = []

    for verification in report.failures():
        fragment = verification.claim.text.strip()
        marker = (
            f"[figure withheld: {verification.verdict.value} against the query results]"
        )
        if fragment and fragment in edited:
            edited = edited.replace(fragment, marker)
        warnings.append(
            f"Unverified figure removed - {verification.claim.value:,.4g} "
            f"({verification.claim.text[:80]}): {verification.detail}"
        )

    return edited, warnings


def summarise(report: VerificationReport) -> dict[str, Any]:
    """Compact form for the audit log and the eval harness."""
    return {
        "checked": report.checked,
        "reconciled": report.reconciled,
        "failed": report.failed,
        "unchecked": report.unchecked,
        "groundedness": report.groundedness,
        "failures": [
            {
                "text": v.claim.text,
                "value": v.claim.value,
                "verdict": v.verdict.value,
                "matched": v.matched_value,
                "detail": v.detail,
            }
            for v in report.failures()
        ],
    }
