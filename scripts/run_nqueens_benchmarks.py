#!/usr/bin/env python3

import argparse
import csv
import os
import re
import shutil
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
JOBS = max(1, os.cpu_count() or 1)
DEFAULT_SIZES = list(range(8, 13))
DEFAULT_TIMEOUT_SEC = 500
JSYLVAN_MEMORY_MB = 2048
EXCLUDED_DEFAULT_TARGETS = {"NDD-SoA-BCDD", "NDD-SoA-FD-ZDD" , "ZDD"}


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


def _read_text_file(path):
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except FileNotFoundError:
        return None


def cache_paths_match_current_workspace(cache_file, expected_paths):
    text = _read_text_file(cache_file)
    if text is None:
        return False
    return all(str(path) in text for path in expected_paths)


def heal_stale_path_cache(cache_files, expected_paths, reset_paths):
    existing_files = [path for path in cache_files if path.exists()]
    if not existing_files:
        return False
    if all(cache_paths_match_current_workspace(path, expected_paths) for path in existing_files):
        return False
    for path in reset_paths:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    return True


def ensure_buddy():
    buddy_dir = ROOT / "BuDDy"
    configure_script = buddy_dir / "configure"
    config_status = buddy_dir / "config.status"
    top_makefile = buddy_dir / "Makefile"
    src_makefile = buddy_dir / "src" / "Makefile"
    queen_makefile = buddy_dir / "examples" / "queen" / "Makefile"
    libbdd = buddy_dir / "src" / "libbdd.la"
    if configure_script.exists() and not os.access(configure_script, os.X_OK):
        configure_script.chmod(configure_script.stat().st_mode | 0o111)
    healed = heal_stale_path_cache(
        [config_status, src_makefile, queen_makefile],
        [buddy_dir],
        [config_status, top_makefile, src_makefile, queen_makefile, libbdd],
    )
    if healed or not config_status.exists():
        run(["./configure"], cwd=buddy_dir)
    if healed or not libbdd.exists():
        run(["make"], cwd=buddy_dir)
    # Clean and rebuild the queen example
    run(["make", "-C", "examples/queen", "clean"], cwd=buddy_dir)
    run(["make", "-C", "examples/queen", "queen"], cwd=buddy_dir)


def ensure_sylvan():
    build_dir = ROOT / "sylvan" / "build"
    heal_stale_path_cache(
        [build_dir / "CMakeCache.txt"],
        [ROOT / "sylvan", build_dir],
        [build_dir],
    )
    run([
        "cmake",
        "-S", "sylvan",
        "-B", "sylvan/build",
        "-DSYLVAN_STATS=ON",
        "-DBUILD_SHARED_LIBS=OFF",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DSYLVAN_USE_MMAP=ON",
    ])
    # Clean and rebuild nqueens_fast
    run(["cmake", "--build", "sylvan/build", "--target", "nqueens_fast", "--clean-first", f"-j{JOBS}"])
    
def ensure_cudd():
    cudd_dir = ROOT / "cudd"
    lib = cudd_dir / "cudd" / ".libs" / "libcudd.a"
    config_status = cudd_dir / "config.status"
    top_makefile = cudd_dir / "Makefile"
    cudd_makefile = cudd_dir / "cudd" / "Makefile"
    configure_script = cudd_dir / "configure"
    if configure_script.exists() and not os.access(configure_script, os.X_OK):
        configure_script.chmod(configure_script.stat().st_mode | 0o111)
    healed = heal_stale_path_cache(
        [config_status, top_makefile, cudd_makefile],
        [cudd_dir],
        [config_status, top_makefile, cudd_makefile, lib],
    )
    if healed or not config_status.exists():
        run(["./configure"], cwd=cudd_dir)
    if healed or not lib.exists():
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

