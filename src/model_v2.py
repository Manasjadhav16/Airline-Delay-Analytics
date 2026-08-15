"""Train and evaluate delay-classification models on the combined 2015+2016 dataset.

Same feature set, leakage exclusions, and class-imbalance fix (weighting +
threshold tuning) as src/model.py -- only the input data and output filenames
differ (to avoid clobbering the original single-year model_metrics*.json
files, everything here is written to *_2yr.json/csv instead of *_v2.json,
since "_v2" is already used inside model.py's own filenames for a different
meaning -- the weighted-model metrics version, not the dataset version).

Run from project root: python3 src/model_v2.py
"""

import json

from pyspark import StorageLevel
from pyspark.ml.classification import LogisticRegression, RandomForestClassifier
from pyspark.ml.evaluation import (
    BinaryClassificationEvaluator,
    MulticlassClassificationEvaluator,
)
from pyspark.ml.feature import StringIndexer, VectorAssembler
from pyspark.ml.functions import vector_to_array
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

PROCESSED_DIR = "data/processed"
METRICS_DIR = "outputs/metrics"

LABEL_COL = "is_delayed"
FEATURE_COLS = [
    "AIRLINE_INDEXED",
    "ORIGIN_AIRPORT_INDEXED",
    "MONTH",
    "DAY_OF_WEEK",
    "SCHEDULED_DEPARTURE_HOUR",
    "DISTANCE",
]

THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]


def evaluate(predictions, model_name):
    binary_eval = BinaryClassificationEvaluator(
        labelCol=LABEL_COL, rawPredictionCol="rawPrediction", metricName="areaUnderROC"
    )
    auc = binary_eval.evaluate(predictions)

    metrics = {}
    for metric_name in ["accuracy", "f1", "weightedPrecision", "weightedRecall"]:
        evaluator = MulticlassClassificationEvaluator(
            labelCol=LABEL_COL, predictionCol="prediction", metricName=metric_name
        )
        metrics[metric_name] = evaluator.evaluate(predictions)

    confusion = (
        predictions.groupBy(LABEL_COL, "prediction")
        .count()
        .orderBy(LABEL_COL, "prediction")
        .collect()
    )
    confusion_counts = {
        f"actual_{int(row[LABEL_COL])}_predicted_{int(row['prediction'])}": row["count"]
        for row in confusion
    }

    result = {
        "model": model_name,
        "auc": round(auc, 4),
        "accuracy": round(metrics["accuracy"], 4),
        "f1": round(metrics["f1"], 4),
        "precision": round(metrics["weightedPrecision"], 4),
        "recall": round(metrics["weightedRecall"], 4),
        "confusion_matrix": confusion_counts,
    }

    print(f"\n=== {model_name} ===")
    print(f"AUC:       {result['auc']}")
    print(f"Accuracy:  {result['accuracy']}")
    print(f"F1:        {result['f1']}")
    print(f"Precision: {result['precision']}")
    print(f"Recall:    {result['recall']}")
    print(f"Confusion matrix: {confusion_counts}")

    return result, confusion


def sweep_thresholds(predictions, model_name):
    predictions = predictions.withColumn(
        "prob_delayed", vector_to_array("probability")[1]
    )
    predictions.persist(StorageLevel.DISK_ONLY)
    predictions.count()

    print(f"\n{model_name} — threshold sweep (precision/recall/F1 for delayed class):")
    print(f"{'threshold':>10} {'precision':>10} {'recall':>10} {'f1':>10}")

    sweep_results = []
    for t in THRESHOLDS:
        row = predictions.agg(
            F.sum(
                F.when((F.col(LABEL_COL) == 1) & (F.col("prob_delayed") >= t), 1).otherwise(0)
            ).alias("tp"),
            F.sum(
                F.when((F.col(LABEL_COL) == 0) & (F.col("prob_delayed") >= t), 1).otherwise(0)
            ).alias("fp"),
            F.sum(
                F.when((F.col(LABEL_COL) == 1) & (F.col("prob_delayed") < t), 1).otherwise(0)
            ).alias("fn"),
            F.sum(
                F.when((F.col(LABEL_COL) == 0) & (F.col("prob_delayed") < t), 1).otherwise(0)
            ).alias("tn"),
        ).collect()[0]

        tp, fp, fn, tn = row["tp"], row["fp"], row["fn"], row["tn"]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        sweep_results.append(
            {
                "threshold": t,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "tn": tn,
            }
        )
        print(f"{t:>10.2f} {precision:>10.4f} {recall:>10.4f} {f1:>10.4f}")

    predictions.unpersist()

    best = max(sweep_results, key=lambda r: r["f1"])
    print(
        f"Best threshold for {model_name} (max F1 on delayed class): "
        f"{best['threshold']} (precision={best['precision']}, recall={best['recall']}, "
        f"f1={best['f1']})"
    )
    return sweep_results, best


