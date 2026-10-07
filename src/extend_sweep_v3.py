"""Extend the threshold sweep for models whose best F1 hit the 0.60 cap.

The first model_v3.py run swept 0.30-0.60 only. For every model in
model_comparison_v3.json whose best threshold is 0.60, this retrains just
that model on the identical split (same seed, same data), checks it
reproduces the recorded AUC, sweeps 0.65-0.85, and updates the JSON with
the best threshold over the full 0.30-0.85 range. Models whose optimum was
inside the original range are left untouched.

(model_v3.py now does this extension itself; this script avoids retraining
the uncapped models, GBT especially, just to fix the capped ones.)

Run from project root: python3 src/extend_sweep_v3.py
"""

import json

from pyspark.ml.evaluation import BinaryClassificationEvaluator

from model_v2 import LABEL_COL, THRESHOLDS, sweep_thresholds
from model_v3 import (
    COMPARISON_PATH,
    EXTENDED_THRESHOLDS,
    build_models,
    get_spark,
    prepare_splits,
    print_comparison,
    write_comparison,
)


def main():
    with open(COMPARISON_PATH) as f:
        comparison = json.load(f)
    baseline = comparison["baseline_6_features"]
    new_results = comparison["models_7_features"]

    capped = [
        r for r in [baseline] + new_results
        if r["best_threshold"] == max(THRESHOLDS) and not r.get("sweep_extended_to_0.85")
    ]
    print("Best threshold per model in the original 0.30-0.60 sweep:")
    for r in [baseline] + new_results:
        flag = "  <-- at upper boundary, extending" if r in capped else ""
        print(f"  {r['model']:<40} {r['best_threshold']:.2f}{flag}")
    if not capped:
        print("No capped models; nothing to do.")
        return

    spark = get_spark()
    train_df, test_df, _, _, _ = prepare_splits(spark)
    estimators = {name: estimator for name, estimator, _ in build_models()}

    for r in capped:
        name = r["model"]
        predictions = estimators[name].fit(train_df).transform(test_df)
        auc = round(
            BinaryClassificationEvaluator(
                labelCol=LABEL_COL, rawPredictionCol="rawPrediction", metricName="areaUnderROC"
            ).evaluate(predictions),
            4,
        )
        print(f"\n{name}: retrained AUC {auc} vs recorded {r['auc']} "
              f"({'reproduced' if abs(auc - r['auc']) <= 1e-4 else 'MISMATCH'})")
        if abs(auc - r["auc"]) > 1e-4:
            raise RuntimeError(f"{name} did not reproduce; refusing to merge sweeps from different models")

        extra, _ = sweep_thresholds(predictions, name, thresholds=EXTENDED_THRESHOLDS[1:])
        r["threshold_sweep"] = r["threshold_sweep"] + extra
        best = max(r["threshold_sweep"], key=lambda s: s["f1"])
        print(
            f"{name}: best threshold over 0.30-0.85 = {best['threshold']} "
            f"(was 0.60; f1 {r['f1']} -> {best['f1']})"
        )
        r.update(
            best_threshold=best["threshold"],
            precision=best["precision"],
            recall=best["recall"],
            f1=best["f1"],
        )
        r["sweep_extended_to_0.85"] = True

    print_comparison(baseline, new_results)
    write_comparison(
        baseline,
        new_results,
        {int(k): v for k, v in comparison["class_weights"].items()},
        comparison["train_rows"],
        comparison["test_rows"],
    )

    train_df.unpersist()
    test_df.unpersist()
    spark.stop()


if __name__ == "__main__":
    main()