def ensure_ndd_reuse():
    import zipfile
    ndd_reuse_dir = ROOT / "NDD-reuse"
    jdd_jar = ndd_reuse_dir / "lib" / "jdd-111.jar"
    if not jdd_jar.exists():
        raise FileNotFoundError(f"Missing NDD-reuse dependency {jdd_jar}")
    run([
        "mvn",
        "-q",
        "install:install-file",
        f"-Dfile={jdd_jar}",
        "-DgroupId=org.bitbucket.vahidi",
        "-DartifactId=JDD",
        "-Dversion=111",
        "-Dpackaging=jar",
    ], cwd=ndd_reuse_dir)
    run(["mvn", "-q", "-DskipTests", "clean", "package"], cwd=ndd_reuse_dir)
    # The maven-assembly jar-with-dependencies unpacks jdd-111.jar and its original BDD.class
    # overwrites the patched BDD.class compiled from NDD-reuse's own jdd/bdd/BDD.java source.
    # Patch the fat jar by replacing the affected class entries with the compiled patched versions.
    fat_jar = ndd_reuse_dir / "target" / "ndd-1.0.1-jar-with-dependencies.jar"
    classes_dir = ndd_reuse_dir / "target" / "classes"
    patched_classes = {
        cls_file.relative_to(classes_dir).as_posix(): cls_file
        for cls_file in classes_dir.glob("jdd/**/*.class")
    }
    if patched_classes:
        print(f"[patch] Replacing {len(patched_classes)} patched BDD class(es) in fat jar")
        tmp_jar = fat_jar.with_suffix(".jar.tmp")
        with zipfile.ZipFile(fat_jar, "r") as src, zipfile.ZipFile(tmp_jar, "w", compression=zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                if item.filename in patched_classes:
                    dst.write(patched_classes[item.filename], item.filename)
                else:
                    dst.writestr(item, src.read(item.filename))
        tmp_jar.replace(fat_jar)

def ensure_ndd_soa():
    jdd_jar = ROOT / "NDD-SoA" / "lib" / "jdd-111.jar"
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
    ], cwd=ROOT / "NDD-SoA")
    # Clean and rebuild
    run(["mvn", "-q", "-DskipTests", "clean", "package"], cwd=ROOT / "NDD-SoA")

def ensure_decisiondiagrams():
    dd_dir = ROOT / "DecisionDiagrams"
    # Check if dotnet is available
    if not shutil.which("dotnet"):
        raise RuntimeError("dotnet SDK is not installed. Install it with: sudo pacman -S dotnet-sdk-6.0")
    # Clean and rebuild
    run(["dotnet", "restore", "DecisionDiagrams.sln"], cwd=dd_dir)
    run(["dotnet", "clean", "-c", "Release", "DecisionDiagrams.sln"], cwd=dd_dir)
    run(["dotnet", "build", "-c", "Release", "DecisionDiagrams.sln"], cwd=dd_dir)


TIMEOUT_SENTINEL_METRICS = {
    "solutions": 0.0,
    "nodes_created": 0,
    "nodes_alive": 0,
    "ndd_nodes_created": 0,
    "ndd_nodes_alive": 0,
    "bdd_nodes_created": 0,
    "bdd_nodes_alive": 0,
}

def _poll_rss(pid, interval, result):
    """Background thread: poll RSS of pid and its children, record peak (KB)."""
    peak = 0
    try:
        proc = psutil.Process(pid)
        while True:
            try:
                rss = proc.memory_info().rss
                for child in proc.children(recursive=True):
                    try:
                        rss += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                if rss > peak:
                    peak = rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            time.sleep(interval)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    result["peak_rss_kb"] = peak // 1024


def execute_with_metrics(cmd, cwd, env, timeout_sec=DEFAULT_TIMEOUT_SEC):
    """Execute command and measure time/memory, returning a timeout result instead of retrying."""
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    rss_result = {}
    poller = threading.Thread(target=_poll_rss, args=(proc.pid, 0.05, rss_result), daemon=True)
    poller.start()

    start_time = time.perf_counter()
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout_sec)
        elapsed_time = time.perf_counter() - start_time
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        elapsed_time = timeout_sec
        timed_out = True

    poller.join(timeout=1)
    max_rss = rss_result.get("peak_rss_kb", 0)

    return {
        "returncode": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "elapsed": elapsed_time,
        "max_rss": max_rss,
        "cmd": cmd,
        "timed_out": timed_out,
    }


