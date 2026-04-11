# BCDD-backed NDD-SoA Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a complemented-edge BDD label mode to `NDD-SoA`, integrate it with the N-Queens benchmark entrypoint, and compare it against the current BDD-backed `NDD-SoA`.

**Architecture:** Keep the existing `BOOLEAN_BDD` and finite-domain ZDD paths intact. Add a local complement-aware BDD manager inside `NDD-SoA` that supports the subset of Boolean-DD operations required by the current `NDD` edge-label algorithms. Wire a new `LabelMode` and a dedicated N-Queens main class to benchmark the new mode without destabilizing existing paths.

**Tech Stack:** Java 8, Maven, `NDD-SoA`, local complement-aware BDD manager, Python benchmark harness, JUnit 4

### Task 1: Pin The Expected External Behavior

**Files:**
- Modify: `NDD-SoA/src/test/java/org/ants/jndd/diagram/NDDLabelModeTest.java`
- Modify: `NDD-SoA/src/test/java/application/nqueen/NDDSolutionTest.java`
- Modify: `tests/test_run_nqueens_benchmarks.py`

**Step 1: Add a failing BCDD label-mode test**

Cover:
- `getVar` and `getNotVar` remain complementary in the new mode
- `satCount` on a literal, its complement, and unions/intersections matches Boolean expectations

**Step 2: Add a failing N-Queens entrypoint test**

Cover:
- new main class prints `NQUEENS_METRICS`
- output identifies the BCDD implementation

**Step 3: Add a failing benchmark-script registration test**

Cover:
- `DEFAULT_TARGETS` includes the BCDD variant
- `build_implementations()` registers the new Java command

### Task 2: Add A Local Complement-aware BDD Manager

**Files:**
- Create: `NDD-SoA/src/main/java/org/ants/jndd/bdd/ComplementedBDD.java`

**Step 1: Implement complemented-handle encoding**

Support:
- `false = 0`, `true = 1`
- internal handles encode a regular node id plus one complement bit

**Step 2: Implement the minimal manager API**

Methods:
- `createVar`, `ref`, `deref`
- `not`, `and`, `or`, `imp`
- `andTo`, `orTo`
- `satCount`
- `mk`, `getVar`, `getLow`, `getHigh`

**Step 3: Add apply caches**

Cache:
- complemented-handle-aware `and` / `or`
- sat-count memoization

### Task 3: Wire BCDD Into NDD

**Files:**
- Modify: `NDD-SoA/src/main/java/org/ants/jndd/diagram/NDD.java`

**Step 1: Add a new label mode**

Add:
- `COMPLEMENTED_BDD`

**Step 2: Route label operations through the new manager**

Update:
- `generateFields`
- `refLabel` / `derefLabel`
- `labelAnd`, `labelDiff`, `labelNot`, `labelOrTo`, `labelAndTo`, `labelSatCount`
- field-cardinality logic if needed

**Step 3: Keep unsupported conversions explicit**

For the first cut:
- keep `toBDD`, `toNDD`, `encodePrefix`, `encodeACL`, and `DecomposeBDD` restricted to the original `BOOLEAN_BDD` mode if they are not required by the benchmark path

### Task 4: Add The N-Queens Entry Point

**Files:**
- Create: `NDD-SoA/src/main/java/application/nqueen/ComplementedBddNDDSolution.java`
- Modify: `NDD-SoA/src/main/java/application/nqueen/NDDSolution.java`

**Step 1: Expose the new mode**

Either:
- add a dedicated main class, or
- add a CLI flag and keep a dedicated wrapper class for the benchmark harness

**Step 2: Emit benchmark-friendly metrics**

Output:
- `NQUEENS_METRICS`
- explicit implementation/mode tag

### Task 5: Integrate The Benchmark Harness

**Files:**
- Modify: `scripts/run_nqueens_benchmarks.py`

**Step 1: Register the new target**

Add:
- default target name, recommended: `NDD-SoA-BCDD`

**Step 2: Reuse the existing `NDD-SoA` build step**

The implementation should:
- build from the same Maven artifact
- run a dedicated Java main class

### Task 6: Verify And Measure

**Files:**
- Modify: `progress.md`
- Modify: `findings.md`

**Step 1: Run tests**

Run:
- Python benchmark-script tests
- Maven tests under `NDD-SoA`

**Step 2: Run benchmarks**

Compare at least:
- `NDD-SoA`
- `NDD-SoA-BCDD`

Collect:
- `time_sec`
- `max_rss_kb`
- `nodes_created`
- `nodes_alive`
- `solutions`

**Step 3: Record results**

Document:
- whether BCDD improved performance
- where it regressed
- whether the result is stable or mixed
