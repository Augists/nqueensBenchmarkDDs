#!/usr/bin/env python3

"""
Simple visualization helper for the aggregated CSV produced by run_nqueens_benchmarks.py

Usage:
    python scripts/plot_nqueens_results.py --input results/nqueens_metrics.csv --output results
"""

import argparse
import csv
from pathlib import Path

try:
    import matplotlib.pyplot as plt
except ImportError as exc:
    raise SystemExit("matplotlib is required for plotting. Install it via `pip install matplotlib`.") from exc


def read_rows(csv_path):
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        rows = [row for row in reader]
    for row in rows:
        row["size"] = int(row["size"])
        row["time_sec"] = float(row["time_sec"])
        row["max_rss_kb"] = int(row["max_rss_kb"])
        row["nodes"] = int(row["nodes"])
        row["solutions"] = float(row["solutions"])
    return rows


def plot_metric(rows, metric, ylabel, output_dir):
    plt.figure(figsize=(8, 5))
    implementations = sorted(set(r["implementation"] for r in rows))
    for impl in implementations:
        subset = sorted((r for r in rows if r["implementation"] == impl), key=lambda r: r["size"])
        plt.plot([r["size"] for r in subset], [r[metric] for r in subset], marker="o", label=impl)
    plt.xlabel("Board size (N)")
    plt.ylabel(ylabel)
    plt.title(f"N-Queens {ylabel}")
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.legend()
    output_path = output_dir / f"nqueens_{metric}.png"
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"[plot] Saved {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Plot N-Queens benchmark metrics.")
    parser.add_argument("--input", type=Path, required=True, help="CSV file produced by run_nqueens_benchmarks.py")
    parser.add_argument("--output", type=Path, default=Path("results"), help="Directory to store plots (default: results)")
    args = parser.parse_args()

    rows = read_rows(args.input)
    args.output.mkdir(parents=True, exist_ok=True)

    plot_metric(rows, "time_sec", "Runtime (s)", args.output)
    plot_metric(rows, "max_rss_kb", "Peak RSS (KB)", args.output)
    plot_metric(rows, "nodes", "Nodes created", args.output)


if __name__ == "__main__":
    main()
