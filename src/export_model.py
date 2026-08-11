"""Train a lightweight scikit-learn delay model for the dashboard API.

Mirrors the Spark RandomForest model (same features, class-weighted for the
81.39% / 18.61% imbalance) but trained on a sample with scikit-learn so it can
be loaded directly by a FastAPI backend via joblib, without a Spark runtime.

Run from project root: python3 src/export_model.py
"""

import json
import re

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

PROCESSED_DIR = "data/processed"
MODEL_DIR = "backend/model"

SAMPLE_SIZE = 500_000
SEED = 42

FEATURE_COLS = [
    "AIRLINE_ENCODED",
    "ORIGIN_AIRPORT_ENCODED",
    "MONTH",
    "DAY_OF_WEEK",
    "SCHEDULED_DEPARTURE_HOUR",
    "DISTANCE",
]
LABEL_COL = "is_delayed"

IATA_CODE_PATTERN = re.compile(r"^[A-Z]{3}$")


def main():
    from pyspark.sql import SparkSession

    spark = (
        SparkSession.builder.appName("AirlineDelayAnalytics-ExportModel")
        .master("local[*]")
        .config("spark.driver.memory", "4g")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")

    full_df = spark.read.parquet(f"{PROCESSED_DIR}/flights_clean.parquet")
    total_rows = full_df.count()

    sample_fraction = min(1.0, SAMPLE_SIZE / total_rows)
    sample_df = full_df.select(
        "AIRLINE",
        "ORIGIN_AIRPORT",
        "MONTH",
        "DAY_OF_WEEK",
        "SCHEDULED_DEPARTURE_HOUR",
        "DISTANCE",
        LABEL_COL,
    ).sample(withReplacement=False, fraction=sample_fraction, seed=SEED)

    pdf = sample_df.toPandas()
    spark.stop()

    print(f"Full cleaned dataset: {total_rows} rows")
    print(f"Sampled {len(pdf)} rows (~{SAMPLE_SIZE} target) for scikit-learn training")

    # Label-encode AIRLINE and ORIGIN_AIRPORT, mirroring the Spark StringIndexer step.
    airline_encoder = LabelEncoder()
    pdf["AIRLINE_ENCODED"] = airline_encoder.fit_transform(pdf["AIRLINE"])

    airport_encoder = LabelEncoder()
    pdf["ORIGIN_AIRPORT_ENCODED"] = airport_encoder.fit_transform(pdf["ORIGIN_AIRPORT"])

    X = pdf[FEATURE_COLS]
    y = pdf[LABEL_COL]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=SEED, stratify=y
    )
    print(f"Train rows: {len(X_train)}, Test rows: {len(X_test)}")

    model = RandomForestClassifier(
        n_estimators=50,
        max_depth=8,
        class_weight="balanced",
        random_state=SEED,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    auc = roc_auc_score(y_test, y_proba)
    precision = precision_score(y_test, y_pred, pos_label=1)
    recall = recall_score(y_test, y_pred, pos_label=1)
    f1 = f1_score(y_test, y_pred, pos_label=1)

    print("\n=== scikit-learn RandomForest evaluation (threshold=0.5, delayed class) ===")
    print(f"AUC:       {round(auc, 4)} (Spark ballpark: ~0.63-0.65)")
    print(f"Precision: {round(precision, 4)}")
    print(f"Recall:    {round(recall, 4)} (Spark ballpark: ~60%)")
    print(f"F1:        {round(f1, 4)}")

    joblib.dump(model, f"{MODEL_DIR}/delay_model.joblib")
    joblib.dump(airline_encoder, f"{MODEL_DIR}/airline_encoder.joblib")
    joblib.dump(airport_encoder, f"{MODEL_DIR}/airport_encoder.joblib")

    # The model itself still trains on/encodes every category in the sample,
    # including the ~8.4% of rows (all of October 2015) that use numeric DOT
    # airport IDs instead of 3-letter IATA codes (a known source-dataset quirk
    # — see aggregate.py). This filter only affects the human-facing dropdown
    # list so the dashboard doesn't show numeric junk airports.
    all_airports = airport_encoder.classes_.tolist()
    valid_airports = sorted(a for a in all_airports if IATA_CODE_PATTERN.match(a))
    excluded_airport_count = len(all_airports) - len(valid_airports)
    print(
        f"\nAirport dropdown filter: excluded {excluded_airport_count} non-IATA "
        f"codes from feature_metadata.json (kept {len(valid_airports)} of "
        f"{len(all_airports)}); model training was unaffected."
    )

    feature_metadata = {
        "feature_order": FEATURE_COLS,
        "airlines": sorted(airline_encoder.classes_.tolist()),
        "airports": valid_airports,
    }
    with open(f"{MODEL_DIR}/feature_metadata.json", "w") as f:
        json.dump(feature_metadata, f, indent=2)

    print(f"\nSaved model to {MODEL_DIR}/delay_model.joblib")
    print(f"Saved airline encoder to {MODEL_DIR}/airline_encoder.joblib")
    print(f"Saved airport encoder to {MODEL_DIR}/airport_encoder.joblib")
    print(f"Saved feature metadata to {MODEL_DIR}/feature_metadata.json")
    print(
        f"  ({len(feature_metadata['airlines'])} airlines, "
        f"{len(feature_metadata['airports'])} airports)"
    )


if __name__ == "__main__":
    main()
