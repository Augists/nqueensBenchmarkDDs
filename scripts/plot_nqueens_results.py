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


LINE_MARKERS = ["o", "+", "*", "s", "^", "v", "D", "x", "p"]


def read_rows(csv_path):
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        rows = [row for row in reader]
    for row in rows:
        row["size"] = int(row["size"])
        row["time_sec"] = float(row["time_sec"])
        row["max_rss_kb"] = int(row["max_rss_kb"])
        row["nodes_created"] = int(row["nodes_created"])
        row["nodes_alive"] = int(row["nodes_alive"])
        row["solutions"] = float(row["solutions"])
    return rows


def filter_rows(rows, min_size=8, max_size=12):
    return [row for row in rows if min_size <= row["size"] <= max_size]


def get_implementation_markers(implementations):
    return {
        impl: LINE_MARKERS[index % len(LINE_MARKERS)]
        for index, impl in enumerate(implementations)
    }


def plot_line_metric(rows, metric, implementations):
    colors = get_implementation_colors(implementations)
    markers = get_implementation_markers(implementations)
    for impl in implementations:
        subset = sorted((r for r in rows if r["implementation"] == impl), key=lambda r: r["size"])
        marker = markers[impl]
        plot_kwargs = {
            "marker": marker,
            "label": impl,
            "color": colors[impl],
            "linewidth": 1.8,
            "markersize": 7,
            "markeredgewidth": 1.4,
        }
        plt.plot([r["size"] for r in subset], [r[metric] for r in subset], **plot_kwargs)


def get_implementation_colors(implementations):
    color_cycle = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    return {
        impl: color_cycle[index % len(color_cycle)]
        for index, impl in enumerate(implementations)
    }


def plot_bar_metric(rows, metric, implementations, sizes):
    width = 0.8 / max(len(implementations), 1)
    colors = get_implementation_colors(implementations)
    labeled_implementations = set()
    for size in sizes:
        size_rows = sorted(
            (r for r in rows if r["size"] == size),
            key=lambda r: (r[metric], r["implementation"]),
        )
        count = len(size_rows)
        positions = [
            size - (count * width) / 2 + width / 2 + index * width
            for index in range(count)
        ]
        for row, position in zip(size_rows, positions):
            impl = row["implementation"]
            label = impl if impl not in labeled_implementations else "_nolegend_"
            plt.bar(
                [position],
                [row[metric]],
                width=width,
                label=label,
                color=colors[impl],
            )
            labeled_implementations.add(impl)


def plot_metric(rows, metric, ylabel, output_dir, use_log_scale=False):
    rows = filter_rows(rows)
    plt.figure(figsize=(10, 5))
    implementations = sorted(set(r["implementation"] for r in rows))
    sizes = sorted(set(r["size"] for r in rows))
    if metric == "time_sec":
        plot_line_metric(rows, metric, implementations)
    else:
        plot_bar_metric(rows, metric, implementations, sizes)
    plt.xticks(sizes)
    if use_log_scale and all(r[metric] > 0 for r in rows):
        plt.yscale("log")
    plt.xlabel("Board size (N)")
    plt.ylabel(ylabel)
    plt.title(f"N-Queens {ylabel}")
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.legend()
    suffix = "_log" if use_log_scale else ""
    output_path = output_dir / f"nqueens_{metric}{suffix}.png"
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"[plot] Saved {output_path}")


def plot_all_metrics(rows, output_dir):
    metrics = [
        ("time_sec", "Runtime (s)"),
        ("max_rss_kb", "Peak RSS (KB)"),
        ("nodes_created", "Nodes created (total)"),
        ("nodes_alive", "Nodes alive (final)"),
    ]
    for metric, ylabel in metrics:
        plot_metric(rows, metric, ylabel, output_dir)
        if metric == "time_sec":
            plot_metric(rows, metric, ylabel, output_dir, use_log_scale=True)


def main():
    parser = argparse.ArgumentParser(description="Plot N-Queens benchmark metrics.")
    parser.add_argument("--input", type=Path, required=True, help="CSV file produced by run_nqueens_benchmarks.py")
    parser.add_argument("--output", type=Path, default=Path("results"), help="Directory to store plots (default: results)")
    args = parser.parse_args()

    rows = read_rows(args.input)
    args.output.mkdir(parents=True, exist_ok=True)

    plot_all_metrics(rows, args.output)


if __name__ == "__main__":
    main()
