"""Evaluation: the golden set and the harness that runs it.

The system has four places it can go wrong independently, so it is measured in
four places rather than one:

* **Routing** - did the question go to the store that can answer it?
* **SQL** - did the generated query execute, and return the right value?
* **Retrieval** - were the right filing sections in the top-k?
* **Answer** - is the final text correct, grounded, and complete?

A single end-to-end score hides which of those broke, and every one of them has
a different fix. The report in `finlens/docs` reads these numbers directly.
"""

from finlens.eval.golden import GoldenCase, load_golden_set
from finlens.eval.harness import EvalReport, run_eval

__all__ = ["EvalReport", "GoldenCase", "load_golden_set", "run_eval"]
