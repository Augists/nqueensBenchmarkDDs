#!/usr/bin/env python3

import argparse
import csv
import multiprocessing as mp
import os
import re
import resource
import shutil
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
JOBS = max(1, os.cpu_count() or 1)


class Implementation:
    def __init__(self, name, language, preparer, command_builder, workdir=None, extra_env=None):
        self.name = name
        self.language = language
        self.preparer = preparer
        self.command_builder = command_builder
        self.workdir = workdir or ROOT
        self.extra_env = extra_env or {}

    def ensure_ready(self):
        if self.preparer:
            self.preparer()

    def command_for(self, size, workers):
        return self.command_builder(size, workers)

    def base_env(self):
        env = os.environ.copy()
        env.update(self.extra_env)
        return env


def run(cmd, cwd=ROOT, env=None):
    print(f"[build] {cwd.relative_to(ROOT) if cwd != ROOT else '.'}$ {' '.join(shlex.quote(str(c)) for c in cmd)}")
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def ensure_buddy():
    exe = ROOT / "BuDDy" / "examples" / "queen" / "queen"
    lib = ROOT / "BuDDy" / "src" / "libbdd.la"
    buddy_dir = ROOT / "BuDDy"
    configure_script = buddy_dir / "configure"
    if configure_script.exists() and not os.access(configure_script, os.X_OK):
        configure_script.chmod(configure_script.stat().st_mode | 0o111)
    if not (buddy_dir / "config.status").exists():
        run(["./configure"], cwd=buddy_dir)
    if not lib.exists():
        run(["make"], cwd=buddy_dir)
    if not exe.exists():
        run(["make", "-C", "examples/queen", "queen"], cwd=buddy_dir)
    run(["make", "-C", "examples/queen", "queen"], cwd=buddy_dir)


def ensure_sylvan():
    binary = ROOT / "sylvan" / "build" / "examples" / "nqueens_fast"
    if binary.exists():
        return
    run([
        "cmake",
        "-S", "sylvan",
        "-B", "sylvan/build",
        "-DSYLVAN_STATS=ON",
        "-DBUILD_SHARED_LIBS=OFF",
        "-DCMAKE_BUILD_TYPE=Release",
    ])
    run([
        "cmake",
        "--build", "sylvan/build",
        "--target", "nqueens_fast",
        f"-j{JOBS}",
    ])


def ensure_cudd():
    cudd_dir = ROOT / "cudd"
    lib = cudd_dir / "cudd" / ".libs" / "libcudd.a"
    if not lib.exists():
        configure_script = cudd_dir / "configure"
        if configure_script.exists() and not os.access(configure_script, os.X_OK):
            configure_script.chmod(configure_script.stat().st_mode | 0o111)
        if not (cudd_dir / "config.status").exists():
            run(["./configure"], cwd=cudd_dir)
        run([
            "make",
            f"-j{JOBS}",
            "ACLOCAL=true",
            "AUTOMAKE=true",
            "AUTOCONF=true",
            "AUTOHEADER=true",
        ], cwd=cudd_dir)
    exe = ROOT / "cudd" / "bin" / "nqueens_bdd"
    if not exe.exists():
        (ROOT / "cudd" / "bin").mkdir(parents=True, exist_ok=True)
        run([
            "gcc",
            "-O3",
            "-I./cudd",
            "-I./cudd/cudd",
            "-I./cudd/mtr",
            "-I./cudd/st",
            "-I./cudd/util",
            "-I./cudd/epd",
            "-o", "cudd/bin/nqueens_bdd",
            "cudd/examples/nqueens_bdd.c",
            "cudd/cudd/.libs/libcudd.a",
            "-lm",
        ])


def ensure_jdd():
    classes_flag = ROOT / "jdd" / "build" / "classes" / "java" / "main" / "jdd" / "examples" / "BDDQueens.class"
    if classes_flag.exists():
        return
    gradlew = ROOT / "jdd" / "gradlew"
    if gradlew.exists() and not os.access(gradlew, os.X_OK):
        gradlew.chmod(gradlew.stat().st_mode | 0o111)
    run(["./gradlew", "--no-daemon", "classes"], cwd=ROOT / "jdd")


def ensure_jsylvan():
    env_with_pkg = os.environ.copy()
    pkg_config = shutil.which("pkg-config")
    if pkg_config:
        env_with_pkg["PKG_CONFIG"] = pkg_config
        env_with_pkg["PKG_CONFIG_EXECUTABLE"] = pkg_config

    native_lib = ROOT / "jsylvan" / "src" / "main" / "resources" / "linux-x64" / "libsylvan-java.so"
    if not native_lib.exists():
        build_script = ROOT / "jsylvan" / "src" / "main" / "c" / "sylvan-java" / "build-sylvan.sh"
        if build_script.exists() and not os.access(build_script, os.X_OK):
            build_script.chmod(build_script.stat().st_mode | 0o111)
        run([
            "./src/main/c/sylvan-java/build-sylvan.sh",
            "https://github.com/trolando/sylvan.git",
            "v1.4.1",
        ], cwd=ROOT / "jsylvan", env=env_with_pkg)
    jar = ROOT / "jsylvan" / "target" / "sylvan-1.0.0-SNAPSHOT.jar"
    if not jar.exists():
        run(["mvn", "-q", "-DskipTests", "package"], cwd=ROOT / "jsylvan")


