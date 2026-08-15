"""Ingest the combined 2015+2016 dataset (data/raw_v2/) and produce a joined parquet.

IMPORTANT SCHEMA NOTE: despite both datasets covering the same underlying
2015 flights, data/raw_v2/*.csv (Kaggle yuanyuwendymu/airline-delay-and-cancellation-
data-2009-2018) uses COMPLETELY DIFFERENT COLUMN NAMES than data/raw/flights.csv
(Kaggle usdot/flight-delays) -- e.g. FL_DATE instead of YEAR/MONTH/DAY/DAY_OF_WEEK,
OP_CARRIER instead of AIRLINE, ARR_DELAY instead of ARRIVAL_DELAY. Reusing
src/ingest.py's FLIGHTS_SCHEMA positionally against these files would silently
misalign every column (e.g. the FL_DATE string forced into the YEAR IntegerType
slot -> nulls or a corrupt read). This script defines a schema matching
raw_v2's ACTUAL columns, then renames/derives everything to match the original
pipeline's naming convention, so clean_v2.py/aggregate_v2.py/model_v2.py can
reuse the exact same downstream logic unchanged.

Run from project root: python3 src/ingest_v2.py
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType,
    StructField,
    IntegerType,
    StringType,
    DoubleType,
)

RAW_V2_DIR = "data/raw_v2"
RAW_DIR = "data/raw"  # airlines.csv / airports.csv lookup tables (unchanged)
PROCESSED_DIR = "data/processed"

YEAR_FILES = ["2015.csv", "2016.csv"]

# Matches raw_v2's actual header order/types (verified against real sample
# rows) -- NOT the same as src/ingest.py's FLIGHTS_SCHEMA.
RAW_V2_SCHEMA = StructType(
    [
        StructField("FL_DATE", StringType(), True),
        StructField("OP_CARRIER", StringType(), True),
        StructField("OP_CARRIER_FL_NUM", IntegerType(), True),
        StructField("ORIGIN", StringType(), True),
        StructField("DEST", StringType(), True),
        StructField("CRS_DEP_TIME", IntegerType(), True),
        StructField("DEP_TIME", DoubleType(), True),
        StructField("DEP_DELAY", DoubleType(), True),
        StructField("TAXI_OUT", DoubleType(), True),
        StructField("WHEELS_OFF", DoubleType(), True),
        StructField("WHEELS_ON", DoubleType(), True),
        StructField("TAXI_IN", DoubleType(), True),
        StructField("CRS_ARR_TIME", IntegerType(), True),
        StructField("ARR_TIME", DoubleType(), True),
        StructField("ARR_DELAY", DoubleType(), True),
        StructField("CANCELLED", DoubleType(), True),
        StructField("CANCELLATION_CODE", StringType(), True),
        StructField("DIVERTED", DoubleType(), True),
        StructField("CRS_ELAPSED_TIME", DoubleType(), True),
        StructField("ACTUAL_ELAPSED_TIME", DoubleType(), True),
        StructField("AIR_TIME", DoubleType(), True),
        StructField("DISTANCE", DoubleType(), True),
        StructField("CARRIER_DELAY", DoubleType(), True),
        StructField("WEATHER_DELAY", DoubleType(), True),
        StructField("NAS_DELAY", DoubleType(), True),
        StructField("SECURITY_DELAY", DoubleType(), True),
        StructField("LATE_AIRCRAFT_DELAY", DoubleType(), True),
        StructField("UNNAMED_27", StringType(), True),  # trailing junk column, always blank
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


def rename_to_pipeline_schema(df):
    """Rename/derive raw_v2 columns to match src/ingest.py's original naming
    convention, so downstream stages don't need to know which raw dataset
    this came from."""
    df = (
        df.withColumn("YEAR", F.year("FL_DATE"))
        .withColumn("MONTH", F.month("FL_DATE"))
        .withColumn("DAY", F.dayofmonth("FL_DATE"))
        # ISO day-of-week (Monday=1 ... Sunday=7), matching the convention
        # already used in src/ingest.py's source data. Spark's dayofweek()
        # returns Sunday=1..Saturday=7; the 'u' date_format pattern would give
        # this directly but was removed in Spark 3.0, so convert arithmetically.
        .withColumn("DAY_OF_WEEK", ((F.dayofweek("FL_DATE") + 5) % 7) + 1)
        .withColumnRenamed("OP_CARRIER", "AIRLINE")
        .withColumnRenamed("OP_CARRIER_FL_NUM", "FLIGHT_NUMBER")
        .withColumnRenamed("ORIGIN", "ORIGIN_AIRPORT")
        .withColumnRenamed("DEST", "DESTINATION_AIRPORT")
        .withColumnRenamed("CRS_DEP_TIME", "SCHEDULED_DEPARTURE")
        .withColumnRenamed("DEP_TIME", "DEPARTURE_TIME")
        .withColumnRenamed("DEP_DELAY", "DEPARTURE_DELAY")
        .withColumnRenamed("CRS_ELAPSED_TIME", "SCHEDULED_TIME")
        .withColumnRenamed("ACTUAL_ELAPSED_TIME", "ELAPSED_TIME")
        .withColumn("DISTANCE", F.col("DISTANCE").cast("int"))
        .withColumnRenamed("CRS_ARR_TIME", "SCHEDULED_ARRIVAL")
        .withColumnRenamed("ARR_TIME", "ARRIVAL_TIME")
        .withColumnRenamed("ARR_DELAY", "ARRIVAL_DELAY")
        .withColumn("DIVERTED", F.col("DIVERTED").cast("int"))
        .withColumn("CANCELLED", F.col("CANCELLED").cast("int"))
        .withColumnRenamed("CANCELLATION_CODE", "CANCELLATION_REASON")
        .withColumnRenamed("CARRIER_DELAY", "AIRLINE_DELAY")
        .withColumnRenamed("NAS_DELAY", "AIR_SYSTEM_DELAY")
        .drop("FL_DATE", "UNNAMED_27")
    )
    return df


def main():
    spark = (
        SparkSession.builder.appName("AirlineDelayAnalytics-Ingest-V2")
        .master("local[*]")
        .config("spark.driver.memory", "4g")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")

    year_dfs = [
        spark.read.csv(f"{RAW_V2_DIR}/{f}", header=True, schema=RAW_V2_SCHEMA)
        for f in YEAR_FILES
    ]
    flights_raw = year_dfs[0]
    for extra_df in year_dfs[1:]:
        flights_raw = flights_raw.unionByName(extra_df)

    flights = rename_to_pipeline_schema(flights_raw)

    airlines = spark.read.csv(f"{RAW_DIR}/airlines.csv", header=True, schema=AIRLINES_SCHEMA)
    airports = spark.read.csv(f"{RAW_DIR}/airports.csv", header=True, schema=AIRPORTS_SCHEMA)

    # Check for AIRLINE codes not covered by our 2015-only airlines.csv lookup
    # (2016 may include carriers absent from the 14-row 2015 lookup table) --
    # print them rather than silently dropping/nulling them.
    known_codes = [row["IATA_CODE"] for row in airlines.select("IATA_CODE").collect()]
    unmatched = (
        flights.filter(~F.col("AIRLINE").isin(known_codes))
        .groupBy("AIRLINE")
        .count()
        .orderBy(F.desc("count"))
        .collect()
    )
    if unmatched:
        print(f"\nWARNING: {len(unmatched)} AIRLINE code(s) in the combined data are NOT in airlines.csv's {len(known_codes)} entries:")
        for row in unmatched:
            print(f"  {row['AIRLINE']}: {row['count']} rows (will have null AIRLINE_NAME after the left join)")
    else:
        print(f"\nAll AIRLINE codes in the combined data are covered by airlines.csv's {len(known_codes)} entries.")

    airlines_renamed = airlines.withColumnRenamed("AIRLINE", "AIRLINE_NAME")
    joined = flights.join(
        airlines_renamed, flights["AIRLINE"] == airlines_renamed["IATA_CODE"], "left"
    ).drop(airlines_renamed["IATA_CODE"])

    origin_airports = (
        airports.withColumnRenamed("CITY", "ORIGIN_CITY")
        .withColumnRenamed("STATE", "ORIGIN_STATE")
        .select("IATA_CODE", "ORIGIN_CITY", "ORIGIN_STATE")
    )
    joined = joined.join(
        origin_airports, joined["ORIGIN_AIRPORT"] == origin_airports["IATA_CODE"], "left"
    ).drop(origin_airports["IATA_CODE"])

    row_count = joined.count()
    print(f"\nJoined row count (2015+2016 combined): {row_count}\n")

    print("Joined schema:")
    joined.printSchema()

    joined.write.mode("overwrite").parquet(f"{PROCESSED_DIR}/flights_joined_v2.parquet")

    print("\nSample rows:")
    joined.select(
        "YEAR", "MONTH", "DAY", "DAY_OF_WEEK", "AIRLINE", "AIRLINE_NAME",
        "ORIGIN_AIRPORT", "ORIGIN_CITY", "ORIGIN_STATE",
        "DESTINATION_AIRPORT", "ARRIVAL_DELAY",
    ).show(5, truncate=False)

    spark.stop()


if __name__ == "__main__":
    main()
