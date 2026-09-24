{% macro sic_sector(sic_column) %}
    {#-
      Map a 4-digit SIC code to a coarse sector.

      SIC is the only industry classification EDGAR publishes, and it is both
      dated and coarse. It is used here for filtering and grouping ("compare to
      other software companies"), not as an authoritative taxonomy - GICS would
      be better and is not free.

      Division boundaries follow the SEC's own SIC division table.
    -#}
    case
        when {{ sic_column }} is null then null
        when cast({{ sic_column }} as integer) between  100 and  999 then 'Agriculture'
        when cast({{ sic_column }} as integer) between 1000 and 1499 then 'Mining'
        when cast({{ sic_column }} as integer) between 1500 and 1799 then 'Construction'
        when cast({{ sic_column }} as integer) between 2000 and 3999 then 'Manufacturing'
        when cast({{ sic_column }} as integer) between 4000 and 4999 then 'Transportation & Utilities'
        when cast({{ sic_column }} as integer) between 5000 and 5199 then 'Wholesale Trade'
        when cast({{ sic_column }} as integer) between 5200 and 5999 then 'Retail Trade'
        when cast({{ sic_column }} as integer) between 6000 and 6799 then 'Finance & Real Estate'
        when cast({{ sic_column }} as integer) between 7000 and 8999 then 'Services'
        when cast({{ sic_column }} as integer) between 9100 and 9729 then 'Public Administration'
        else 'Other'
    end
{% endmacro %}