def parse_metrics(stdout):
    metric_line = None
    for line in stdout.strip().splitlines():
        if "NQUEENS_METRICS" in line:
            metric_line = line.strip()
    if not metric_line:
        raise RuntimeError("Failed to parse NQUEENS_METRICS from program output")

    parts = {}
    for token in metric_line.split():
        if token == "NQUEENS_METRICS" or "=" not in token:
            continue
        key, value = token.split("=", 1)
        parts[key] = value

    size = int(parts["n"])
    solutions = float(parts["solutions"])
    nodes_created = int(parts["nodes_created"])
    nodes_alive = int(parts["nodes_alive"])
    ndd_nodes_created = int(parts.get("ndd_nodes_created", 0))
    ndd_nodes_alive = int(parts.get("ndd_nodes_alive", 0))
    bdd_nodes_created = int(parts.get("bdd_nodes_created", nodes_created))
    bdd_nodes_alive = int(parts.get("bdd_nodes_alive", nodes_alive))
    if "ndd_nodes_created" not in parts and "bdd_nodes_created" not in parts:
        ndd_nodes_created = 0
        bdd_nodes_created = nodes_created
    if "ndd_nodes_alive" not in parts and "bdd_nodes_alive" not in parts:
        ndd_nodes_alive = 0
        bdd_nodes_alive = nodes_alive
    seconds = float(parts["seconds"]) if "seconds" in parts else None
    return {
        "size": size,
        "solutions": solutions,
        "nodes_created": nodes_created,
        "nodes_alive": nodes_alive,
        "ndd_nodes_created": ndd_nodes_created,
        "ndd_nodes_alive": ndd_nodes_alive,
        "bdd_nodes_created": bdd_nodes_created,
        "bdd_nodes_alive": bdd_nodes_alive,
        "seconds": seconds,
    }


def run_implementation(impl, size, workers, timeout_sec=DEFAULT_TIMEOUT_SEC):
    cmd = impl.command_for(size, workers)
    env = impl.base_env()
    result = execute_with_metrics(cmd, cwd=impl.workdir, env=env, timeout_sec=timeout_sec)
    if result["timed_out"]:
        print(f"[timeout] {impl.name:10s} N={size:2d} time={timeout_sec:7.3f}s rss={result['max_rss']:>8d}KB")
        return {
            "implementation": impl.name,
            "language": impl.language,
            "size": size,
            "time_sec": timeout_sec,
            "max_rss_kb": result["max_rss"],
            "nodes_created": TIMEOUT_SENTINEL_METRICS["nodes_created"],
            "nodes_alive": TIMEOUT_SENTINEL_METRICS["nodes_alive"],
            "ndd_nodes_created": TIMEOUT_SENTINEL_METRICS["ndd_nodes_created"],
            "ndd_nodes_alive": TIMEOUT_SENTINEL_METRICS["ndd_nodes_alive"],
            "bdd_nodes_created": TIMEOUT_SENTINEL_METRICS["bdd_nodes_created"],
            "bdd_nodes_alive": TIMEOUT_SENTINEL_METRICS["bdd_nodes_alive"],
            "solutions": TIMEOUT_SENTINEL_METRICS["solutions"],
        }
    if result["returncode"] != 0:
        raise subprocess.CalledProcessError(
            result["returncode"],
            result["cmd"],
            output=result["stdout"],
            stderr=result["stderr"],
        )
    metrics = parse_metrics(result["stdout"])
    if metrics["size"] != size:
        raise RuntimeError(f"Implementation {impl.name} reported size {metrics['size']} but expected {size}")
    time_sec = metrics["seconds"] if metrics["seconds"] is not None else result["elapsed"]
    max_rss = result["max_rss"]
    print(f"[run] {impl.name:10s} N={size:2d} time={time_sec:7.3f}s rss={max_rss:>8d}KB "
          f"created={metrics['nodes_created']} alive={metrics['nodes_alive']} "
          f"(bdd={metrics['bdd_nodes_created']}/{metrics['bdd_nodes_alive']} "
          f"ndd={metrics['ndd_nodes_created']}/{metrics['ndd_nodes_alive']})")
    return {
        "implementation": impl.name,
        "language": impl.language,
        "size": size,
        "time_sec": time_sec,
        "max_rss_kb": max_rss,
        "nodes_created": metrics["nodes_created"],
        "nodes_alive": metrics["nodes_alive"],
        "ndd_nodes_created": metrics["ndd_nodes_created"],
        "ndd_nodes_alive": metrics["ndd_nodes_alive"],
        "bdd_nodes_created": metrics["bdd_nodes_created"],
        "bdd_nodes_alive": metrics["bdd_nodes_alive"],
        "solutions": metrics["solutions"],
    }


