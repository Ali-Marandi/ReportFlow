"""Render a compact chart from Locust CSV artifacts created by the quota load harness."""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).parents[2]
RUNS = [
    ("100 users\n(10 RPS/user)", ROOT / ".task_artifacts/locust/quota_1000rps_stats.csv"),
    ("1000 users\n(1 RPS/user)", ROOT / ".task_artifacts/locust/quota_full_1000rps_stats.csv"),
]


def row_for(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return next(row for row in rows if row["Type"] == "POST")


def main() -> None:
    labels, rps, p50, p95 = [], [], [], []
    for label, path in RUNS:
        row = row_for(path)
        labels.append(label)
        rps.append(float(row["Requests/s"]))
        p50.append(float(row["50%"] or row["Median Response Time"]))
        p95.append(float(row["95%"] or row["95%"] or 0))

    figure, axes = plt.subplots(1, 2, figsize=(11, 4.6), dpi=160)
    colors = ["#1b998b", "#e76f51"]
    axes[0].bar(labels, rps, color=colors)
    axes[0].axhline(1000, color="#264653", linestyle="--", linewidth=1.5, label="Target: 1000 RPS")
    axes[0].set_title("Observed throughput")
    axes[0].set_ylabel("Requests per second")
    axes[0].legend(frameon=False)
    for index, value in enumerate(rps):
        axes[0].text(index, value + 18, f"{value:.1f}", ha="center", va="bottom", fontweight="bold")

    positions = list(range(len(labels)))
    axes[1].bar([x - 0.18 for x in positions], p50, width=0.36, label="p50", color="#457b9d")
    axes[1].bar([x + 0.18 for x in positions], p95, width=0.36, label="p95", color="#f4a261")
    axes[1].set_xticks(positions, labels)
    axes[1].set_title("Response latency")
    axes[1].set_ylabel("Milliseconds")
    axes[1].legend(frameon=False)
    for axis in axes:
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(axis="y", alpha=0.2)

    figure.suptitle("ReportFlow quota-load harness — isolated local benchmark", fontweight="bold", y=1.02)
    figure.tight_layout()
    output = ROOT / "docs/assets/v27_locust_quota_benchmark.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, bbox_inches="tight")
    print(output)


if __name__ == "__main__":
    main()