def main():
    spark = (
        SparkSession.builder.appName("AirlineDelayAnalytics-Model-V2")
        .master("local[*]")
        .config("spark.driver.memory", "4g")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")

    df = spark.read.parquet(f"{PROCESSED_DIR}/flights_clean_v2.parquet")
    df = df.select(
        "AIRLINE",
        "ORIGIN_AIRPORT",
        "MONTH",
        "DAY_OF_WEEK",
        "SCHEDULED_DEPARTURE_HOUR",
        "DISTANCE",
        LABEL_COL,
    )
    df.persist(StorageLevel.DISK_ONLY)

    total_rows = df.count()
    print(f"Total rows for modeling (2015+2016 combined): {total_rows}")

    airline_indexer = StringIndexer(
        inputCol="AIRLINE", outputCol="AIRLINE_INDEXED", handleInvalid="keep"
    )
    airport_indexer = StringIndexer(
        inputCol="ORIGIN_AIRPORT", outputCol="ORIGIN_AIRPORT_INDEXED", handleInvalid="keep"
    )
    df = airline_indexer.fit(df).transform(df)
    df = airport_indexer.fit(df).transform(df)

    assembler = VectorAssembler(inputCols=FEATURE_COLS, outputCol="features")
    df = assembler.transform(df)

    train_df, test_df = df.randomSplit([0.8, 0.2], seed=42)
    train_df.persist(StorageLevel.DISK_ONLY)
    test_df.persist(StorageLevel.DISK_ONLY)
    train_count = train_df.count()
    test_count = test_df.count()
    print(f"Train rows: {train_count}, Test rows: {test_count}")

    test_on_time = test_df.filter(f"{LABEL_COL} == 0").count()
    majority_baseline_accuracy = round(test_on_time / test_count, 4)
    print(
        f"\n'Always predict on-time' baseline accuracy on test set: "
        f"{majority_baseline_accuracy} ({majority_baseline_accuracy * 100:.2f}%)"
    )

    all_metrics = {"majority_class_baseline_accuracy": majority_baseline_accuracy}

    # (a) Unweighted Logistic Regression baseline
    lr = LogisticRegression(featuresCol="features", labelCol=LABEL_COL)
    lr_model = lr.fit(train_df)
    lr_predictions = lr_model.transform(test_df)
    lr_result, _ = evaluate(lr_predictions, "LogisticRegression (unweighted)")
    all_metrics["unweighted_logistic_regression"] = lr_result

    # (b) Unweighted Random Forest baseline
    # maxBins must be >= the cardinality of the largest categorical feature.
    rf = RandomForestClassifier(
        featuresCol="features",
        labelCol=LABEL_COL,
        numTrees=50,
        maxDepth=8,
        maxBins=700,
        seed=42,
    )
    rf_model = rf.fit(train_df)
    rf_predictions = rf_model.transform(test_df)
    rf_result, rf_confusion = evaluate(rf_predictions, "RandomForest (unweighted)")
    all_metrics["unweighted_random_forest"] = rf_result

    importances = list(zip(FEATURE_COLS, rf_model.featureImportances.toArray()))
    importances.sort(key=lambda x: x[1], reverse=True)
    print("\nUnweighted Random Forest feature importances (sorted descending):")
    for feature, importance in importances:
        print(f"  {feature}: {round(float(importance), 4)}")
    all_metrics["unweighted_random_forest_feature_importances"] = {
        feature: round(float(importance), 4) for feature, importance in importances
    }

    # Confusion matrix CSV for the unweighted RF baseline
    confusion_csv_path = f"{METRICS_DIR}/confusion_matrix_random_forest_2yr.csv"
    with open(confusion_csv_path, "w") as f:
        f.write("actual,predicted,count\n")
        for row in rf_confusion:
            f.write(f"{int(row[LABEL_COL])},{int(row['prediction'])},{row['count']}\n")

    # ------------------------------------------------------------------
    # Class weighting + threshold tuning (same fix as the original pipeline)
    # ------------------------------------------------------------------
    print("\n\n=== Addressing class imbalance: class weighting + threshold tuning ===")

    label_counts = {int(r[LABEL_COL]): r["count"] for r in train_df.groupBy(LABEL_COL).count().collect()}
    total_train = sum(label_counts.values())
    class_weights = {
        label: total_train / (2 * count) for label, count in label_counts.items()
    }
    print(f"Train label counts: {label_counts}")
    print(f"Class weights (total / (2 * class_count)): {class_weights}")

    train_weighted = train_df.withColumn(
        "classWeight",
        F.when(F.col(LABEL_COL) == 1, class_weights[1]).otherwise(class_weights[0]),
    )
    train_weighted.persist(StorageLevel.DISK_ONLY)
    train_weighted.count()

    lr_weighted = LogisticRegression(
        featuresCol="features", labelCol=LABEL_COL, weightCol="classWeight"
    )
    lr_weighted_model = lr_weighted.fit(train_weighted)
    lr_weighted_predictions = lr_weighted_model.transform(test_df)
    lr_weighted_auc = BinaryClassificationEvaluator(
        labelCol=LABEL_COL, rawPredictionCol="rawPrediction", metricName="areaUnderROC"
    ).evaluate(lr_weighted_predictions)
    print(f"\nWeighted LogisticRegression AUC: {round(lr_weighted_auc, 4)}")
    lr_sweep, lr_best = sweep_thresholds(lr_weighted_predictions, "Weighted LogisticRegression")

    rf_weighted = RandomForestClassifier(
        featuresCol="features",
        labelCol=LABEL_COL,
        numTrees=50,
        maxDepth=8,
        maxBins=700,
        seed=42,
        weightCol="classWeight",
    )
    rf_weighted_model = rf_weighted.fit(train_weighted)
    rf_weighted_predictions = rf_weighted_model.transform(test_df)
    rf_weighted_auc = BinaryClassificationEvaluator(
        labelCol=LABEL_COL, rawPredictionCol="rawPrediction", metricName="areaUnderROC"
    ).evaluate(rf_weighted_predictions)
    print(f"\nWeighted RandomForest AUC: {round(rf_weighted_auc, 4)}")
    rf_sweep, rf_best = sweep_thresholds(rf_weighted_predictions, "Weighted RandomForest")

    rf_best_t = rf_best["threshold"]
    rf_tuned = rf_weighted_predictions.withColumn(
        "prob_delayed", vector_to_array("probability")[1]
    ).withColumn(
        "tuned_prediction", F.when(F.col("prob_delayed") >= rf_best_t, 1).otherwise(0)
    )
    rf_tuned_confusion = (
        rf_tuned.groupBy(LABEL_COL, "tuned_prediction")
        .count()
        .orderBy(LABEL_COL, "tuned_prediction")
        .collect()
    )
    rf_tuned_confusion_counts = {
        f"actual_{int(row[LABEL_COL])}_predicted_{int(row['tuned_prediction'])}": row["count"]
        for row in rf_tuned_confusion
    }

    print("\n=== Before vs After comparison (2015+2016 combined) ===")
    print(
        f"BEFORE (unweighted RandomForest, 0.5 threshold): "
        f"accuracy={rf_result['accuracy']}, precision={rf_result['precision']}, "
        f"recall={rf_result['recall']}, f1={rf_result['f1']}, "
        f"confusion={rf_result['confusion_matrix']}"
    )
    print(
        f"\nAFTER (weighted RandomForest, tuned threshold={rf_best_t}): "
        f"precision(delayed)={rf_best['precision']}, recall(delayed)={rf_best['recall']}, "
        f"f1(delayed)={rf_best['f1']}, confusion={rf_tuned_confusion_counts}"
    )

    all_metrics["class_weights"] = {str(k): v for k, v in class_weights.items()}
    all_metrics["weighted_logistic_regression"] = {
        "auc": round(lr_weighted_auc, 4),
        "threshold_sweep": lr_sweep,
        "best_threshold": lr_best,
    }
    all_metrics["weighted_random_forest"] = {
        "auc": round(rf_weighted_auc, 4),
        "threshold_sweep": rf_sweep,
        "best_threshold": rf_best,
        "confusion_matrix_at_best_threshold": rf_tuned_confusion_counts,
    }

    with open(f"{METRICS_DIR}/model_metrics_2yr.json", "w") as f:
        json.dump(all_metrics, f, indent=2)

    print(f"\nMetrics saved to {METRICS_DIR}/model_metrics_2yr.json")
    print(f"Confusion matrix saved to {confusion_csv_path}")

    df.unpersist()
    train_df.unpersist()
    test_df.unpersist()
    train_weighted.unpersist()
    spark.stop()


if __name__ == "__main__":
    main()
