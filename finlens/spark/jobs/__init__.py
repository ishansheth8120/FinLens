"""Runnable Spark jobs.

Each module exposes a ``run(spark, settings, **kwargs)`` function and a
``__main__`` guard, so it works both as an import (Airflow, tests) and as a
``spark-submit`` target:

    spark-submit --master local[*] -m finlens.spark.jobs.bronze_companyfacts
"""