def write_results(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "implementation",
        "language",
        "size",
        "time_sec",
        "max_rss_kb",
        "nodes_created",
        "nodes_alive",
        "ndd_nodes_created",
        "ndd_nodes_alive",
        "bdd_nodes_created",
        "bdd_nodes_alive",
        "solutions",
    ]
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


def plot_results(output_path):
    plot_script = ROOT / "scripts" / "plot_nqueens_results.py"
    print(f"[plot] Generating plots from {output_path}")
    subprocess.run(
        [
            "python3",
            str(plot_script),
            "--input",
            str(output_path),
            "--output",
            str(output_path.parent),
        ],
        cwd=ROOT,
        check=True,
    )


def parse_args():
    default_targets = get_default_targets()
    parser = argparse.ArgumentParser(description="Run N-Queens benchmarks across multiple BDD implementations.")
    parser.add_argument(
        "--sizes",
        nargs="+",
        type=int,
        default=DEFAULT_SIZES,
        help="Board sizes to benchmark (default: 8 9 10 11 12)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Worker threads for Sylvan-based implementations (0 = autodetect, default: 0)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SEC,
        help="Per-run timeout in seconds (default: 500)",
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
        default=default_targets,
        help=f"Which implementations to run (default: {' '.join(default_targets)}). Example: --targets BuDDy Sylvan JSylvan",
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
            "ZDD",
            "Java",
            ensure_jdd,
            lambda size, _: [
                "java",
                "-cp", "build/classes/java/main",
                "jdd.examples.ZDDQueens",
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
                "--memory-mb", str(JSYLVAN_MEMORY_MB),
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
            "NDD-reuse",
            "Java",
            ensure_ndd_reuse,
            lambda size, _: [
                "java",
                "-cp", str(ROOT / "NDD-reuse" / "target" / "ndd-1.0.1-jar-with-dependencies.jar"),
                "application.nqueen.NDDSolution",
                str(size),
            ],
            workdir=ROOT / "NDD-reuse",
        ),
        Implementation(
            "NDD-SoA",
            "Java",                        
            ensure_ndd_soa,             
            lambda size, _: [
                "java",
                "-cp", str(ROOT / "NDD-SoA" / "target" / "ndd-1.0.1-jar-with-dependencies.jar"), 
                "application.nqueen.NDDSolution", 
                str(size),
            ],
            workdir=ROOT / "NDD-SoA",
        ),
        Implementation(
            "NDD-SoA-BCDD",
            "Java",
            ensure_ndd_soa,
            lambda size, _: [
                "java",
                "-cp", str(ROOT / "NDD-SoA" / "target" / "ndd-1.0.1-jar-with-dependencies.jar"),
                "application.nqueen.ComplementedBddNDDSolution",
                str(size),
            ],
            workdir=ROOT / "NDD-SoA",
        ),
        Implementation(
            "NDD-SoA-FD-ZDD",
            "Java",
            ensure_ndd_soa,
            lambda size, _: [
                "java",
                "-cp", str(ROOT / "NDD-SoA" / "target" / "ndd-1.0.1-jar-with-dependencies.jar"),
                "application.nqueen.FiniteDomainZddNDDSolution",
                str(size),
            ],
            workdir=ROOT / "NDD-SoA",
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


def get_default_targets():
    return [impl.name for impl in build_implementations() if impl.name not in EXCLUDED_DEFAULT_TARGETS]


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
            rows.append(run_implementation(impl, size, args.workers, timeout_sec=args.timeout))

    write_results(rows, args.output)
    plot_results(args.output)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"[error] Command failed with exit code {exc.returncode}: {' '.join(exc.cmd)}", file=sys.stderr)
        sys.exit(exc.returncode)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
