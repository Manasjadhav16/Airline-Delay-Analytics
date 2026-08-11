"""Ingest raw flights/airlines/airports CSVs and produce a joined parquet dataset.

Run from project root: python3 src/ingest.py
"""

from pyspark.sql import SparkSession
from pyspark.sql.types import (
    StructType,
    StructField,
    IntegerType,
    StringType,
    DoubleType,
)

RAW_DIR = "data/raw"
PROCESSED_DIR = "data/processed"

# Explicit schema for flights.csv (5.8M rows) — avoid inferSchema, it forces a
# full extra pass over the file just to guess types.
FLIGHTS_SCHEMA = StructType(
    [
        StructField("YEAR", IntegerType(), True),
        StructField("MONTH", IntegerType(), True),
        StructField("DAY", IntegerType(), True),
        StructField("DAY_OF_WEEK", IntegerType(), True),
        StructField("AIRLINE", StringType(), True),
        StructField("FLIGHT_NUMBER", IntegerType(), True),
        StructField("TAIL_NUMBER", StringType(), True),
        StructField("ORIGIN_AIRPORT", StringType(), True),
        StructField("DESTINATION_AIRPORT", StringType(), True),
        StructField("SCHEDULED_DEPARTURE", IntegerType(), True),
        StructField("DEPARTURE_TIME", IntegerType(), True),
        StructField("DEPARTURE_DELAY", DoubleType(), True),
        StructField("TAXI_OUT", DoubleType(), True),
        StructField("WHEELS_OFF", IntegerType(), True),
        StructField("SCHEDULED_TIME", DoubleType(), True),
        StructField("ELAPSED_TIME", DoubleType(), True),
        StructField("AIR_TIME", DoubleType(), True),
        StructField("DISTANCE", IntegerType(), True),
        StructField("WHEELS_ON", IntegerType(), True),
        StructField("TAXI_IN", DoubleType(), True),
        StructField("SCHEDULED_ARRIVAL", IntegerType(), True),
        StructField("ARRIVAL_TIME", IntegerType(), True),
        StructField("ARRIVAL_DELAY", DoubleType(), True),
        StructField("DIVERTED", IntegerType(), True),
        StructField("CANCELLED", IntegerType(), True),
        StructField("CANCELLATION_REASON", StringType(), True),
        StructField("AIR_SYSTEM_DELAY", DoubleType(), True),
        StructField("SECURITY_DELAY", DoubleType(), True),
        StructField("AIRLINE_DELAY", DoubleType(), True),
        StructField("LATE_AIRCRAFT_DELAY", DoubleType(), True),
        StructField("WEATHER_DELAY", DoubleType(), True),
    ]
)

AIRLINES_SCHEMA = StructType(
    [
        StructField("IATA_CODE", StringType(), True),
        StructField("AIRLINE", StringType(), True),
    ]
)

AIRPORTS_SCHEMA = StructType(
    [
        StructField("IATA_CODE", StringType(), True),
        StructField("AIRPORT", StringType(), True),
        StructField("CITY", StringType(), True),
        StructField("STATE", StringType(), True),
        StructField("COUNTRY", StringType(), True),
        StructField("LATITUDE", DoubleType(), True),
        StructField("LONGITUDE", DoubleType(), True),
    ]
)


def main():
    spark = (
        SparkSession.builder.appName("AirlineDelayAnalytics-Ingest")
        .master("local[*]")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")

    flights = spark.read.csv(
        f"{RAW_DIR}/flights.csv", header=True, schema=FLIGHTS_SCHEMA
    )
    airlines = spark.read.csv(
        f"{RAW_DIR}/airlines.csv", header=True, schema=AIRLINES_SCHEMA
    )
    airports = spark.read.csv(
        f"{RAW_DIR}/airports.csv", header=True, schema=AIRPORTS_SCHEMA
    )

    # Join airline full name (rename to avoid colliding with flights.AIRLINE code column)
    airlines_renamed = airlines.withColumnRenamed("AIRLINE", "AIRLINE_NAME")
    joined = flights.join(
        airlines_renamed,
        flights["AIRLINE"] == airlines_renamed["IATA_CODE"],
        "left",
    ).drop(airlines_renamed["IATA_CODE"])

    # Join origin airport city/state
    origin_airports = (
        airports.withColumnRenamed("CITY", "ORIGIN_CITY")
        .withColumnRenamed("STATE", "ORIGIN_STATE")
        .select("IATA_CODE", "ORIGIN_CITY", "ORIGIN_STATE")
    )
    joined = joined.join(
        origin_airports,
        joined["ORIGIN_AIRPORT"] == origin_airports["IATA_CODE"],
        "left",
    ).drop(origin_airports["IATA_CODE"])

    row_count = joined.count()
    print(f"\nJoined row count: {row_count}\n")

    print("Joined schema:")
    joined.printSchema()

    joined.write.mode("overwrite").parquet(f"{PROCESSED_DIR}/flights_joined.parquet")

    print("\nSample rows:")
    joined.select(
        "YEAR",
        "MONTH",
        "DAY",
        "AIRLINE",
        "AIRLINE_NAME",
        "ORIGIN_AIRPORT",
        "ORIGIN_CITY",
        "ORIGIN_STATE",
        "DESTINATION_AIRPORT",
        "ARRIVAL_DELAY",
    ).show(5, truncate=False)

    spark.stop()


if __name__ == "__main__":
    main()
