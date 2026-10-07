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
METRICS_DIR = "outputs/metrics"

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


@app.get("/stats/model-comparison")
def get_model_comparison():
    """3-way Logistic Regression vs Decision Tree vs Random Forest comparison
    from src/model_v2.py, each at its own best-F1 threshold (delayed class)."""
    path = f"{METRICS_DIR}/model_comparison_3way.json"
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=(
                "No model comparison data found — has src/model_v2.py been "
                "run since the 3-way comparison was added?"
            ),
        )


@app.get("/stats/airport-map")
def get_airport_map():
    """Airport delay rates joined with lat/lon from airports.csv, for the
    dashboard's geographic map. agg_by_airport_v2.csv (aggregate_v2.py) is
    already restricted to airports with > 10,000 flights, which is stricter
    than (and therefore already satisfies) the > 5,000 threshold requested
    here -- so the explicit filter below is a no-op today but keeps the
    contract correct if that upstream threshold ever changes."""
    matches = glob.glob(f"{PROCESSED_DIR}/agg_by_airport_v2.csv/part-*.csv")
    if not matches:
        raise HTTPException(
            status_code=404,
            detail="No airport aggregate data found — has src/aggregate_v2.py been run?",
        )

    airport_stats = pd.read_csv(matches[0])
    airport_stats = airport_stats[airport_stats["total_flights"] > 5000]

    airports_geo = pd.read_csv(f"{RAW_DIR}/airports.csv")[
        ["IATA_CODE", "LATITUDE", "LONGITUDE"]
    ]

    merged = airport_stats.merge(
        airports_geo, left_on="ORIGIN_AIRPORT", right_on="IATA_CODE", how="inner"
    )
    merged = merged.rename(
        columns={"ORIGIN_AIRPORT": "airport", "LATITUDE": "lat", "LONGITUDE": "lon"}
    )
    merged = merged[["airport", "delay_pct", "total_flights", "lat", "lon"]]
    return merged.to_dict(orient="records")


def read_aggregate_csv(name):
    matches = glob.glob(f"{PROCESSED_DIR}/{name}.csv/part-*.csv")
    if not matches:
        raise HTTPException(
            status_code=404,
            detail=f"No {name} data found — has src/aggregate_dashboard_v2.py been run?",
        )
    return pd.read_csv(matches[0])


def dow_hour_records(df):
    df = df.rename(columns={"DAY_OF_WEEK": "day_of_week", "SCHEDULED_DEPARTURE_HOUR": "hour"})
    return df[["day_of_week", "hour", "total_flights", "total_delayed", "delay_pct"]].to_dict(
        orient="records"
    )


@app.get("/stats/dow-hour")
def get_dow_hour():
    """National day-of-week x scheduled-departure-hour delay grid."""
    return dow_hour_records(read_aggregate_csv("agg_by_dow_hour_v2"))


@app.get("/stats/delay-minutes")
def get_delay_minutes():
    """Mean/median ARRIVAL_DELAY summary from src/aggregate_dashboard_v2.py."""
    try:
        with open(f"{METRICS_DIR}/delay_minutes_v2.json") as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="No delay-minutes data found — has src/aggregate_dashboard_v2.py been run?",
        )


@app.get("/stats/airport/{code}")
def get_airport_breakdown(code: str):
    """One busy airport's delay rate by airline, hour, day of week, month and
    the weekday x hour grid -- the same shapes as the national endpoints."""
    code = code.upper()
    breakdown = read_aggregate_csv("agg_airport_breakdown_v2")
    breakdown = breakdown[breakdown["ORIGIN_AIRPORT"] == code]
    if breakdown.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No breakdown for '{code}' — only airports with 10,000+ flights have one.",
        )

    result = {"airport": code}
    for dimension in ["airline", "hour", "dayofweek", "month"]:
        rows = breakdown[breakdown["dimension"] == dimension]
        if dimension != "airline":
            rows = rows.assign(name=rows["name"].astype(int))
        result[dimension] = rows[["name", "total_flights", "total_delayed", "delay_pct"]].to_dict(
            orient="records"
        )

    grid = read_aggregate_csv("agg_airport_dow_hour_v2")
    result["dow_hour"] = dow_hour_records(grid[grid["ORIGIN_AIRPORT"] == code])
    return result


# NOTE: this route must stay registered BEFORE /stats/{category} below --
# otherwise the parameterized route would swallow "/stats/model-comparison"
# requests as category="model-comparison" and 404 them there instead.
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
