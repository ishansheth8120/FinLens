{% macro safe_divide(numerator, denominator) %}
    {#-
      Division that returns NULL instead of raising or returning infinity.

      Financial data hits every degenerate case: a pre-revenue company divides
      by zero, a company emerging from losses divides by a negative base (where
      a "growth rate" is meaningless rather than merely large), and a missing
      tag divides by NULL. NULL is the honest answer to all three, and it keeps
      one bad row from failing an entire model build.
    -#}
    case
        when {{ denominator }} is null then null
        when {{ denominator }} = 0     then null
        else ({{ numerator }}) * 1.0 / ({{ denominator }})
    end
{% endmacro %}


{% macro pct_change(current_value, prior_value) %}
    {#- Percent change with the same guards, expressed as a fraction. -#}
    {{ safe_divide(current_value ~ ' - ' ~ prior_value, 'abs(' ~ prior_value ~ ')') }}
{% endmacro %}
