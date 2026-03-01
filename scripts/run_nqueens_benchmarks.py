#!/usr/bin/env python3

import argparse
import csv
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
    buddy_dir = ROOT / "BuDDy"
    configure_script = buddy_dir / "configure"
    if configure_script.exists() and not os.access(configure_script, os.X_OK):
        configure_script.chmod(configure_script.stat().st_mode | 0o111)
    if not (buddy_dir / "config.status").exists():
        run(["./configure"], cwd=buddy_dir)
    if not (buddy_dir / "src" / "libbdd.la").exists():
        run(["make"], cwd=buddy_dir)
    # Clean and rebuild the queen example
    run(["make", "-C", "examples/queen", "clean"], cwd=buddy_dir)
    run(["make", "-C", "examples/queen", "queen"], cwd=buddy_dir)


def ensure_sylvan():
    build_dir = ROOT / "sylvan" / "build"
    if not (build_dir / "CMakeCache.txt").exists():
        run([
            "cmake",
            "-S", "sylvan",
            "-B", "sylvan/build",
            "-DSYLVAN_STATS=ON",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DCMAKE_BUILD_TYPE=Release",
        ])
    # Clean and rebuild nqueens_fast
    run(["cmake", "--build", "sylvan/build", "--target", "nqueens_fast", "--clean-first", f"-j{JOBS}"])


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
    # Clean and rebuild nqueens_bdd
    exe = ROOT / "cudd" / "bin" / "nqueens_bdd"
    if exe.exists():
        exe.unlink()
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
    gradlew = ROOT / "jdd" / "gradlew"
    if gradlew.exists() and not os.access(gradlew, os.X_OK):
        gradlew.chmod(gradlew.stat().st_mode | 0o111)
    # Clean and rebuild
    run(["./gradlew", "--no-daemon", "clean", "classes"], cwd=ROOT / "jdd")


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
    # Clean and rebuild
    run(["mvn", "-q", "-DskipTests", "clean", "package"], cwd=ROOT / "jsylvan", env=env_with_pkg)


def ensure_ndd():
    jdd_jar = ROOT / "NDD" / "lib" / "jdd-111.jar"
    if not jdd_jar.exists():
        raise FileNotFoundError(f"Missing NDD dependency {jdd_jar}")
    # Ensure local Maven repo has the JDD artifact
    run([
        "mvn",
        "-q",
        "install:install-file",
        f"-Dfile={jdd_jar}",
        "-DgroupId=org.bitbucket.vahidi",
        "-DartifactId=JDD",
        "-Dversion=111",
        "-Dpackaging=jar",
    ], cwd=ROOT / "NDD")
    # Clean and rebuild
    run(["mvn", "-q", "-DskipTests", "clean", "package"], cwd=ROOT / "NDD")


def ensure_decisiondiagrams():
    dd_dir = ROOT / "DecisionDiagrams"
    # Check if dotnet is available
    if not shutil.which("dotnet"):
        raise RuntimeError("dotnet SDK is not installed. Install it with: sudo pacman -S dotnet-sdk-6.0")
    # Clean and rebuild
    run(["dotnet", "clean", "-c", "Release", "DecisionDiagrams.sln"], cwd=dd_dir)
    run(["dotnet", "build", "-c", "Release", "DecisionDiagrams.sln"], cwd=dd_dir)


MAX_TIMEOUT = 300   # 5 minute hard timeout per run
MAX_RETRIES = 3     # retry on timeout (handles Lace/Sylvan intermittent hangs)

def execute_with_metrics(cmd, cwd, env):
    """Execute command and measure time/memory. Retries on timeout."""
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            start_time = time.perf_counter()
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=MAX_TIMEOUT,
            )
            elapsed_time = time.perf_counter() - start_time

            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            max_rss = usage.ru_maxrss

            return {
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "elapsed": elapsed_time,
                "max_rss": max_rss,
                "cmd": cmd,
            }
        except subprocess.TimeoutExpired as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                print(f"[retry] Timeout on attempt {attempt}/{MAX_RETRIES}, retrying...")
                time.sleep(2)
    raise last_exc


