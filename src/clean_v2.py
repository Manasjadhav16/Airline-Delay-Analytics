"""Clean the joined combined (2015+2016) dataset and build the is_delayed label.

Identical logic to src/clean.py -- only the input/output paths differ, since
src/ingest_v2.py already normalized the raw_v2 columns to match the original
pipeline's naming convention.

Run from project root: python3 src/clean_v2.py
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

PROCESSED_DIR = "data/processed"

DELAY_CAUSE_COLUMNS = [
    "AIR_SYSTEM_DELAY",
    "SECURITY_DELAY",
    "AIRLINE_DELAY",
    "LATE_AIRCRAFT_DELAY",
    "WEATHER_DELAY",
]


def main():
    spark = (
        SparkSession.builder.appName("AirlineDelayAnalytics-Clean-V2")
        .master("local[*]")
        .config("spark.driver.memory", "4g")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")

    df = spark.read.parquet(f"{PROCESSED_DIR}/flights_joined_v2.parquet")

    total_rows = df.count()
    print(f"\nStarting row count: {total_rows}")

    cancelled_count = df.filter(F.col("CANCELLED") == 1).count()
    diverted_count = df.filter((F.col("CANCELLED") != 1) & (F.col("DIVERTED") == 1)).count()
    print(f"Rows dropped for CANCELLED == 1: {cancelled_count}")
    print(f"Rows dropped for DIVERTED == 1 (excluding already-cancelled): {diverted_count}")

    df = df.filter((F.col("CANCELLED") != 1) & (F.col("DIVERTED") != 1))
    after_filter_rows = df.count()
    print(f"Row count after dropping cancelled/diverted: {after_filter_rows}")

    df = df.fillna(0, subset=DELAY_CAUSE_COLUMNS)

    df = df.withColumn(
        "is_delayed", F.when(F.col("ARRIVAL_DELAY") >= 15, 1).otherwise(0)
    )

    delayed_count = df.filter(F.col("is_delayed") == 1).count()
    on_time_count = after_filter_rows - delayed_count
    pct_delayed = 100.0 * delayed_count / after_filter_rows
    pct_on_time = 100.0 * on_time_count / after_filter_rows
    print(
        f"\nClass balance — delayed: {delayed_count} ({pct_delayed:.2f}%), "
        f"on-time: {on_time_count} ({pct_on_time:.2f}%)"
    )

    df = df.withColumn("SCHEDULED_DEPARTURE_HOUR", (F.col("SCHEDULED_DEPARTURE") / 100).cast("int"))

    final_row_count = df.count()
    print(f"\nFinal row count: {final_row_count}")

    df.write.mode("overwrite").parquet(f"{PROCESSED_DIR}/flights_clean_v2.parquet")

    print("\nSample rows:")
    df.select(
        "YEAR",
        "MONTH",
        "DAY",
        "AIRLINE",
        "SCHEDULED_DEPARTURE",
        "SCHEDULED_DEPARTURE_HOUR",
        "ARRIVAL_DELAY",
        "is_delayed",
        "AIR_SYSTEM_DELAY",
        "SECURITY_DELAY",
        "AIRLINE_DELAY",
        "LATE_AIRCRAFT_DELAY",
        "WEATHER_DELAY",
    ).show(5, truncate=False)

    spark.stop()


if __name__ == "__main__":
    main()
