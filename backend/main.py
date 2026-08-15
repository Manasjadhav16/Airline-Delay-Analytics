"""FastAPI backend for the Airline Delay Analytics dashboard.

Serves delay predictions from the scikit-learn model exported by
src/export_model_v2.py (trained on the combined 2015+2016 dataset), plus
dashboard chart data from aggregate_v2.py's CSV outputs. The original
single-year model/aggregate files are left on disk untouched for
comparison/fallback -- this backend just points at the _v2 versions.

Run from project root: uvicorn backend.main:app --reload
"""

import glob
import json
from contextlib import asynccontextmanager

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

MODEL_DIR = "backend/model"
PROCESSED_DIR = "data/processed"
RAW_DIR = "data/raw"

# Threshold tuned against the delayed-class F1 sweep in an earlier session
# (Spark weighted RandomForest on the combined dataset, best F1 at threshold
# 0.5 -- same threshold as the single-year model, confirmed unchanged).
DELAY_THRESHOLD = 0.5

# From src/export_model_v2.py's held-out test evaluation (sklearn
# RandomForest, class_weight="balanced", threshold=0.5, combined 2015+2016
# dataset): precision=0.2499, recall=0.6196.
MODEL_RECALL = 0.6196
MODEL_PRECISION = 0.2499

STATS_CATEGORY_MAP = {
    "airline": ("agg_by_airline_v2", "AIRLINE_NAME"),
    "airport": ("agg_by_airport_v2", "ORIGIN_AIRPORT"),
    "hour": ("agg_by_hour_v2", "SCHEDULED_DEPARTURE_HOUR"),
    "dayofweek": ("agg_by_day_of_week_v2", "DAY_OF_WEEK"),
    "month": ("agg_by_month_v2", "MONTH"),
}

# Populated at startup by the lifespan handler below.
artifacts = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    artifacts["model"] = joblib.load(f"{MODEL_DIR}/delay_model_v2.joblib")
    artifacts["airline_encoder"] = joblib.load(f"{MODEL_DIR}/airline_encoder_v2.joblib")
    artifacts["airport_encoder"] = joblib.load(f"{MODEL_DIR}/airport_encoder_v2.joblib")

    with open(f"{MODEL_DIR}/feature_metadata_v2.json") as f:
        artifacts["feature_metadata"] = json.load(f)

    # The model was trained on IATA airline codes (AIRLINE column), but the
    # API accepts full airline names for a friendlier UX — build the
    # name<->code lookup from the same airlines.csv used throughout the
    # pipeline, restricted to codes the encoder actually knows.
    airlines_df = pd.read_csv(f"{RAW_DIR}/airlines.csv")
    known_codes = set(artifacts["airline_encoder"].classes_)
    airlines_df = airlines_df[airlines_df["IATA_CODE"].isin(known_codes)]
    artifacts["airline_name_to_code"] = dict(
        zip(airlines_df["AIRLINE"], airlines_df["IATA_CODE"])
    )
    artifacts["known_airline_names"] = sorted(artifacts["airline_name_to_code"].keys())
    artifacts["known_airport_codes"] = set(artifacts["airport_encoder"].classes_)

    print(
        f"Loaded model, encoders, and metadata "
        f"({len(known_codes)} airlines, {len(artifacts['known_airport_codes'])} "
        f"airport codes known to the model)"
    )
    yield
    artifacts.clear()


app = FastAPI(title="Airline Delay Analytics API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PredictRequest(BaseModel):
    airline: str
    origin_airport: str
    month: int = Field(ge=1, le=12)
    day_of_week: int = Field(ge=1, le=7)
    scheduled_hour: int = Field(ge=0, le=23)
    distance: int = Field(gt=0)


class PredictResponse(BaseModel):
    prediction: str
    probability: float
    confidence_note: str


@app.get("/")
def health_check():
    return {"status": "ok"}


@app.get("/metadata")
def get_metadata():
    return {
        "airlines": artifacts["known_airline_names"],
        "airports": artifacts["feature_metadata"]["airports"],
    }


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest):
    airline_name = request.airline.strip()
    airline_code = artifacts["airline_name_to_code"].get(airline_name)
    if airline_code is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown airline '{airline_name}'. Valid airlines: "
                f"{', '.join(artifacts['known_airline_names'])}"
            ),
        )

    origin_airport = request.origin_airport.strip().upper()
    if origin_airport not in artifacts["known_airport_codes"]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown origin_airport '{origin_airport}'. It is not one of "
                f"the airport codes the model was trained on. See /metadata "
                f"for a list of recognized codes."
            ),
        )

    airline_encoded = artifacts["airline_encoder"].transform([airline_code])[0]
    airport_encoded = artifacts["airport_encoder"].transform([origin_airport])[0]

    # Column order must match FEATURE_COLS from src/export_model_v2.py.
    feature_row = pd.DataFrame(
        [
            {
                "AIRLINE_ENCODED": airline_encoded,
                "ORIGIN_AIRPORT_ENCODED": airport_encoded,
                "MONTH": request.month,
                "DAY_OF_WEEK": request.day_of_week,
                "SCHEDULED_DEPARTURE_HOUR": request.scheduled_hour,
                "DISTANCE": request.distance,
            }
        ],
        columns=artifacts["feature_metadata"]["feature_order"],
    )

    probability = float(artifacts["model"].predict_proba(feature_row)[0][1])
    prediction = "delayed" if probability >= DELAY_THRESHOLD else "on-time"

    confidence_note = (
        f"Model catches ~{MODEL_RECALL * 100:.0f}% of real delays (recall) but "
        f"only ~{MODEL_PRECISION * 100:.0f}% of 'delayed' predictions turn out "
        f"correct (precision) — treat this as a screening signal, not a "
        f"certainty."
    )

    return PredictResponse(
        prediction=prediction,
        probability=round(probability, 4),
        confidence_note=confidence_note,
    )


@app.get("/stats/{category}")
def get_stats(category: str):
    if category not in STATS_CATEGORY_MAP:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown category '{category}'. Valid categories: "
                f"{', '.join(STATS_CATEGORY_MAP.keys())}"
            ),
        )

    file_stem, name_col = STATS_CATEGORY_MAP[category]
    matches = glob.glob(f"{PROCESSED_DIR}/{file_stem}.csv/part-*.csv")
    if not matches:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No data found for category '{category}' — has "
                f"src/aggregate.py been run?"
            ),
        )

    df = pd.read_csv(matches[0])
    df = df.rename(columns={name_col: "name"})
    df = df[["name", "total_flights", "total_delayed", "delay_pct"]]
    return df.to_dict(orient="records")
