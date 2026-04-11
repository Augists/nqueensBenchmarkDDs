# NDD ZDD Edge Labels Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Evaluate and, if desired, implement a safe path toward using ZDDs inside NDD without breaking current Boolean semantics.

**Architecture:** The current NDD design treats each edge label as a Boolean function over the bits of one field. That representation is tightly coupled to JDD's BDD semantics, including complement, sat-count over assignments, and structural traversal. A direct swap to JDD's ZDD manager is therefore unsafe. The recommended architecture is to keep the existing BDD-backed NDD unchanged and add an alternative ZDD-backed edge-label mode only for workloads where each edge label denotes a sparse family of explicit value assignments for that field.

**Tech Stack:** Java, NDD-SoA/NDD-reuse, JDD `jdd.bdd.BDD`, JDD `jdd.zdd.ZDD`.

### Task 1: Freeze The Current Semantic Contract

**Files:**
- Modify: `NDD-SoA/src/main/java/org/ants/jndd/diagram/NDD.java`
- Modify: `NDD-SoA/src/main/java/org/ants/jndd/utils/DecomposeBDD.java`
- Modify: `NDD-reuse/src/main/java/org/ants/jndd/diagram/NDD.java`
- Test: `NDD-SoA/src/test/...` or equivalent new tests

**Step 1: Write tests that pin current meaning of edge labels**

Cover:
- edge labels denote all field assignments routed to a given child
- `or`, `and`, `not`, `diff`, `imp` preserve `toBDD` equivalence
- `satCount` matches `toBDD`
- `toNDD(toBDD(x))` round-trips for representative inputs

**Step 2: Run tests to confirm the baseline**

Expected:
- current BDD-backed implementation passes

**Step 3: Add explicit comments/documentation**

Document:
- edge labels are Boolean functions, not just sparse set families
- current algorithms assume Boolean complement and assignment counting

**Step 4: Run tests again**

Expected:
- no behavior changes

### Task 2: Introduce An Edge-Label Abstraction

**Files:**
- Create: `NDD-SoA/src/main/java/org/ants/jndd/diagram/EdgeLabelManager.java`
- Modify: `NDD-SoA/src/main/java/org/ants/jndd/diagram/NDD.java`
- Modify: `NDD-SoA/src/main/java/org/ants/jndd/nodetable/NodeTable.java`

**Step 1: Define the smallest useful interface**

Methods should include:
- `zero()`, `one()`
- `ref(int)`, `deref(int)`
- `or(int,int)`, `and(int,int)`, `not(int)`
- `mkVar(int localVarIndex, boolean positive)`
- `satAssignments(int label, int fieldBits)`
- `isOne(int)`, `isZero(int)`

**Step 2: Implement `BddEdgeLabelManager`**

Back it with the current `jdd.bdd.BDD` engine.

**Step 3: Wire NDD to the abstraction**

Replace direct `bddEngine` edge-label calls inside NDD hot paths with the abstraction, but keep `toBDD`/`toNDD` and decomposition on the BDD manager only for now.

**Step 4: Run equivalence tests**

Expected:
- behavior identical to baseline

### Task 3: Decide The ZDD Semantics Before Coding

**Files:**
- Modify: `docs/plans/2026-04-10-ndd-zdd-edge-label-design.md`

**Step 1: Choose one of two meanings**

Option A:
- edge label ZDD encodes the set of concrete field values routed to the child

Option B:
- edge label ZDD encodes the set of satisfying cubes/minterms for the field

Recommendation:
- use Option A when field domains are sparse and enumerably representable

**Step 2: Reject unsupported cases explicitly**

Do not support:
- arbitrary large dense prefixes without expansion strategy
- operations that require cheap universal complement over the full field universe unless you add an explicit universe ZDD

### Task 4: Add A Prototype ZDD Label Manager

**Files:**
- Create: `NDD-SoA/src/main/java/org/ants/jndd/diagram/ZddEdgeLabelManager.java`
- Create: `NDD-SoA/src/main/java/org/ants/jndd/diagram/FieldUniverse.java`
- Test: new unit tests for set-family semantics

**Step 1: Represent each field value as a cube**

For a field with `k` bits:
- create a ZDD variable for each bit-position/value convention
- define how a concrete integer value maps to one ZDD set element or one cube

**Step 2: Implement set-family operations**

Map:
- NDD edge overlap to ZDD `intersect`
- edge union to ZDD `union`
- edge subtraction to ZDD `diff`

**Step 3: Implement explicit complement against field universe**

Since JDD ZDD lacks Boolean-function `not`, define:
- `complement(label) = universe(field) - label`

This must be field-local and cached.

**Step 4: Implement assignment counting**

Use ZDD set counting semantics, not BDD `satCount`.

### Task 5: Fork NDD Operations For ZDD Mode

**Files:**
- Modify: `NDD-SoA/src/main/java/org/ants/jndd/diagram/NDD.java`
- Test: operation equivalence and negative tests

**Step 1: Keep BDD mode unchanged**

Do not try to make BDD and ZDD share every internal helper if their semantics diverge.

**Step 2: Add separate logic where Boolean complement was assumed**

Hot spots:
- `orRec`
- `notRec`
- `satCountRec`
- `encodePrefix` and ACL encoding
- `toBDD` / `toNDD`

**Step 3: Disable unsupported conversions in ZDD mode**

If edge labels are no longer Boolean functions, `toBDD` and `DecomposeBDD` cannot stay generic. Throw or route through an explicit value-expansion conversion.

### Task 6: Restrict Initial Scope

**Files:**
- Modify: benchmark or app entrypoints that construct NDD predicates
- Test: focused benchmarks

**Step 1: Start with workloads that already enumerate discrete values**

Good first targets:
- N-Queens style exact-position constraints
- AP sets already represented as explicit atoms

**Step 2: Exclude dense prefix/range workloads initially**

These often favor BDDs and can make ZDD encoding explode.

### Task 7: Benchmark And Compare

**Files:**
- Modify: benchmark harness
- Test: repeatable benchmark script/results

**Step 1: Measure both internal and end-to-end metrics**

Capture:
- time
- total created nodes
- live nodes
- memory
- edge-label node counts

**Step 2: Compare by workload type**

Expect:
- sparse explicit-set workloads may improve with ZDD
- dense symbolic predicate workloads may regress

### Task 8: Decide On Product Shape

**Files:**
- Modify: docs/README as needed

**Step 1: Keep dual mode unless evidence is overwhelming**

Recommendation:
- preserve BDD-backed NDD as default
- expose ZDD-backed NDD as an opt-in experimental mode

**Step 2: Document the selection rule**

Use ZDD-backed edges only when edge labels are sparse set families over a bounded field universe.