def execute_with_metrics(cmd, cwd, env):
    queue = mp.Queue()

    def worker():
        start = time.perf_counter()
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        elapsed = time.perf_counter() - start
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        queue.put({
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "elapsed": elapsed,
            "max_rss": usage.ru_maxrss,
            "cmd": cmd,
        })

    process = mp.Process(target=worker)
    process.start()
    process.join()
    if not process.exitcode == 0:
        raise RuntimeError("Measurement helper failed")
    if queue.empty():
        raise RuntimeError("Measurement helper returned no data")
    return queue.get()


METRIC_PATTERN = re.compile(r"NQUEENS_METRICS\s+[^n]*n=(\d+)\s+[^s]*solutions=([0-9.]+)\s+[^n]*nodes=(\d+)")
def parse_metrics(stdout):
    match = None
    for line in stdout.strip().splitlines():
        maybe = METRIC_PATTERN.search(line)
        if maybe:
            match = maybe
    if not match:
        raise RuntimeError("Failed to parse NQUEENS_METRICS from program output")
    size = int(match.group(1))
    solutions = float(match.group(2))
    nodes = int(match.group(3))
    return size, solutions, nodes


def run_implementation(impl, size, workers):
    cmd = impl.command_for(size, workers)
    env = impl.base_env()
    result = execute_with_metrics(cmd, cwd=impl.workdir, env=env)
    if result["returncode"] != 0:
        raise subprocess.CalledProcessError(
            result["returncode"],
            result["cmd"],
            output=result["stdout"],
            stderr=result["stderr"],
        )
    measured_size, solutions, nodes = parse_metrics(result["stdout"])
    if measured_size != size:
        raise RuntimeError(f"Implementation {impl.name} reported size {measured_size} but expected {size}")
    time_sec = result["elapsed"]
    max_rss = result["max_rss"]
    print(f"[run] {impl.name:10s} N={size:2d} time={time_sec:7.3f}s rss={max_rss:>8d}KB nodes={nodes}")
    return {
        "implementation": impl.name,
        "language": impl.language,
        "size": size,
        "time_sec": time_sec,
        "max_rss_kb": max_rss,
        "nodes": nodes,
        "solutions": solutions,
    }


def write_results(rows, output_path):
    RESULTS_DIR.mkdir(exist_ok=True)
    fieldnames = ["implementation", "language", "size", "time_sec", "max_rss_kb", "nodes", "solutions"]
    with output_path.open("w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"[done] Results saved to {output_path.relative_to(ROOT)}")


def parse_args():
    parser = argparse.ArgumentParser(description="Run N-Queens benchmarks across multiple BDD implementations.")
    parser.add_argument(
        "--sizes",
        nargs="+",
        type=int,
        default=list(range(4, 13)),
        help="Board sizes to benchmark (default: 4 5 ... 12)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Worker threads for Sylvan-based implementations (0 = autodetect, default: 0)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=RESULTS_DIR / "nqueens_metrics.csv",
        help="Output CSV path (default: results/nqueens_metrics.csv)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    implementations = [
        Implementation(
            "BuDDy",
            "C",
            ensure_buddy,
            lambda size, _: [str(ROOT / "BuDDy" / "examples" / "queen" / "queen"), str(size)],
            workdir=ROOT,
            extra_env={
                "LD_LIBRARY_PATH": f"{ROOT / 'BuDDy' / 'src' / '.libs'}:{os.environ.get('LD_LIBRARY_PATH','')}",
            },
        ),
        Implementation(
            "Sylvan",
            "C",
            ensure_sylvan,
            lambda size, workers: [
                str(ROOT / "sylvan" / "build" / "examples" / "nqueens_fast"),
                "-w", str(workers),
                str(size),
            ],
            workdir=ROOT,
            extra_env={
                "LD_LIBRARY_PATH": f"{ROOT / 'sylvan' / 'build' / 'src'}:{os.environ.get('LD_LIBRARY_PATH','')}",
            },
        ),
        Implementation(
            "CUDD",
            "C",
            ensure_cudd,
            lambda size, _: [str(ROOT / "cudd" / "bin" / "nqueens_bdd"), str(size)],
        ),
        Implementation(
            "JDD",
            "Java",
            ensure_jdd,
            lambda size, _: [
                "java",
                "-cp", "build/classes/java/main",
                "jdd.examples.BDDQueens",
                str(size),
            ],
            workdir=ROOT / "jdd",
        ),
        Implementation(
            "JSylvan",
            "Java",
            ensure_jsylvan,
            lambda size, workers: [
                "java",
                "-cp", "target/sylvan-1.0.0-SNAPSHOT.jar",
                "jsylvan.examples.JSylvanNQueens",
                "-w", str(workers),
                str(size),
            ],
            workdir=ROOT / "jsylvan",
        ),
    ]

    for impl in implementations:
        impl.ensure_ready()

    rows = []
    for size in args.sizes:
        for impl in implementations:
            rows.append(run_implementation(impl, size, args.workers))

    write_results(rows, args.output)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"[error] Command failed with exit code {exc.returncode}: {' '.join(exc.cmd)}", file=sys.stderr)
        sys.exit(exc.returncode)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