METRIC_PATTERN = re.compile(
    r"NQUEENS_METRICS\s+n=(\d+)\s+solutions=([0-9.]+)\s+nodes_created=(\d+)\s+nodes_alive=(\d+)"
)
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
    nodes_created = int(match.group(3))
    nodes_alive = int(match.group(4))
    return size, solutions, nodes_created, nodes_alive


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
    measured_size, solutions, nodes_created, nodes_alive = parse_metrics(result["stdout"])
    if measured_size != size:
        raise RuntimeError(f"Implementation {impl.name} reported size {measured_size} but expected {size}")
    time_sec = result["elapsed"]
    max_rss = result["max_rss"]
    print(f"[run] {impl.name:10s} N={size:2d} time={time_sec:7.3f}s rss={max_rss:>8d}KB "
          f"created={nodes_created} alive={nodes_alive}")
    return {
        "implementation": impl.name,
        "language": impl.language,
        "size": size,
        "time_sec": time_sec,
        "max_rss_kb": max_rss,
        "nodes_created": nodes_created,
        "nodes_alive": nodes_alive,
        "solutions": solutions,
    }


def write_results(rows, output_path):
    RESULTS_DIR.mkdir(exist_ok=True)
    fieldnames = ["implementation", "language", "size", "time_sec", "max_rss_kb", "nodes_created", "nodes_alive", "solutions"]
    with output_path.open("w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    try:
        display_path = output_path.relative_to(ROOT)
    except ValueError:
        display_path = output_path
    print(f"[done] Results saved to {display_path}")


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
    parser.add_argument(
        "--targets",
        nargs="+",
        default=["all"],
        help="Which implementations to run (default: all). Example: --targets BuDDy Sylvan JSylvan",
    )
    return parser.parse_args()


def build_implementations():
    return [
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
        Implementation(
            "NDD",
            "Java",
            ensure_ndd,
            lambda size, _: [
                "java",
                "-cp", str(ROOT / "NDD" / "target" / "ndd-1.0.1-jar-with-dependencies.jar"),
                "application.nqueen.NDDSolution",
                str(size),
            ],
            workdir=ROOT / "NDD",
        ),
        Implementation(
            "DD-BDD",
            "C#",
            ensure_decisiondiagrams,
            lambda size, _: [
                "dotnet",
                str(ROOT / "DecisionDiagrams" / "DecisionDiagrams.Bench" / "bin" / "Release" / "net6.0" / "DecisionDiagrams.Bench.dll"),
                str(size),
                "--use-bdd",
            ],
            workdir=ROOT / "DecisionDiagrams",
        ),
        Implementation(
            "DD-CBDD",
            "C#",
            ensure_decisiondiagrams,
            lambda size, _: [
                "dotnet",
                str(ROOT / "DecisionDiagrams" / "DecisionDiagrams.Bench" / "bin" / "Release" / "net6.0" / "DecisionDiagrams.Bench.dll"),
                str(size),
            ],
            workdir=ROOT / "DecisionDiagrams",
        ),
    ]


def main():
    args = parse_args()
    available_impls = build_implementations()
    impl_map = {impl.name.lower(): impl for impl in available_impls}
    requested = [t.lower() for t in args.targets]
    if requested == ["all"]:
        selected_impls = available_impls
    else:
        missing = [t for t in requested if t not in impl_map]
        if missing:
            raise ValueError(f"Unknown implementations requested: {', '.join(missing)}. Available: {', '.join(impl_map.keys())}")
        seen = set()
        selected_impls = []
        for name in requested:
            if name in seen:
                continue
            seen.add(name)
            selected_impls.append(impl_map[name])

    for impl in selected_impls:
        impl.ensure_ready()

    rows = []
    for size in args.sizes:
        for impl in selected_impls:
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
