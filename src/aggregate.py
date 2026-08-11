"""Aggregate the cleaned flights dataset into delay-rate summary tables.

Run from project root: python3 src/aggregate.py
"""

import json

from pyspark import StorageLevel
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

PROCESSED_DIR = "data/processed"
METRICS_DIR = "outputs/metrics"

DELAY_CAUSE_COLUMNS = [
    "AIRLINE_DELAY",
    "WEATHER_DELAY",
    "AIR_SYSTEM_DELAY",
    "SECURITY_DELAY",
    "LATE_AIRCRAFT_DELAY",
]


def delay_rate_agg(df, group_cols):
    return (
        df.groupBy(*group_cols)
        .agg(
            F.count("*").alias("total_flights"),
            F.sum("is_delayed").alias("total_delayed"),
        )
        .withColumn(
            "delay_pct",
            F.round(100.0 * F.col("total_delayed") / F.col("total_flights"), 2),
        )
    )


def save(df, name):
    df.coalesce(1).write.mode("overwrite").parquet(f"{PROCESSED_DIR}/{name}.parquet")
    df.coalesce(1).write.mode("overwrite").option("header", True).csv(
        f"{PROCESSED_DIR}/{name}.csv"
    )


def main():
    spark = (
        SparkSession.builder.appName("AirlineDelayAnalytics-Aggregate")
        .master("local[*]")
        .config("spark.driver.memory", "4g")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")

    df = spark.read.parquet(f"{PROCESSED_DIR}/flights_clean.parquet")
    df.persist(StorageLevel.DISK_ONLY)

    # a. By AIRLINE_NAME
    by_airline = delay_rate_agg(df, ["AIRLINE_NAME"]).orderBy(F.desc("delay_pct"))
    save(by_airline, "agg_by_airline")

    # b. By ORIGIN_AIRPORT, filtered to busy airports.
    # ~8.4% of rows (all of October 2015) use numeric DOT airport IDs instead
    # of 3-letter IATA codes (a known quirk of the source dataset) — those
    # never joined against airports.csv and would show up as junk numeric
    # "airports" here, so exclude them from this airport-keyed view only.
    IATA_CODE_PATTERN = "^[A-Z]{3}$"
    airport_rows_before = df.select("ORIGIN_AIRPORT").count()
    valid_airport_df = df.filter(F.col("ORIGIN_AIRPORT").rlike(IATA_CODE_PATTERN))
    airport_rows_after = valid_airport_df.count()
    airport_rows_excluded = airport_rows_before - airport_rows_after
    print(
        f"By-airport aggregation: excluded {airport_rows_excluded} rows with "
        f"non-IATA ORIGIN_AIRPORT codes (kept {airport_rows_after} of "
        f"{airport_rows_before})"
    )

    by_airport = (
        delay_rate_agg(valid_airport_df, ["ORIGIN_AIRPORT"])
        .filter(F.col("total_flights") > 10000)
        .orderBy(F.desc("total_flights"))
    )
    save(by_airport, "agg_by_airport")

    # c. By SCHEDULED_DEPARTURE_HOUR
    by_hour = delay_rate_agg(df, ["SCHEDULED_DEPARTURE_HOUR"]).orderBy(
        F.asc("SCHEDULED_DEPARTURE_HOUR")
    )
    save(by_hour, "agg_by_hour")

    # d. By DAY_OF_WEEK
    by_dow = delay_rate_agg(df, ["DAY_OF_WEEK"]).orderBy(F.asc("DAY_OF_WEEK"))
    save(by_dow, "agg_by_day_of_week")

    # e. By MONTH
    by_month = delay_rate_agg(df, ["MONTH"]).orderBy(F.asc("MONTH"))
    save(by_month, "agg_by_month")

    # Overall delay-cause totals (minutes), for a pie chart later
    cause_sums = df.agg(
        *[F.sum(c).alias(c) for c in DELAY_CAUSE_COLUMNS]
    ).collect()[0]
    cause_totals = {c: float(cause_sums[c] or 0.0) for c in DELAY_CAUSE_COLUMNS}

    with open(f"{METRICS_DIR}/delay_cause_totals.json", "w") as f:
        json.dump(cause_totals, f, indent=2)

    # Top-level summary
    total_rows = df.count()
    total_delayed = df.filter(F.col("is_delayed") == 1).count()
    overall_delay_pct = round(100.0 * total_delayed / total_rows, 2)
    unique_airlines = df.select("AIRLINE_NAME").distinct().count()
    unique_airports = df.select("ORIGIN_AIRPORT").distinct().count()
    unique_airports_valid = valid_airport_df.select("ORIGIN_AIRPORT").distinct().count()

    print("\n=== Aggregation results ===")

    print("\n(a) Delay rate by airline (top 10, sorted by delay_pct desc):")
    by_airline.show(10, truncate=False)

    print("(b) Delay rate by origin airport, total_flights > 10000 (top 10, sorted by total_flights desc):")
    by_airport.show(10, truncate=False)

    print("(c) Delay rate by scheduled departure hour (top 10, sorted by hour asc):")
    by_hour.show(10, truncate=False)

    print("(d) Delay rate by day of week (top 10, sorted by day asc):")
    by_dow.show(10, truncate=False)

    print("(e) Delay rate by month (top 10, sorted by month asc):")
    by_month.show(10, truncate=False)

    print("Overall delay-cause totals (minutes):")
    print(json.dumps(cause_totals, indent=2))

    print("\n=== Summary ===")
    print(f"Total rows: {total_rows}")
    print(f"Unique airlines: {unique_airlines}")
    print(f"Unique origin airports (raw, incl. non-IATA codes): {unique_airports}")
    print(f"Unique origin airports (valid 3-letter IATA codes only): {unique_airports_valid}")
    print(f"Overall delay percentage: {overall_delay_pct}% (sanity check vs 18.61% from clean.py)")

    df.unpersist()
    spark.stop()


if __name__ == "__main__":
    main()
