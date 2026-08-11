"""Generate EDA charts (PNG) from aggregate.py's CSV outputs.

Run from project root: python3 src/eda.py
"""

import glob
import json
import os

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

PROCESSED_DIR = "data/processed"
METRICS_DIR = "outputs/metrics"
CHARTS_DIR = "outputs/charts"

DPI = 150

MONTH_LABELS = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}
DOW_LABELS = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


def read_agg_csv(name):
    # Spark writes each CSV as a directory containing one part file.
    path = glob.glob(f"{PROCESSED_DIR}/{name}.csv/part-*.csv")[0]
    return pd.read_csv(path)


def main():
    sns.set_style("whitegrid")
    os.makedirs(CHARTS_DIR, exist_ok=True)

    findings = []

    # 1. Top 10 worst airlines by delay_pct
    by_airline = read_agg_csv("agg_by_airline").sort_values(
        "delay_pct", ascending=False
    ).head(10)
    fig, ax = plt.subplots(figsize=(9, 6))
    sns.barplot(
        data=by_airline.sort_values("delay_pct"),
        x="delay_pct",
        y="AIRLINE_NAME",
        color="#4C72B0",
        ax=ax,
    )
    ax.set_title("Top 10 Worst Airlines by Delay Rate")
    ax.set_xlabel("Delay Rate (%)")
    ax.set_ylabel("Airline")
    fig.tight_layout()
    fig.savefig(f"{CHARTS_DIR}/01_delay_by_airline.png", dpi=DPI)
    plt.close(fig)

    worst = by_airline.iloc[0]
    best_of_worst = by_airline.iloc[-1]
    findings.append(
        f"Chart 1 (delay by airline): {worst['AIRLINE_NAME']} has the worst delay "
        f"rate at {worst['delay_pct']}%, roughly "
        f"{worst['delay_pct'] / best_of_worst['delay_pct']:.1f}x the rate of "
        f"{best_of_worst['AIRLINE_NAME']} ({best_of_worst['delay_pct']}%), the "
        f"best-performing airline within this worst-10 list."
    )

    # 2. Delay pct for top 10 busiest airports (already sorted by total_flights)
    by_airport = read_agg_csv("agg_by_airport").sort_values(
        "total_flights", ascending=False
    ).head(10)
    fig, ax = plt.subplots(figsize=(9, 6))
    sns.barplot(
        data=by_airport.sort_values("total_flights"),
        x="delay_pct",
        y="ORIGIN_AIRPORT",
        color="#DD8452",
        ax=ax,
    )
    ax.set_title("Delay Rate at the 10 Busiest Origin Airports")
    ax.set_xlabel("Delay Rate (%)")
    ax.set_ylabel("Airport (IATA code)")
    fig.tight_layout()
    fig.savefig(f"{CHARTS_DIR}/02_delay_by_airport.png", dpi=DPI)
    plt.close(fig)

    worst_airport = by_airport.loc[by_airport["delay_pct"].idxmax()]
    best_airport = by_airport.loc[by_airport["delay_pct"].idxmin()]
    findings.append(
        f"Chart 2 (delay by airport): among the 10 busiest airports, "
        f"{worst_airport['ORIGIN_AIRPORT']} has the highest delay rate "
        f"({worst_airport['delay_pct']}%) while {best_airport['ORIGIN_AIRPORT']} "
        f"has the lowest ({best_airport['delay_pct']}%) despite similar traffic "
        f"volumes — busiest does not mean most delayed."
    )

    # 3. Delay cause breakdown pie chart
    with open(f"{METRICS_DIR}/delay_cause_totals.json") as f:
        cause_totals = json.load(f)
    labels = list(cause_totals.keys())
    values = list(cause_totals.values())
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.pie(
        values,
        labels=labels,
        autopct="%1.1f%%",
        startangle=90,
        colors=sns.color_palette("Set2", len(values)),
    )
    ax.set_title("Total Delay Minutes by Cause")
    fig.tight_layout()
    fig.savefig(f"{CHARTS_DIR}/03_delay_cause_breakdown.png", dpi=DPI)
    plt.close(fig)

    total_minutes = sum(values)
    top_cause = max(cause_totals, key=cause_totals.get)
    top_cause_pct = 100.0 * cause_totals[top_cause] / total_minutes
    findings.append(
        f"Chart 3 (delay cause breakdown): {top_cause.replace('_', ' ').title()} "
        f"is the single largest contributor to total delay minutes, accounting "
        f"for {top_cause_pct:.1f}% of all delay time across the dataset."
    )

    # 4. Delay pct across scheduled departure hour
    by_hour = read_agg_csv("agg_by_hour").sort_values("SCHEDULED_DEPARTURE_HOUR")
    fig, ax = plt.subplots(figsize=(10, 6))
    sns.lineplot(
        data=by_hour, x="SCHEDULED_DEPARTURE_HOUR", y="delay_pct", marker="o", ax=ax
    )
    ax.set_title("Delay Rate by Scheduled Departure Hour")
    ax.set_xlabel("Scheduled Departure Hour (0-23)")
    ax.set_ylabel("Delay Rate (%)")
    ax.set_xticks(range(0, 24))
    fig.tight_layout()
    fig.savefig(f"{CHARTS_DIR}/04_delay_by_hour.png", dpi=DPI)
    plt.close(fig)

    morning = by_hour[by_hour["SCHEDULED_DEPARTURE_HOUR"].between(5, 8)]["delay_pct"].mean()
    evening = by_hour[by_hour["SCHEDULED_DEPARTURE_HOUR"].between(18, 21)]["delay_pct"].mean()
    findings.append(
        f"Chart 4 (delay by hour): delay rate climbs steadily through the day — "
        f"early-morning flights (5-8am) average {morning:.1f}% delayed versus "
        f"{evening:.1f}% for evening flights (6-9pm), roughly "
        f"{evening / morning:.1f}x higher, consistent with delays cascading "
        f"through the day as aircraft fall behind schedule."
    )

    # 5. Delay pct by day of week
    by_dow = read_agg_csv("agg_by_day_of_week").sort_values("DAY_OF_WEEK")
    by_dow["DOW_LABEL"] = by_dow["DAY_OF_WEEK"].map(DOW_LABELS)
    fig, ax = plt.subplots(figsize=(9, 6))
    sns.barplot(data=by_dow, x="DOW_LABEL", y="delay_pct", color="#55A868", ax=ax)
    ax.set_title("Delay Rate by Day of Week")
    ax.set_xlabel("Day of Week")
    ax.set_ylabel("Delay Rate (%)")
    fig.tight_layout()
    fig.savefig(f"{CHARTS_DIR}/05_delay_by_dayofweek.png", dpi=DPI)
    plt.close(fig)

    worst_dow = by_dow.loc[by_dow["delay_pct"].idxmax()]
    best_dow = by_dow.loc[by_dow["delay_pct"].idxmin()]
    findings.append(
        f"Chart 5 (delay by day of week): {worst_dow['DOW_LABEL']} is the worst "
        f"day to fly ({worst_dow['delay_pct']}% delayed), while "
        f"{best_dow['DOW_LABEL']} is the best ({best_dow['delay_pct']}%) — "
        f"weekday travel is somewhat more delay-prone than Saturday in "
        f"particular."
    )

    # 6. Delay pct by month
    by_month = read_agg_csv("agg_by_month").sort_values("MONTH")
    by_month["MONTH_LABEL"] = by_month["MONTH"].map(MONTH_LABELS)
    fig, ax = plt.subplots(figsize=(10, 6))
    sns.lineplot(data=by_month, x="MONTH", y="delay_pct", marker="o", ax=ax)
    ax.set_title("Delay Rate by Month")
    ax.set_xlabel("Month")
    ax.set_ylabel("Delay Rate (%)")
    ax.set_xticks(by_month["MONTH"])
    ax.set_xticklabels(by_month["MONTH_LABEL"])
    fig.tight_layout()
    fig.savefig(f"{CHARTS_DIR}/06_delay_by_month.png", dpi=DPI)
    plt.close(fig)

    worst_month = by_month.loc[by_month["delay_pct"].idxmax()]
    best_month = by_month.loc[by_month["delay_pct"].idxmin()]
    findings.append(
        f"Chart 6 (delay by month): {worst_month['MONTH_LABEL']} has the highest "
        f"delay rate ({worst_month['delay_pct']}%), while "
        f"{best_month['MONTH_LABEL']} has the lowest ({best_month['delay_pct']}%) "
        f"— summer travel months and winter weather months both spike, "
        f"consistent with the weather- and volume-driven causes in chart 3."
    )

    print("\n=== EDA charts saved to outputs/charts/ ===")
    for i in range(1, 7):
        print(f"  {i}: saved")

    print("\n=== Findings summary (for report) ===")
    for line in findings:
        print(f"- {line}")


if __name__ == "__main__":
    main()
