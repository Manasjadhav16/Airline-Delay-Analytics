"""Does PREV_FLIGHT_DELAYED improve delay prediction?

Trains, on one shared 80/20 split of flights_engineered.parquet (2015 only):
  * baseline: class-weighted Random Forest on the original 6 features
  * Logistic Regression, Decision Tree, Random Forest and Gradient Boosted
    Trees on the 6 features + PREV_FLIGHT_DELAYED
Same inverse-frequency class weighting and threshold sweep as model_v2.py,
except that a sweep whose best F1 lands on the upper boundary (0.60) is
extended to 0.85 so the reported optimum isn't capped by the search range.

The published 2015+2016 RF AUC (model_comparison_3way.json) is reported for
reference only -- different data, so the in-script 6-feature baseline is the
fair comparison.

Run from project root: python3 src/model_v3.py
"""

import json

from pyspark import StorageLevel
from pyspark.ml.classification import (
    DecisionTreeClassifier,
    GBTClassifier,
    LogisticRegression,
    RandomForestClassifier,
)
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.ml.feature import StringIndexer, VectorAssembler
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from model_v2 import LABEL_COL, THRESHOLDS, sweep_thresholds

PROCESSED_DIR = "data/processed"
METRICS_DIR = "outputs/metrics"
COMPARISON_PATH = f"{METRICS_DIR}/model_comparison_v3.json"

BASE_FEATURES = [
    "AIRLINE_INDEXED",
    "ORIGIN_AIRPORT_INDEXED",
    "MONTH",
    "DAY_OF_WEEK",
    "SCHEDULED_DEPARTURE_HOUR",
    "DISTANCE",
]
NEW_FEATURES = BASE_FEATURES + ["PREV_FLIGHT_DELAYED"]

EXTENDED_THRESHOLDS = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85]

BASELINE_NAME = "Random Forest (6 features, baseline)"


