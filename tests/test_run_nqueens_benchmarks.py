import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import run_nqueens_benchmarks


class CacheHealingHelperTests(unittest.TestCase):
    def test_cache_paths_match_current_workspace_rejects_stale_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "workspace"
            root.mkdir()
            cache_file = root / "cache.txt"
            cache_file.write_text("build_dir=/home/augists/old-workspace/build\n", encoding="utf-8")

            self.assertFalse(
                run_nqueens_benchmarks.cache_paths_match_current_workspace(cache_file, [root]),
            )


class EnsureBuddyTests(unittest.TestCase):
    def test_ensure_buddy_reconfigures_when_cached_paths_are_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            buddy_dir = root / "BuDDy"
            (buddy_dir / "src").mkdir(parents=True)
            (buddy_dir / "examples" / "queen").mkdir(parents=True)
            (buddy_dir / "configure").write_text("#!/bin/sh\n", encoding="utf-8")
            (buddy_dir / "config.status").write_text("srcdir=/home/augists/old/BuDDy\n", encoding="utf-8")
            (buddy_dir / "src" / "Makefile").write_text("srcdir=/home/augists/old/BuDDy/src\n", encoding="utf-8")
            (buddy_dir / "src" / "libbdd.la").write_text("", encoding="utf-8")

            with (
                mock.patch.object(run_nqueens_benchmarks, "ROOT", root),
                mock.patch.object(run_nqueens_benchmarks, "run") as run,
            ):
                run_nqueens_benchmarks.ensure_buddy()

        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(["./configure"], commands)
        self.assertIn(["make"], commands)


class EnsureSylvanTests(unittest.TestCase):
    def test_sylvan_cmake_enables_mmap_by_default(self):
        cmake_file = run_nqueens_benchmarks.ROOT / "sylvan" / "src" / "CMakeLists.txt"
        cmake_text = cmake_file.read_text(encoding="utf-8")

        self.assertIn(
            'option(SYLVAN_USE_MMAP "Let Sylvan use mmap to allocate (virtual) memory" ON)',
            cmake_text,
        )

    def test_ensure_sylvan_removes_stale_build_dir_before_reconfigure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            build_dir = root / "sylvan" / "build"
            build_dir.mkdir(parents=True)
            (build_dir / "CMakeCache.txt").write_text(
                "CMAKE_HOME_DIRECTORY:INTERNAL=/home/augists/old/sylvan\n"
                "CMAKE_CACHEFILE_DIR:INTERNAL=/home/augists/old/sylvan/build\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(run_nqueens_benchmarks, "ROOT", root),
                mock.patch.object(run_nqueens_benchmarks, "run") as run,
                mock.patch.object(run_nqueens_benchmarks.shutil, "rmtree") as rmtree,
            ):
                run_nqueens_benchmarks.ensure_sylvan()

        rmtree.assert_called_once_with(build_dir)
        configure_cmd = run.call_args_list[0].args[0]
        self.assertNotIn("-DSYLVAN_USE_MMAP=OFF", configure_cmd)

    def test_nqueens_fast_uses_sylvan_set_limits_instead_of_fixed_sizes(self):
        source = (run_nqueens_benchmarks.ROOT / "sylvan" / "examples" / "nqueens_fast.c").read_text(
            encoding="utf-8"
        )

        self.assertIn("sylvan_set_limits(", source)
        self.assertNotIn("sylvan_set_sizes(", source)


class EnsureCuddTests(unittest.TestCase):
    def test_ensure_cudd_reconfigures_and_rebuilds_when_cached_paths_are_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cudd_dir = root / "cudd"
            (cudd_dir / "cudd" / ".libs").mkdir(parents=True)
            (cudd_dir / "bin").mkdir(parents=True)
            (cudd_dir / "configure").write_text("#!/bin/sh\n", encoding="utf-8")
            (cudd_dir / "config.status").write_text("srcdir=/home/augists/old/cudd\n", encoding="utf-8")
            (cudd_dir / "Makefile").write_text("top_srcdir=/home/augists/old/cudd\n", encoding="utf-8")
            (cudd_dir / "cudd" / ".libs" / "libcudd.a").write_text("", encoding="utf-8")

            with (
                mock.patch.object(run_nqueens_benchmarks, "ROOT", root),
                mock.patch.object(run_nqueens_benchmarks, "run") as run,
            ):
                run_nqueens_benchmarks.ensure_cudd()

        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(["./configure"], commands)
        self.assertIn(
            ["make", f"-j{run_nqueens_benchmarks.JOBS}", "ACLOCAL=true", "AUTOMAKE=true", "AUTOCONF=true", "AUTOHEADER=true"],
            commands,
        )


class EnsureDecisionDiagramsTests(unittest.TestCase):
    def test_ensure_decisiondiagrams_restores_before_clean_and_build(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "DecisionDiagrams").mkdir(parents=True)

            with (
                mock.patch.object(run_nqueens_benchmarks, "ROOT", root),
                mock.patch.object(run_nqueens_benchmarks.shutil, "which", return_value="/usr/bin/dotnet"),
                mock.patch.object(run_nqueens_benchmarks, "run") as run,
            ):
                run_nqueens_benchmarks.ensure_decisiondiagrams()

        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            commands[:3],
            [
                ["dotnet", "restore", "DecisionDiagrams.sln"],
                ["dotnet", "clean", "-c", "Release", "DecisionDiagrams.sln"],
                ["dotnet", "build", "-c", "Release", "DecisionDiagrams.sln"],
            ],
        )


class MetricsParsingTests(unittest.TestCase):
    def test_parse_metrics_accepts_optional_seconds_field(self):
        size, solutions, nodes_created, nodes_alive, seconds = run_nqueens_benchmarks.parse_metrics(
            "NQUEENS_METRICS n=8 solutions=92 nodes_created=1234 nodes_alive=456 seconds=0.789\n"
        )

        self.assertEqual(size, 8)
        self.assertEqual(solutions, 92.0)
        self.assertEqual(nodes_created, 1234)
        self.assertEqual(nodes_alive, 456)
        self.assertEqual(seconds, 0.789)

    def test_run_implementation_prefers_reported_seconds(self):
        impl = run_nqueens_benchmarks.Implementation(
            "NDD",
            "Java",
            preparer=None,
            command_builder=lambda size, _: ["java", "NDDSolution", str(size)],
        )

        with mock.patch.object(
            run_nqueens_benchmarks,
            "execute_with_metrics",
            return_value={
                "returncode": 0,
                "stdout": "NQUEENS_METRICS n=8 solutions=92 nodes_created=1234 nodes_alive=456 seconds=0.789\n",
                "stderr": "",
                "elapsed": 1.234,
                "max_rss": 2048,
                "cmd": ["java", "NDDSolution", "8"],
            },
        ):
            row = run_nqueens_benchmarks.run_implementation(impl, 8, 0)

        self.assertEqual(row["time_sec"], 0.789)
        self.assertEqual(row["nodes_alive"], 456)


if __name__ == "__main__":
    unittest.main()
