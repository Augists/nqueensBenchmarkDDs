import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import plot_nqueens_results


def make_row(implementation, size, value):
    return {
        "implementation": implementation,
        "size": size,
        "time_sec": value,
        "max_rss_kb": int(value * 1000),
        "nodes_created": int(value * 10000),
        "nodes_alive": int(value * 5000),
        "solutions": float(size),
    }


class PlotMetricTests(unittest.TestCase):
    def test_plot_metric_filters_rows_below_min_size(self):
        rows = [
            make_row("ImplA", 7, 0.01),
            make_row("ImplA", 8, 0.02),
            make_row("ImplA", 12, 0.5),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with mock.patch.object(plot_nqueens_results.plt, "plot") as plot:
                plot_nqueens_results.plot_metric(rows, "time_sec", "Runtime (s)", output_dir)

        x_values = plot.call_args.args[0]
        self.assertEqual(x_values, [8, 12])

    def test_plot_metric_keeps_linear_scale_by_default(self):
        rows = [
            make_row("ImplA", 8, 0.02),
            make_row("ImplA", 12, 0.5),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with mock.patch.object(plot_nqueens_results.plt, "yscale") as yscale:
                plot_nqueens_results.plot_metric(rows, "time_sec", "Runtime (s)", output_dir)

        yscale.assert_not_called()

    def test_plot_metric_uses_log_scale_when_requested(self):
        rows = [
            make_row("ImplA", 8, 0.02),
            make_row("ImplA", 12, 0.5),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with mock.patch.object(plot_nqueens_results.plt, "yscale") as yscale:
                plot_nqueens_results.plot_metric(
                    rows,
                    "time_sec",
                    "Runtime (s)",
                    output_dir,
                    use_log_scale=True,
                )

        yscale.assert_called_once_with("log")

    def test_plot_metric_uses_integer_x_ticks(self):
        rows = [
            make_row("ImplA", 8, 0.02),
            make_row("ImplA", 9, 0.05),
            make_row("ImplA", 10, 0.12),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with mock.patch.object(plot_nqueens_results.plt, "xticks") as xticks:
                plot_nqueens_results.plot_metric(rows, "time_sec", "Runtime (s)", output_dir)

        xticks.assert_called_once_with([8, 9, 10])

    def test_plot_metric_uses_bar_chart_for_peak_rss(self):
        rows = [
            make_row("ImplA", 8, 0.02),
            make_row("ImplA", 9, 0.05),
            make_row("ImplB", 8, 0.03),
            make_row("ImplB", 9, 0.06),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with (
                mock.patch.object(plot_nqueens_results.plt, "bar") as bar,
                mock.patch.object(plot_nqueens_results.plt, "plot") as plot,
            ):
                plot_nqueens_results.plot_metric(rows, "max_rss_kb", "Peak RSS (KB)", output_dir)

        self.assertGreater(len(bar.call_args_list), 0)
        plot.assert_not_called()

    def test_plot_metric_uses_requested_marker_sequence(self):
        rows = [
            make_row("ImplA", 8, 0.02),
            make_row("ImplA", 9, 0.05),
            make_row("ImplB", 8, 0.03),
            make_row("ImplB", 9, 0.06),
            make_row("ImplC", 8, 0.04),
            make_row("ImplC", 9, 0.07),
            make_row("ImplD", 8, 0.08),
            make_row("ImplD", 9, 0.09),
            make_row("ImplE", 8, 0.10),
            make_row("ImplE", 9, 0.11),
            make_row("ImplF", 8, 0.12),
            make_row("ImplF", 9, 0.13),
            make_row("ImplG", 8, 0.14),
            make_row("ImplG", 9, 0.15),
            make_row("ImplH", 8, 0.16),
            make_row("ImplH", 9, 0.17),
            make_row("ImplI", 8, 0.18),
            make_row("ImplI", 9, 0.19),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with mock.patch.object(plot_nqueens_results.plt, "plot") as plot:
                plot_nqueens_results.plot_metric(rows, "time_sec", "Runtime (s)", output_dir)

        markers = [call.kwargs["marker"] for call in plot.call_args_list]
        self.assertEqual(markers, ["o", "+", "*", "s", "^", "v", "D", "x", "p"])

    def test_plot_metric_uses_wider_figure(self):
        rows = [
            make_row("ImplA", 8, 0.02),
            make_row("ImplB", 8, 0.03),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with mock.patch.object(plot_nqueens_results.plt, "figure") as figure:
                plot_nqueens_results.plot_metric(rows, "max_rss_kb", "Peak RSS (KB)", output_dir)

        figure_sizes = [call.kwargs.get("figsize") for call in figure.call_args_list]
        self.assertIn((10, 5), figure_sizes)

    def test_plot_metric_keeps_bar_chart_for_other_non_time_metrics(self):
        rows = [
            make_row("ImplA", 8, 0.02),
            make_row("ImplA", 9, 0.05),
            make_row("ImplB", 8, 0.03),
            make_row("ImplB", 9, 0.06),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with (
                mock.patch.object(plot_nqueens_results.plt, "bar") as bar,
                mock.patch.object(plot_nqueens_results.plt, "plot") as plot,
            ):
                plot_nqueens_results.plot_metric(rows, "nodes_created", "Nodes created (total)", output_dir)

        self.assertGreater(len(bar.call_args_list), 0)
        plot.assert_not_called()

    def test_plot_all_metrics_writes_time_log_file_only(self):
        rows = [
            make_row("ImplA", 8, 0.02),
            make_row("ImplA", 12, 0.5),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with mock.patch.object(plot_nqueens_results.plt, "savefig") as savefig:
                plot_nqueens_results.plot_all_metrics(rows, output_dir)

        saved_paths = [Path(call.args[0]).name for call in savefig.call_args_list]
        self.assertEqual(
            saved_paths,
            [
                "nqueens_time_sec.png",
                "nqueens_time_sec_log.png",
                "nqueens_max_rss_kb.png",
                "nqueens_nodes_created.png",
                "nqueens_nodes_alive.png",
            ],
        )


if __name__ == "__main__":
    unittest.main()
