"""Aircraft-history feature engineering: PREV_FLIGHT_DELAYED.

Motivation: our EDA found Late Aircraft Delay is the #1 delay cause (39.5% of
total delay minutes), yet the model had no feature describing the aircraft's
recent history. This script adds one.

PREV_FLIGHT_DELAYED = 1 if the same physical aircraft (TAIL_NUMBER)'s
immediately preceding flight had is_delayed = 1, else 0.

Dataset note: this runs on the 2015-only data (flights_clean.parquet). The
combined 2015+2016 raw files (data/raw_v2/) have no tail-number column at all,
so the feature cannot be built for the _v2 dataset.

Run from project root: python3 src/feature_engineer.py
"""

from pyspark import StorageLevel
from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F

PROCESSED_DIR = "data/processed"
INPUT_PATH = f"{PROCESSED_DIR}/flights_clean.parquet"
OUTPUT_PATH = f"{PROCESSED_DIR}/flights_engineered.parquet"


def main():
    spark = (
        SparkSession.builder.appName("AirlineDelayAnalytics-FeatureEngineer")
        .master("local[*]")
        .config("spark.driver.memory", "4g")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")

    df = spark.read.parquet(INPUT_PATH)
    input_rows = df.count()
    print(f"Input rows (flights_clean.parquet, 2015): {input_rows}")

    null_tail_rows = df.filter(F.col("TAIL_NUMBER").isNull()).count()
    print(f"Rows with null TAIL_NUMBER: {null_tail_rows}")

    # Chronological order of one aircraft's flights. SCHEDULED_DEPARTURE is
    # local time (hhmm) at the origin airport; the continuity check below
    # measures how often that ordering links a flight to the leg that actually
    # delivered the aircraft. FLIGHT_NUMBER is only a deterministic tiebreaker.
    aircraft_window = Window.partitionBy("TAIL_NUMBER").orderBy(
        "YEAR", "MONTH", "DAY", "SCHEDULED_DEPARTURE", "FLIGHT_NUMBER"
    )

    # LEAKAGE CHECK -- why this feature is safe:
    # For flight N we read is_delayed from flight N-1 (the same aircraft's
    # previous leg) and nothing from flight N's own outcome. Flight N's only
    # contribution is its SCHEDULED date/time, which just positions it in the
    # sequence. Flight N-1's arrival delay is known to the airline before
    # flight N departs: the inbound aircraft has either landed late or is
    # visibly still en route/late, which is exactly how airlines anticipate
    # "late aircraft" delays. Caveat: it is known at departure time, not at
    # booking time. It fits a day-of-operations prediction, not a
    # weeks-ahead one.
    # Cancelled/diverted legs were already removed by clean.py, so "previous
    # flight" means the previous completed leg of that aircraft.
    prev_delayed = F.lag("is_delayed", 1).over(aircraft_window)
    prev_dest = F.lag("DESTINATION_AIRPORT", 1).over(aircraft_window)

    df = (
        df.withColumn("_prev_is_delayed", prev_delayed)
        .withColumn("_prev_dest", prev_dest)
        # Null tail numbers must not be chained together as if they were one
        # aircraft, so they get the default 0, like an aircraft's first flight.
        .withColumn(
            "_has_prev",
            F.col("TAIL_NUMBER").isNotNull() & F.col("_prev_is_delayed").isNotNull(),
        )
        .withColumn(
            "PREV_FLIGHT_DELAYED",
            F.when(F.col("_has_prev"), F.col("_prev_is_delayed")).otherwise(0).cast("int"),
        )
    )
    df.persist(StorageLevel.DISK_ONLY)

    output_rows = df.count()
    print(f"Output rows: {output_rows} (row count unchanged: {output_rows == input_rows})")

    no_prev = df.filter(~F.col("_has_prev")).count()
    first_flight = df.filter(
        F.col("TAIL_NUMBER").isNotNull() & F.col("_prev_is_delayed").isNull()
    ).count()
    print(
        f"Rows defaulted to PREV_FLIGHT_DELAYED=0 (no previous flight): {no_prev} "
        f"({no_prev / output_rows * 100:.3f}%) -- "
        f"{first_flight} aircraft-first-flights + {null_tail_rows} null-tail rows"
    )

    # Sanity check: for a correctly ordered sequence, the previous leg's
    # destination should be this leg's origin.
    with_prev = df.filter(F.col("_has_prev"))
    with_prev_count = with_prev.count()
    continuous = with_prev.filter(F.col("_prev_dest") == F.col("ORIGIN_AIRPORT")).count()
    print(
        f"Continuity check: previous leg's DESTINATION == this leg's ORIGIN for "
        f"{continuous}/{with_prev_count} rows ({continuous / with_prev_count * 100:.2f}%)"
    )

    print("\nPREV_FLIGHT_DELAYED distribution and delay rate of the current flight:")
    (
        df.groupBy("PREV_FLIGHT_DELAYED")
        .agg(
            F.count("*").alias("rows"),
            F.round(F.avg("is_delayed") * 100, 2).alias("pct_current_delayed"),
        )
        .orderBy("PREV_FLIGHT_DELAYED")
        .show()
    )

    df = df.drop("_prev_is_delayed", "_prev_dest", "_has_prev")
    df.write.mode("overwrite").parquet(OUTPUT_PATH)

    written = spark.read.parquet(OUTPUT_PATH)
    print(f"Saved {written.count()} rows to {OUTPUT_PATH}")
    written.select(
        "TAIL_NUMBER", "MONTH", "DAY", "SCHEDULED_DEPARTURE", "ORIGIN_AIRPORT",
        "DESTINATION_AIRPORT", "is_delayed", "PREV_FLIGHT_DELAYED",
    ).filter(F.col("TAIL_NUMBER") == "N407AS").orderBy(
        "MONTH", "DAY", "SCHEDULED_DEPARTURE"
    ).show(8)

    df.unpersist()
    spark.stop()


if __name__ == "__main__":
    main()