def get_spark():
    spark = (
        SparkSession.builder.appName("AirlineDelayAnalytics-Model-V3")
        .master("local[*]")
        .config("spark.driver.memory", "4g")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def prepare_splits(spark):
    """Index, assemble, split (seed 42) and class-weight. Deterministic, so
    every caller gets the same train/test rows."""
    df = spark.read.parquet(f"{PROCESSED_DIR}/flights_engineered.parquet").select(
        "AIRLINE",
        "ORIGIN_AIRPORT",
        "MONTH",
        "DAY_OF_WEEK",
        "SCHEDULED_DEPARTURE_HOUR",
        "DISTANCE",
        "PREV_FLIGHT_DELAYED",
        LABEL_COL,
    )
    print(f"Total rows for modeling (2015, flights_engineered.parquet): {df.count()}")

    df = StringIndexer(
        inputCol="AIRLINE", outputCol="AIRLINE_INDEXED", handleInvalid="keep"
    ).fit(df).transform(df)
    df = StringIndexer(
        inputCol="ORIGIN_AIRPORT", outputCol="ORIGIN_AIRPORT_INDEXED", handleInvalid="keep"
    ).fit(df).transform(df)
    df = VectorAssembler(inputCols=BASE_FEATURES, outputCol="features_6").transform(df)
    df = VectorAssembler(inputCols=NEW_FEATURES, outputCol="features_7").transform(df)

    # One split shared by every model, so the baseline and the 7-feature
    # models are scored on exactly the same test rows.
    train_df, test_df = df.randomSplit([0.8, 0.2], seed=42)

    label_counts = {
        int(r[LABEL_COL]): r["count"] for r in train_df.groupBy(LABEL_COL).count().collect()
    }
    total_train = sum(label_counts.values())
    class_weights = {label: total_train / (2 * count) for label, count in label_counts.items()}
    print(f"Train label counts: {label_counts}")
    print(f"Class weights (total / (2 * class_count)): {class_weights}")

    train_df = train_df.withColumn(
        "classWeight",
        F.when(F.col(LABEL_COL) == 1, class_weights[1]).otherwise(class_weights[0]),
    )
    train_df.persist(StorageLevel.DISK_ONLY)
    test_df.persist(StorageLevel.DISK_ONLY)
    train_count = train_df.count()
    test_count = test_df.count()
    print(f"Train rows: {train_count}, Test rows: {test_count}")
    return train_df, test_df, class_weights, train_count, test_count


def build_models():
    """(name, estimator, feature_cols) for the baseline and the 4 candidates."""
    # Tree hyperparameters match model_v2.py (maxBins >= airport cardinality).
    tree_params = dict(labelCol=LABEL_COL, weightCol="classWeight", maxDepth=8, maxBins=700, seed=42)
    return [
        (BASELINE_NAME,
         RandomForestClassifier(featuresCol="features_6", numTrees=50, **tree_params),
         BASE_FEATURES),
        ("Logistic Regression (7 features)",
         LogisticRegression(featuresCol="features_7", labelCol=LABEL_COL, weightCol="classWeight"),
         NEW_FEATURES),
        ("Decision Tree (7 features)",
         DecisionTreeClassifier(featuresCol="features_7", **tree_params),
         NEW_FEATURES),
        ("Random Forest (7 features)",
         RandomForestClassifier(featuresCol="features_7", numTrees=50, **tree_params),
         NEW_FEATURES),
        # GBT: shallower trees than RF, as is usual for boosting; 50 rounds.
        ("Gradient Boosted Trees (7 features)",
         GBTClassifier(featuresCol="features_7", labelCol=LABEL_COL, weightCol="classWeight",
                       maxIter=50, maxDepth=6, maxBins=700, stepSize=0.1, seed=42),
         NEW_FEATURES),
    ]


def full_sweep(predictions, name):
    """Standard sweep; if the best F1 sits on the 0.60 boundary, extend to
    0.60-0.85 and pick the best over the combined range."""
    sweep, best = sweep_thresholds(predictions, name)
    extended = False
    if best["threshold"] == max(THRESHOLDS):
        print(f"{name}: best threshold is at the sweep boundary -- extending to 0.60-0.85")
        extra, _ = sweep_thresholds(predictions, name, thresholds=EXTENDED_THRESHOLDS[1:])
        sweep = sweep + extra
        best = max(sweep, key=lambda r: r["f1"])
        extended = True
        print(
            f"{name}: best threshold over 0.30-0.85 = {best['threshold']} "
            f"(precision={best['precision']}, recall={best['recall']}, f1={best['f1']})"
        )
    return sweep, best, extended


def fit_and_evaluate(estimator, train_df, test_df, name, feature_cols):
    model = estimator.fit(train_df)
    predictions = model.transform(test_df)
    auc = BinaryClassificationEvaluator(
        labelCol=LABEL_COL, rawPredictionCol="rawPrediction", metricName="areaUnderROC"
    ).evaluate(predictions)
    print(f"\n{name} AUC: {round(auc, 4)}")
    sweep, best, extended = full_sweep(predictions, name)

    result = {
        "model": name,
        "features": feature_cols,
        "auc": round(auc, 4),
        "best_threshold": best["threshold"],
        "precision": best["precision"],
        "recall": best["recall"],
        "f1": best["f1"],
        "sweep_extended_to_0.85": extended,
        "threshold_sweep": sweep,
    }

    if hasattr(model, "featureImportances"):
        importances = sorted(
            zip(feature_cols, model.featureImportances.toArray()),
            key=lambda x: x[1],
            reverse=True,
        )
        print(f"{name} feature importances (ranked):")
        for rank, (feature, importance) in enumerate(importances, start=1):
            print(f"  {rank}. {feature}: {round(float(importance), 4)}")
        result["feature_importances"] = {f: round(float(i), 4) for f, i in importances}
    elif hasattr(model, "coefficients"):
        # Spark LR standardizes internally but returns raw-scale
        # coefficients; listed for completeness, not as an importance.
        result["coefficients"] = dict(
            zip(feature_cols, [round(float(c), 4) for c in model.coefficients])
        )
        print(f"{name} coefficients (raw scale): {result['coefficients']}")
    return result


def print_comparison(baseline, new_results):
    print("\n\n=== Comparison (2015 test set, class-weighted, best-F1 threshold each) ===")
    header = f"{'Model':<40} {'AUC':>7} {'dAUC':>8} {'Thr':>5} {'Prec':>7} {'Recall':>7} {'F1':>7} {'dF1':>8}"
    print(header)
    print("-" * len(header))
    for r in [baseline] + new_results:
        d_auc = r["auc"] - baseline["auc"]
        d_f1 = r["f1"] - baseline["f1"]
        print(
            f"{r['model']:<40} {r['auc']:>7.4f} {d_auc:>+8.4f} {r['best_threshold']:>5.2f} "
            f"{r['precision']:>7.4f} {r['recall']:>7.4f} {r['f1']:>7.4f} {d_f1:>+8.4f}"
        )


def write_comparison(baseline, new_results, class_weights, train_count, test_count):
    with open(f"{METRICS_DIR}/model_comparison_3way.json") as f:
        prior_2yr = json.load(f)
    prior_rf_auc = next(r["auc"] for r in prior_2yr["comparison"] if r["model"] == "Random Forest")
    print(
        f"\nReference only (different dataset, 2015+2016): published 6-feature RF AUC = {prior_rf_auc}"
    )

    rf7 = next(r for r in new_results if r["model"].startswith("Random Forest"))
    ranking = list(rf7["feature_importances"])
    prev_rank = ranking.index("PREV_FLIGHT_DELAYED") + 1
    print(
        f"PREV_FLIGHT_DELAYED importance rank in 7-feature RF: {prev_rank} of {len(ranking)} "
        f"({rf7['feature_importances']['PREV_FLIGHT_DELAYED']})"
    )

    comparison = {
        "dataset": "2015 only (flights_engineered.parquet) -- 2015+2016 data has no TAIL_NUMBER",
        "train_rows": train_count,
        "test_rows": test_count,
        "class_weighting": "inverse-frequency (total / (2 * class_count))",
        "class_weights": {str(k): v for k, v in class_weights.items()},
        "threshold_sweep": "0.30-0.60 step 0.05; extended to 0.85 when best F1 hit 0.60",
        "baseline_6_features": baseline,
        "models_7_features": new_results,
        "delta_vs_baseline": {
            r["model"]: {
                "auc": round(r["auc"] - baseline["auc"], 4),
                "f1": round(r["f1"] - baseline["f1"], 4),
            }
            for r in new_results
        },
        "prev_flight_delayed_rank_in_rf": prev_rank,
        "reference_2015_2016_rf_auc_not_comparable": prior_rf_auc,
    }
    with open(COMPARISON_PATH, "w") as f:
        json.dump(comparison, f, indent=2)
    print(f"\nSaved to {COMPARISON_PATH}")


def main():
    spark = get_spark()
    train_df, test_df, class_weights, train_count, test_count = prepare_splits(spark)

    results = [
        fit_and_evaluate(estimator, train_df, test_df, name, feature_cols)
        for name, estimator, feature_cols in build_models()
    ]
    baseline, new_results = results[0], results[1:]

    print_comparison(baseline, new_results)
    write_comparison(baseline, new_results, class_weights, train_count, test_count)

    train_df.unpersist()
    test_df.unpersist()
    spark.stop()


if __name__ == "__main__":
    main()
