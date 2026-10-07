"""Extra aggregates for the ARRIVALS dashboard (combined 2015+2016 dataset).

Writes only new outputs -- the verified tables from aggregate_v2.py are not
touched:
  f. agg_by_dow_hour_v2         national DAY_OF_WEEK x SCHEDULED_DEPARTURE_HOUR
  g. agg_airport_breakdown_v2   busy airport x {airline, hour, dayofweek, month}
  h. agg_airport_dow_hour_v2    busy airport x DAY_OF_WEEK x hour
  i. delay_minutes_v2.json      mean ARRIVAL_DELAY, overall and for late flights

"Busy airport" uses the same rule as agg_by_airport_v2 (3-letter IATA origin
code, more than 10,000 flights), so every airport on the dashboard map has a
breakdown.

Run from project root: python3 src/aggregate_dashboard_v2.py
"""

import json

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

PROCESSED_DIR = "data/processed"
METRICS_DIR = "outputs/metrics"
IATA_CODE_PATTERN = "^[A-Z]{3}$"
BUSY_AIRPORT_MIN_FLIGHTS = 10000

# dimension name used by the API -> column in flights_clean_v2
BREAKDOWN_DIMENSIONS = {
    "airline": "AIRLINE_NAME",
    "hour": "SCHEDULED_DEPARTURE_HOUR",
    "dayofweek": "DAY_OF_WEEK",
    "month": "MONTH",
}


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
        SparkSession.builder.appName("AirlineDelayAnalytics-AggregateDashboard-V2")
        .master("local[*]")
        .config("spark.driver.memory", "4g")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")

    # Only the columns these aggregates need. No persist(): a DISK_ONLY cache
    # of the full 35-column table ran this machine out of disk, and re-reading
    # 7 columns from columnar parquet per aggregate is cheap.
    df = spark.read.parquet(f"{PROCESSED_DIR}/flights_clean_v2.parquet").select(
        "ORIGIN_AIRPORT",
        "AIRLINE_NAME",
        "SCHEDULED_DEPARTURE_HOUR",
        "DAY_OF_WEEK",
        "MONTH",
        "ARRIVAL_DELAY",
        "is_delayed",
    )
    total_rows = df.count()
    print(f"Input rows (flights_clean_v2): {total_rows}")

    # f. National weekday x hour grid
    by_dow_hour = delay_rate_agg(df, ["DAY_OF_WEEK", "SCHEDULED_DEPARTURE_HOUR"]).orderBy(
        "DAY_OF_WEEK", "SCHEDULED_DEPARTURE_HOUR"
    )
    save(by_dow_hour, "agg_by_dow_hour_v2")
    dow_hour_rows = by_dow_hour.count()
    dow_hour_flights = by_dow_hour.agg(F.sum("total_flights")).collect()[0][0]
    print(
        f"(f) agg_by_dow_hour_v2: {dow_hour_rows} cells (max 7x24=168), "
        f"{dow_hour_flights} flights (should equal input rows)"
    )

    # Busy-airport subset, same rule as agg_by_airport_v2
    valid_airport_df = df.filter(F.col("ORIGIN_AIRPORT").rlike(IATA_CODE_PATTERN))
    busy_airports = (
        valid_airport_df.groupBy("ORIGIN_AIRPORT")
        .count()
        .filter(F.col("count") > BUSY_AIRPORT_MIN_FLIGHTS)
        .select("ORIGIN_AIRPORT")
    )
    busy_df = valid_airport_df.join(F.broadcast(busy_airports), "ORIGIN_AIRPORT")
    busy_rows = busy_df.count()
    print(
        f"Busy-airport subset: {busy_airports.count()} airports, {busy_rows} of "
        f"{total_rows} rows ({total_rows - busy_rows} rows at non-IATA or "
        f"<= {BUSY_AIRPORT_MIN_FLIGHTS}-flight airports excluded)"
    )

    # g. Per-airport breakdowns, one long table
    breakdowns = None
    for dimension, column in BREAKDOWN_DIMENSIONS.items():
        part = (
            delay_rate_agg(busy_df, ["ORIGIN_AIRPORT", column])
            .withColumnRenamed(column, "name")
            .withColumn("name", F.col("name").cast("string"))
            .withColumn("dimension", F.lit(dimension))
            .select("ORIGIN_AIRPORT", "dimension", "name", "total_flights", "total_delayed", "delay_pct")
        )
        breakdowns = part if breakdowns is None else breakdowns.unionByName(part)
    breakdowns = breakdowns.orderBy("ORIGIN_AIRPORT", "dimension", "name")
    save(breakdowns, "agg_airport_breakdown_v2")
    print("(g) agg_airport_breakdown_v2 rows per dimension (flights should equal busy subset):")
    breakdowns.groupBy("dimension").agg(
        F.count("*").alias("rows"), F.sum("total_flights").alias("flights")
    ).orderBy("dimension").show(truncate=False)

    # h. Per-airport weekday x hour grid
    airport_dow_hour = delay_rate_agg(
        busy_df, ["ORIGIN_AIRPORT", "DAY_OF_WEEK", "SCHEDULED_DEPARTURE_HOUR"]
    ).orderBy("ORIGIN_AIRPORT", "DAY_OF_WEEK", "SCHEDULED_DEPARTURE_HOUR")
    save(airport_dow_hour, "agg_airport_dow_hour_v2")
    adh_rows = airport_dow_hour.count()
    small_cells = airport_dow_hour.filter(F.col("total_flights") < 30).count()
    print(
        f"(h) agg_airport_dow_hour_v2: {adh_rows} cells, {small_cells} with < 30 "
        f"flights (dashboard greys these out rather than showing a noisy rate)"
    )

    # i. Delay minutes. ARRIVAL_DELAY is signed (early arrivals are negative),
    # so report both the all-flights mean and the mean over late flights.
    minutes = df.agg(
        F.avg("ARRIVAL_DELAY").alias("mean_all"),
        F.avg(F.when(F.col("is_delayed") == 1, F.col("ARRIVAL_DELAY"))).alias("mean_late"),
        F.expr("percentile_approx(CASE WHEN is_delayed = 1 THEN ARRIVAL_DELAY END, 0.5)").alias(
            "median_late"
        ),
        F.sum("is_delayed").alias("late_flights"),
    ).collect()[0]
    delay_minutes = {
        "mean_arrival_delay_all_min": round(float(minutes["mean_all"]), 2),
        "mean_arrival_delay_late_min": round(float(minutes["mean_late"]), 2),
        "median_arrival_delay_late_min": float(minutes["median_late"]),
        "late_flights": int(minutes["late_flights"]),
        "total_flights": total_rows,
        "late_threshold_min": 15,
    }
    with open(f"{METRICS_DIR}/delay_minutes_v2.json", "w") as f:
        json.dump(delay_minutes, f, indent=2)
    print("(i) delay_minutes_v2.json:")
    print(json.dumps(delay_minutes, indent=2))

    print("\nSample: national weekday x hour, Friday 15:00-20:00")
    by_dow_hour.filter(
        (F.col("DAY_OF_WEEK") == 5) & F.col("SCHEDULED_DEPARTURE_HOUR").between(15, 20)
    ).show(truncate=False)

    spark.stop()


if __name__ == "__main__":
    main()
