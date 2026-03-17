/**
 * NDD (Node Decision Diagram) main API.
 * Provides initialization, field declaration, Boolean operations (and, or, not, diff, imp),
 * encoding (prefix, ACL), and conversion between NDD and BDD.
 *
 * @author Zechun Li & Yichi Zhang - XJTU ANTS NetVerify Lab
 * @version 1.0
 */
package org.ants.jndd.diagram;

import jdd.bdd.BDD;
import org.ants.jndd.nodetable.NodeTable;
import org.ants.jndd.utils.DecomposeBDD;

import java.io.FileWriter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;
import java.util.function.IntConsumer;

public class NDD {
    /**
     * Size of operation caches (not, and, or).
     */
    private static int CACHE_SIZE = 10000;

    /**
     * The node table (node storage and unique table).
     */
    private static NodeTable nodeTable;

    /**
     * The internal BDD engine (shared with node table).
     */
    protected static BDD bddEngine;

    /**
     * Current number of declared fields (0-based).
     */
    protected static int fieldNum;

    /**
     * Per-field max variable index (cumulative bit index for BDD decomposition).
     */
    private static ArrayList<Integer> maxVariablePerField;

    /**
     * Per-field divisor for sat count normalization.
     */
    private static ArrayList<Double> satCountDiv;

    /**
     * BDD variable handles per field (for encoding).
     */
    private static ArrayList<int[]> bddVarsPerField;

    /**
     * BDD negated variable handles per field.
     */
    private static ArrayList<int[]> bddNotVarsPerField;

    /**
     * NDD node ids for positive literal per field per bit.
     */
    private static ArrayList<int[]> nddVarsPerField;

    /**
     * NDD node ids for negative literal per field per bit.
     */
    private static ArrayList<int[]> nddNotVarsPerField;

    /**
     * Node ids temporarily protected during an operation (e.g. and/or/not), to avoid gc.
     */
    private static IntHashSet temporarilyProtect;

    /**
     * Cache for not operation results.
     */
    private static IntOperationCache notCache;

    /**
     * Cache for and operation results.
     */
    private static IntOperationCache andCache;

    /**
     * Cache for or operation results.
     */
    private static IntOperationCache orCache;

    /**
     * Initial capacity of edge-collection stack.
     */
    private static final int INITIAL_STACK_SIZE = 100000;

    /**
     * Stack of edge targets during edge collection.
     */
    private static int[] stackTargets;

    /**
     * Stack of edge labels (BDD handles) during edge collection.
     */
    private static int[] stackLabels;

    /**
     * Top of the edge stack (next free index).
     */
    private static int stackTop;

    /**
     * Terminal node id for TRUE.
     */
    private static final int TRUE = 1;

    /**
     * Terminal node id for FALSE.
     */
    private static final int FALSE = 0;

    /**
     * Initialize NDD with default cache size.
     *
     * @param nddTableSize Max NDD node table size.
     * @param bddTableSize BDD node table size.
     * @param bddCacheSize BDD cache size.
     */
    public static void initNDD(int nddTableSize, int bddTableSize, int bddCacheSize) {
        initNDD(nddTableSize, CACHE_SIZE, bddTableSize, bddCacheSize);
    }

    /**
     * Initialize NDD engine: node table, BDD engine, caches, and per-field arrays.
     *
     * @param nddTableSize  Max NDD node table size.
     * @param nddCacheSize  Size of not/and/or caches.
     * @param bddTableSize BDD node table size.
     * @param bddCacheSize BDD cache size.
     */
    public static void initNDD(int nddTableSize, int nddCacheSize, int bddTableSize, int bddCacheSize) {
        CACHE_SIZE = nddCacheSize;
        nodeTable = new NodeTable(nddTableSize, bddTableSize, bddCacheSize);
        bddEngine = nodeTable.getBddEngine();

        fieldNum = -1;
        maxVariablePerField = new ArrayList<>();
        satCountDiv = new ArrayList<>();

        bddVarsPerField = new ArrayList<>();
        bddNotVarsPerField = new ArrayList<>();
        nddVarsPerField = new ArrayList<>();
        nddNotVarsPerField = new ArrayList<>();

        temporarilyProtect = new IntHashSet(1024);
        notCache = new IntOperationCache(CACHE_SIZE);
        andCache = new IntOperationCache(CACHE_SIZE);
        orCache = new IntOperationCache(CACHE_SIZE);

        stackTargets = new int[INITIAL_STACK_SIZE];
        stackLabels = new int[INITIAL_STACK_SIZE];
        stackTop = 0;
    }

    /**
     * Declare a new field with the given number of bits; creates BDD/NDD variables and unique table.
     *
     * @param bitNum Number of bits in this field.
     * @return The field index (0-based).
     */
    public static int declareField(int bitNum) {
        fieldNum++;
        if (maxVariablePerField.isEmpty()) {
            maxVariablePerField.add(bitNum - 1);
        } else {
            maxVariablePerField.add(maxVariablePerField.get(maxVariablePerField.size() - 1) + bitNum);
        }

        double factor = Math.pow(2.0, bitNum);
        for (int i = 0; i < satCountDiv.size(); i++) {
            satCountDiv.set(i, satCountDiv.get(i) * factor);
        }
        int totalBitsBefore = 0;
        if (maxVariablePerField.size() > 1) {
            totalBitsBefore = maxVariablePerField.get(maxVariablePerField.size() - 2) + 1;
        }
        satCountDiv.add(Math.pow(2.0, totalBitsBefore));

        nodeTable.declareField();

        int[] bddVars = new int[bitNum];
        int[] bddNotVars = new int[bitNum];
        int[] nddVars = new int[bitNum];
        int[] nddNotVars = new int[bitNum];

        for (int i = 0; i < bitNum; i++) {
            bddVars[i] = bddEngine.ref(bddEngine.createVar());
            bddNotVars[i] = bddEngine.ref(bddEngine.not(bddVars[i]));

            nddVars[i] = nodeTable.mk(fieldNum, new int[]{TRUE}, new int[]{bddEngine.ref(bddVars[i])});
            nodeTable.fixNDDNodeRefCount(nddVars[i]);

            nddNotVars[i] = nodeTable.mk(fieldNum, new int[]{TRUE}, new int[]{bddEngine.ref(bddNotVars[i])});
            nodeTable.fixNDDNodeRefCount(nddNotVars[i]);
        }

        bddVarsPerField.add(bddVars);
        bddNotVarsPerField.add(bddNotVars);
        nddVarsPerField.add(nddVars);
        nddNotVarsPerField.add(nddNotVars);

        return fieldNum;
    }

    /** @return Terminal node id for TRUE. */
    public static int getTrue() { return TRUE; }
    /** @return Terminal node id for FALSE. */
    public static int getFalse() { return FALSE; }
    /** @return Whether the node is TRUE. */
    public static boolean isTrue(int node) { return node == TRUE; }
    /** @return Whether the node is FALSE. */
    public static boolean isFalse(int node) { return node == FALSE; }
    /** @return Whether the node is a terminal (TRUE or FALSE). */
    public static boolean isTerminal(int node) { return node <= 1; }

    /** @return Number of declared fields. */
    public static int getFieldNum() { return fieldNum; }

    /** @return NDD node id for positive literal at (field, index). */
    public static int getVar(int field, int index) { return nddVarsPerField.get(field)[index]; }
    /** @return NDD node id for negative literal at (field, index). */
    public static int getNotVar(int field, int index) { return nddNotVarsPerField.get(field)[index]; }
    /** @return BDD variable handles for the field. */
    public static int[] getBDDVars(int field) { return bddVarsPerField.get(field); }
    /** @return BDD negated variable handles for the field. */
    public static int[] getNotBDDVars(int field) { return bddNotVarsPerField.get(field); }

    /** @return The internal BDD engine. */
    public static BDD getBDDEngine() { return bddEngine; }

    /**
     * Clear not/and/or operation caches (e.g. after gc).
     */
    public static void clearCaches() {
        notCache.clear();
        andCache.clear();
        orCache.clear();
    }

    /**
     * Apply consumer to each node id in the temporary protect set (used during gc).
     *
     * @param consumer Action to perform for each protected node id.
     */
    public static void forEachTemporarilyProtect(IntConsumer consumer) {
        temporarilyProtect.forEach(consumer);
    }

    /**
     * Increment reference count of a node (protect from gc).
     *
     * @param nodeId The node id.
     * @return The same node id.
     */
    public static int ref(int nodeId) { return nodeTable.ref(nodeId); }

    /**
     * Decrement reference count of a node.
     *
     * @param nodeId The node id.
     */
    public static void deref(int nodeId) { nodeTable.deref(nodeId); }

    /**
     * Collect one edge (target, label) into the stack; merge with same target by OR-ing labels.
     *
     * @param frameStart Start of current frame in stack.
     * @param target     Target node id.
     * @param label      BDD handle for edge label (caller ref'd).
     */
    private static void edgeCollect(int frameStart, int target, int label) {
        if (target == FALSE) {
            bddEngine.deref(label);
            return;
        }

        for (int i = frameStart; i < stackTop; i++) {
            if (stackTargets[i] == target) {
                int oldLabel = stackLabels[i];
                stackLabels[i] = bddEngine.orTo(oldLabel, label);
                bddEngine.deref(label);
                return;
            }
        }

        if (stackTop >= stackTargets.length) growStack();
        stackTargets[stackTop] = target;
        stackLabels[stackTop] = label;
        stackTop++;
    }

    /**
     * Flush collected edges: sort by target, then create/reuse node via nodeTable.mk.
     *
     * @param frameStart Start of current frame in stack.
     * @param field      Field index for the new node.
     * @return The created or reused node id, or FALSE if no edges.
     */
    private static int edgeFlush(int frameStart, int field) {
        int size = stackTop - frameStart;

        if (size == 0) {
            stackTop = frameStart;
            return FALSE;
        }

        for (int i = frameStart + 1; i < stackTop; i++) {
            int t = stackTargets[i];
            int l = stackLabels[i];
            int j = i - 1;
            while (j >= frameStart && stackTargets[j] > t) {
                stackTargets[j + 1] = stackTargets[j];
                stackLabels[j + 1] = stackLabels[j];
                j--;
            }
            stackTargets[j + 1] = t;
            stackLabels[j + 1] = l;
        }

        int res = nodeTable.mk(field, stackTargets, stackLabels, frameStart, size);

        stackTop = frameStart;
        return res;
    }

    /**
     * Double the capacity of the edge stack.
     */
    private static void growStack() {
        int newCap = stackTargets.length * 2;
        stackTargets = Arrays.copyOf(stackTargets, newCap);
        stackLabels = Arrays.copyOf(stackLabels, newCap);
    }

    /**
     * Create or reuse an NDD node with the given edges (target -> label map).
     *
     * @param field Field index.
     * @param edges Map from target node id to BDD label handle.
     * @return The node id.
     */
    public static int mk(int field, IntIntMap edges) {
        int frameStart = stackTop;
        edges.forEach((target, label) -> {
            edgeCollect(frameStart, target, bddEngine.ref(label));
        });
        return edgeFlush(frameStart, field);
    }

    /**
     * And two NDDs, store result in a (ref result, deref a).
     *
     * @param a First operand (consumed).
     * @param b Second operand.
     * @return The result node id (ref'd).
     */
    public static int andTo(int a, int b) {
        int result = ref(and(a, b));
        deref(a);
        return result;
    }

    /**
     * Or two NDDs, store result in a (ref result, deref a).
     *
     * @param a First operand (consumed).
     * @param b Second operand.
     * @return The result node id (ref'd).
     */
    public static int orTo(int a, int b) {
        int result = ref(or(a, b));
        deref(a);
        return result;
    }

    /**
     * Logical and of two NDDs (result not ref'd).
     *
     * @param a First operand.
     * @param b Second operand.
     * @return The and result node id.
     */
    public static int and(int a, int b) {
        temporarilyProtect.clear();
        return andRec(a, b);
    }

    /**
     * Recursive and: same-field nodes combine edges by BDD and on labels; different fields take earlier field.
     */
    private static int andRec(int a, int b) {
        if (isFalse(a) || isTrue(b)) return a;
        if (isTrue(a) || isFalse(b) || a == b) return b;

        if (andCache.getEntry(a, b)) return andCache.result;

        int frameStart = stackTop;

        int aField = nodeTable.getField(a);
        int bField = nodeTable.getField(b);
        if (aField == bField) {
            int aStart = nodeTable.getEdgeStart(a);
            int aCount = nodeTable.getEdgeCount(a);
            int bStart = nodeTable.getEdgeStart(b);
            int bCount = nodeTable.getEdgeCount(b);
            for (int i = 0; i < aCount; i++) {
                int aTarget = nodeTable.getEdgeTarget(aStart + i);
                int aLabel = nodeTable.getEdgeLabel(aStart + i);
                for (int j = 0; j < bCount; j++) {
                    int bTarget = nodeTable.getEdgeTarget(bStart + j);
                    int bLabel = nodeTable.getEdgeLabel(bStart + j);
                    int intersect = bddEngine.ref(bddEngine.and(aLabel, bLabel));
                    if (intersect != 0) {
                        int sub = andRec(aTarget, bTarget);
                        edgeCollect(frameStart, sub, intersect);
                    }
                }
            }
        } else {
            if (aField > bField) {
                int t = a; a = b; b = t;
                int tf = aField; aField = bField; bField = tf;
            }
            int aStart = nodeTable.getEdgeStart(a);
            int aCount = nodeTable.getEdgeCount(a);
            for (int i = 0; i < aCount; i++) {
                int aTarget = nodeTable.getEdgeTarget(aStart + i);
                int aLabel = nodeTable.getEdgeLabel(aStart + i);
                int sub = andRec(aTarget, b);
                edgeCollect(frameStart, sub, bddEngine.ref(aLabel));
            }
        }

        int res = edgeFlush(frameStart, aField);
        temporarilyProtect.add(res);
        andCache.setEntry(andCache.hashValue, a, b, res);
        return res;
    }

    /**
     * Logical or of two NDDs (result not ref'd).
     *
     * @param a First operand.
     * @param b Second operand.
     * @return The or result node id.
     */
    public static int or(int a, int b) {
        temporarilyProtect.clear();
        return orRec(a, b);
    }

    /**
     * Recursive or: same-field nodes merge edges and subtract overlaps; different fields take earlier field.
     */
    private static int orRec(int a, int b) {
        if (isTrue(a) || isFalse(b)) return a;
        if (isFalse(a) || isTrue(b) || a == b) return b;

        if (orCache.getEntry(a, b)) return orCache.result;

        int frameStart = stackTop;
        int aField = nodeTable.getField(a);
        int bField = nodeTable.getField(b);

        if (aField == bField) {
            int aStart = nodeTable.getEdgeStart(a);
            int aCount = nodeTable.getEdgeCount(a);
            int bStart = nodeTable.getEdgeStart(b);
            int bCount = nodeTable.getEdgeCount(b);

            IntIntMap resA = new IntIntMap(aCount);
            IntIntMap resB = new IntIntMap(bCount);

            for (int i = 0; i < aCount; i++) {
                int target = nodeTable.getEdgeTarget(aStart + i);
                int label = nodeTable.getEdgeLabel(aStart + i);
                resA.put(target, bddEngine.ref(label));
            }
            for (int i = 0; i < bCount; i++) {
                int target = nodeTable.getEdgeTarget(bStart + i);
                int label = nodeTable.getEdgeLabel(bStart + i);
                resB.put(target, bddEngine.ref(label));
            }

            for (int i = 0; i < aCount; i++) {
                int aTarget = nodeTable.getEdgeTarget(aStart + i);
                int aLabel = nodeTable.getEdgeLabel(aStart + i);
                for (int j = 0; j < bCount; j++) {
                    int bTarget = nodeTable.getEdgeTarget(bStart + j);
                    int bLabel = nodeTable.getEdgeLabel(bStart + j);
                    int intersect = bddEngine.ref(bddEngine.and(aLabel, bLabel));
                    if (intersect != 0) {
                        int notIntersect = bddEngine.ref(bddEngine.not(intersect));
                        int ra = resA.get(aTarget);
                        resA.put(aTarget, bddEngine.andTo(ra, notIntersect));
                        int rb = resB.get(bTarget);
                        resB.put(bTarget, bddEngine.andTo(rb, notIntersect));
                        bddEngine.deref(notIntersect);
                        int sub = orRec(aTarget, bTarget);
                        edgeCollect(frameStart, sub, intersect);
                    }
                }
            }

            resA.forEach((key, value) -> {
                if (value != 0) edgeCollect(frameStart, key, bddEngine.ref(value));
                bddEngine.deref(value);
            });
            resB.forEach((key, value) -> {
                if (value != 0) edgeCollect(frameStart, key, bddEngine.ref(value));
                bddEngine.deref(value);
            });
        } else {
            if (aField > bField) {
                int t = a; a = b; b = t;
                int tf = aField; aField = bField; bField = tf;
            }
            int residualB = 1;
            int aStart = nodeTable.getEdgeStart(a);
            int aCount = nodeTable.getEdgeCount(a);
            for (int i = 0; i < aCount; i++) {
                int aTarget = nodeTable.getEdgeTarget(aStart + i);
                int aLabel = nodeTable.getEdgeLabel(aStart + i);
                int notInt = bddEngine.ref(bddEngine.not(aLabel));
                residualB = bddEngine.andTo(residualB, notInt);
                bddEngine.deref(notInt);

                int sub = orRec(aTarget, b);
                edgeCollect(frameStart, sub, bddEngine.ref(aLabel));
            }
            if (residualB != 0) edgeCollect(frameStart, b, residualB);
        }

        int res = edgeFlush(frameStart, aField);
        temporarilyProtect.add(res);
        orCache.setEntry(orCache.hashValue, a, b, res);
        return res;
    }

    /**
     * Logical not of an NDD (result not ref'd).
     *
     * @param a Operand.
     * @return The not result node id.
     */
    public static int not(int a) {
        temporarilyProtect.clear();
        return notRec(a);
    }

    /**
     * Recursive not: complement each edge label and add residual to TRUE.
     */
    private static int notRec(int a) {
        if (isTrue(a)) return FALSE;
        if (isFalse(a)) return TRUE;

        if (notCache.getEntry(a)) return notCache.result;

        int frameStart = stackTop;
        int residual = 1;

        int aStart = nodeTable.getEdgeStart(a);
        int aCount = nodeTable.getEdgeCount(a);
        for (int i = 0; i < aCount; i++) {
            int aTarget = nodeTable.getEdgeTarget(aStart + i);
            int aLabel = nodeTable.getEdgeLabel(aStart + i);
            int notIntersect = bddEngine.ref(bddEngine.not(aLabel));
            residual = bddEngine.andTo(residual, notIntersect);
            bddEngine.deref(notIntersect);

            int sub = notRec(aTarget);
            edgeCollect(frameStart, sub, bddEngine.ref(aLabel));
        }

        if (residual != 0) edgeCollect(frameStart, TRUE, residual);

        int result = edgeFlush(frameStart, nodeTable.getField(a));
        temporarilyProtect.add(result);
        notCache.setEntry(notCache.hashValue, a, result);
        return result;
    }

    /**
     * Set difference: a and not(b).
     *
     * @param a First operand.
     * @param b Second operand.
     * @return The result node id.
     */
    public static int diff(int a, int b) {
        temporarilyProtect.clear();
        int n = notRec(b);
        temporarilyProtect.add(n);
        return andRec(a, n);
    }

    /**
     * Implication: not(a) or b.
     *
     * @param a First operand.
     * @param b Second operand.
     * @return The result node id.
     */
    public static int imp(int a, int b) {
        temporarilyProtect.clear();
        int n = notRec(a);
        temporarilyProtect.add(n);
        return orRec(n, b);
    }

    /**
     * Number of satisfying assignments of the NDD (via conversion to BDD).
     *
     * @param ndd Root node id.
     * @return Sat count.
     */
    public static double satCount(int ndd) {
        return bddEngine.satCount(toBDD(ndd));
    }

    /**
     * Get the current number of allocated NDD nodes.
     * @return Node count stored in the node table.
     */
    public static long getNodeCount() {
        if (nodeTable == null) {
            return 0;
        }
        return nodeTable.getCurrentSize();
    }

    /**
     * Run NDD garbage collection immediately.
     */
    public static void gc() {
        if (nodeTable != null) {
            nodeTable.gc();
            clearCaches();
        }
    }

    /**
     * Get the total number of NDD nodes ever created.
     * @return Total created count (including garbage collected nodes).
     */
    public static long getTotalCreated() {
        if (nodeTable == null) {
            return 0;
        }
        return nodeTable.getTotalCreated();
    }

    /**
     * Encode a single binary prefix as an NDD (one node with one edge labeled by BDD).
     *
     * @param prefixBinary Binary prefix (e.g. for IP).
     * @param field        Field index.
     * @return NDD node id.
     */
    public static int encodePrefix(int[] prefixBinary, int field) {
        if (prefixBinary.length == 0) return TRUE;
        int prefixBDD = encodePrefixBDD(prefixBinary, getBDDVars(field), getNotBDDVars(field));
        return nodeTable.mk(field, new int[]{TRUE}, new int[]{prefixBDD});
    }

    /**
     * Encode multiple binary prefixes as union (or) of prefix NDDs.
     *
     * @param prefixsBinary List of binary prefixes.
     * @param field         Field index.
     * @return NDD node id.
     */
    public static int encodePrefixs(ArrayList<int[]> prefixsBinary, int field) {
        int prefixsBDD = 0;
        for (int[] prefix : prefixsBinary) {
            prefixsBDD = bddEngine.orTo(prefixsBDD, encodePrefixBDD(prefix, getBDDVars(field), getNotBDDVars(field)));
        }
        return nodeTable.mk(field, new int[]{TRUE}, new int[]{prefixsBDD});
    }

    /**
     * Encode a binary prefix as a BDD using given variable handles.
     *
     * @param prefixBinary Binary prefix.
     * @param vars         BDD positive literal handles.
     * @param notVars      BDD negative literal handles.
     * @return BDD handle for the prefix.
     */
    public static int encodePrefixBDD(int[] prefixBinary, int[] vars, int[] notVars) {
        if (prefixBinary.length == 0) return 1;
        int prefixBDD = 1;
        for (int i = prefixBinary.length - 1; i >= 0; i--) {
            int currentBit = prefixBinary[i] == 1 ? vars[i] : notVars[i];
            if (i == prefixBinary.length - 1) prefixBDD = bddEngine.ref(currentBit);
            else prefixBDD = bddEngine.andTo(prefixBDD, currentBit);
        }
        return prefixBDD;
    }

    /**
     * Encode an ACL (list of per-field BDDs) as a multi-field NDD.
     *
     * @param perFieldBDD List of (field index, BDD handle) pairs.
     * @return Root NDD node id.
     */
    public static int encodeACL(ArrayList<Pair<Integer, Integer>> perFieldBDD) {
        int result = TRUE;
        for (int i = perFieldBDD.size() - 1; i >= 0; i--) {
            if (perFieldBDD.get(i).getValue() != 1) {
                result = nodeTable.mk(perFieldBDD.get(i).getKey(),
                        new int[]{result},
                        new int[]{perFieldBDD.get(i).getValue()});
            }
        }
        return result;
    }

    /**
     * Wrap a BDD handle as a single-field NDD (one node, one edge to TRUE with label a).
     *
     * @param a     BDD handle.
     * @param field Field index.
     * @return NDD node id.
     */
    public static int toNDD(int a, int field) {
        if (a == 1) return TRUE;
        return nodeTable.mk(field, new int[]{TRUE}, new int[]{a});
    }

    /**
     * Convert a (multi-field decomposed) BDD to NDD by rebuilding structure per field.
     *
     * @param a BDD root handle.
     * @return NDD root node id.
     */
    public static int toNDD(int a) {
        HashMap<Integer, HashMap<Integer, Integer>> decomposed = DecomposeBDD.decompose(a, bddEngine, maxVariablePerField);
        HashMap<Integer, Integer> converted = new HashMap<>();
        converted.put(1, TRUE);

        while (!decomposed.isEmpty()) {
            Set<Integer> finished = converted.keySet();
            Iterator<Map.Entry<Integer, HashMap<Integer, Integer>>> it = decomposed.entrySet().iterator();
            while (it.hasNext()) {
                Map.Entry<Integer, HashMap<Integer, Integer>> entry = it.next();
                if (finished.containsAll(entry.getValue().keySet())) {
                    int field = DecomposeBDD.bddGetField(entry.getKey());
                    HashMap<Integer, Integer> edgeMap = entry.getValue();

                    int frameStart = stackTop;
                    for (Map.Entry<Integer, Integer> e : edgeMap.entrySet()) {
                        edgeCollect(frameStart, converted.get(e.getKey()), bddEngine.ref(e.getValue()));
                    }
                    int n = edgeFlush(frameStart, field);

                    converted.put(entry.getKey(), n);
                    it.remove();
                    break;
                }
            }
        }
        return converted.get(a);
    }

    /**
     * Convert an NDD to BDD (recursive: each node's edges OR'd with and(target_BDD, label)).
     *
     * @param root NDD root node id.
     * @return BDD handle (caller must deref when done).
     */
    public static int toBDD(int root) {
        int result = toBDDRec(root);
        bddEngine.deref(result);
        return result;
    }

    /**
     * Recursively convert NDD subtree to BDD (returns ref'd BDD).
     */
    private static int toBDDRec(int current) {
        if (isTrue(current)) return 1;
        if (isFalse(current)) return 0;
        int result = 0;
        int start = nodeTable.getEdgeStart(current);
        int count = nodeTable.getEdgeCount(current);
        for (int i = 0; i < count; i++) {
            int target = nodeTable.getEdgeTarget(start + i);
            int label = nodeTable.getEdgeLabel(start + i);
            int temp = bddEngine.andTo(toBDDRec(target), label);
            result = bddEngine.orTo(result, temp);
            bddEngine.deref(temp);
        }
        return result;
    }

    /**
     * Print NDD structure to stdout (debug).
     *
     * @param root Root node id.
     */
    public static void print(int root) {
        System.out.println("Print " + root + " begin!");
        printRec(root);
        System.out.println("Print " + root + " finish!\n");
    }

    /** Recursively print node and its edges. */
    private static void printRec(int current) {
        if (isTrue(current)) System.out.println("TRUE");
        else if (isFalse(current)) System.out.println("FALSE");
        else {
            System.out.println("field:" + nodeTable.getField(current) + " node:" + current);
            int start = nodeTable.getEdgeStart(current);
            int count = nodeTable.getEdgeCount(current);
            for (int i = 0; i < count; i++) {
                System.out.println("next:" + nodeTable.getEdgeTarget(start + i) + " label:" + nodeTable.getEdgeLabel(start + i));
            }
            for (int i = 0; i < count; i++) printRec(nodeTable.getEdgeTarget(start + i));
        }
    }

    /**
     * Export NDD as a Dot file for graph visualization.
     *
     * @param root     Root node id.
     * @param filename Output file path.
     */
    public static void printDot(int root, String filename) {
        try (FileWriter writer = new FileWriter(filename)) {
            StringBuilder sb = new StringBuilder();
            sb.append("digraph NDD_Graph {\nrankdir=TD;\ncompound=true;\n");
            sb.append("  NDD_TRUE [shape=box, style=filled, label=\"TRUE\"];\n");
            sb.append("  NDD_FALSE [shape=box, style=filled, label=\"FALSE\"];\n");
            IntHashSet visited = new IntHashSet(1024);
            printNDDStructure(root, sb, visited);
            sb.append("}\n");
            writer.write(sb.toString());
        } catch (IOException e) { e.printStackTrace(); }
    }

    /** Recursively append current node and edges to Dot output. */
    private static void printNDDStructure(int current, StringBuilder sb, IntHashSet visited) {
        if (isTerminal(current) || visited.contains(current)) return;
        visited.add(current);
        String nodeId = "N" + current;
        sb.append("  ").append(nodeId).append(" [shape=circle, label=\"F").append(nodeTable.getField(current)).append("\"];\n");
        int start = nodeTable.getEdgeStart(current);
        int count = nodeTable.getEdgeCount(current);
        for (int i = 0; i < count; i++) {
            int next = nodeTable.getEdgeTarget(start + i);
            String nextId = isTrue(next) ? "NDD_TRUE" : (isFalse(next) ? "NDD_FALSE" : "N" + next);
            sb.append("  ").append(nodeId).append(" -> ").append(nextId)
                    .append(" [label=\"").append(nodeTable.getEdgeLabel(start + i)).append("\"];\n");
            printNDDStructure(next, sb, visited);
        }
    }

    /**
     * Simple key-value pair for encodeACL (field index, BDD handle).
     */
    public static class Pair<K, V> {
        private final K key;
        private final V value;

        public Pair(K key, V value) {
            this.key = key;
            this.value = value;
        }

        public K getKey() { return key; }
        public V getValue() { return value; }
    }

    /**
     * Cache for unary/binary NDD operations (op1, op2, result slots by hash).
     */
    private static class IntOperationCache {
        private static final int EMPTY = Integer.MIN_VALUE;
        private final int size;
        private final int[] op1;
        private final int[] op2;
        private final int[] res;
        /** Last result from getEntry (for setEntry). */
        int result;
        /** Last hash index from getEntry (for setEntry). */
        int hashValue;

        IntOperationCache(int cacheSize) {
            this.size = cacheSize;
            this.op1 = new int[cacheSize];
            this.op2 = new int[cacheSize];
            this.res = new int[cacheSize];
            clear();
        }

        /** Look up unary cache (e.g. not); return true if hit and result is set. */
        boolean getEntry(int a) {
            int hash = hashUnary(a);
            if (op1[hash] == a) {
                result = res[hash];
                return true;
            }
            hashValue = hash;
            return false;
        }

        /** Look up binary cache (e.g. and, or); return true if hit and result is set. */
        boolean getEntry(int a, int b) {
            int hash = hashBinary(a, b);
            int oa = op1[hash];
            int ob = op2[hash];
            if ((oa == a && ob == b) || (oa == b && ob == a)) {
                result = res[hash];
                return true;
            }
            hashValue = hash;
            return false;
        }

        /** Store unary result at index. */
        void setEntry(int index, int a, int result) {
            op1[index] = a;
            op2[index] = EMPTY;
            res[index] = result;
        }

        /** Store binary result at index. */
        void setEntry(int index, int a, int b, int result) {
            op1[index] = a;
            op2[index] = b;
            res[index] = result;
        }

        void clear() {
            Arrays.fill(op1, EMPTY);
            Arrays.fill(op2, EMPTY);
            Arrays.fill(res, 0);
        }

        private int hashUnary(int a) {
            return Math.abs(a) % size;
        }

        private int hashBinary(int a, int b) {
            return (int) (Math.abs((long) a + (long) b) % size);
        }
    }

    /**
     * Int set for temporarily protected node ids (open-addressed hash set).
     */
    private static class IntHashSet {
        private static final int EMPTY = Integer.MIN_VALUE;
        private int[] table;
        private int size;
        private int mask;
        private int threshold;

        IntHashSet(int capacity) {
            int cap = 1;
            while (cap < capacity * 2) cap <<= 1;
            table = new int[cap];
            Arrays.fill(table, EMPTY);
            mask = cap - 1;
            threshold = (int) (cap * 0.7);
        }

        void clear() {
            Arrays.fill(table, EMPTY);
            size = 0;
        }

        /** @return Whether the set contains the value. */
        boolean contains(int value) {
            if (value <= 1) return true;
            int pos = mix(value) & mask;
            while (table[pos] != EMPTY) {
                if (table[pos] == value) return true;
                pos = (pos + 1) & mask;
            }
            return false;
        }

        void add(int value) {
            if (value <= 1) return;
            if (size >= threshold) rehash();
            int pos = mix(value) & mask;
            while (table[pos] != EMPTY) {
                if (table[pos] == value) return;
                pos = (pos + 1) & mask;
            }
            table[pos] = value;
            size++;
        }

        /** Apply consumer to each element. */
        void forEach(IntConsumer consumer) {
            for (int value : table) {
                if (value != EMPTY) consumer.accept(value);
            }
        }

        private void rehash() {
            int[] old = table;
            int newCap = old.length << 1;
            table = new int[newCap];
            Arrays.fill(table, EMPTY);
            mask = newCap - 1;
            threshold = (int) (newCap * 0.7);
            size = 0;
            for (int value : old) {
                if (value != EMPTY) add(value);
            }
        }

        private int mix(int x) {
            x ^= (x >>> 16);
            x *= 0x7feb352d;
            x ^= (x >>> 15);
            x *= 0x846ca68b;
            x ^= (x >>> 16);
            return x;
        }
    }

    /**
     * Int-to-int map for edge collection (target -> label), open-addressed.
     */
    private static class IntIntMap {
        private static final int EMPTY = Integer.MIN_VALUE;
        private int[] keys;
        private int[] values;
        private int size;
        private int mask;
        private int threshold;

        IntIntMap(int capacity) {
            int cap = 1;
            while (cap < capacity * 2) cap <<= 1;
            keys = new int[cap];
            values = new int[cap];
            Arrays.fill(keys, EMPTY);
            mask = cap - 1;
            threshold = (int) (cap * 0.7);
        }

        /** @return Value for key, or 0 if absent. */
        int get(int key) {
            int pos = mix(key) & mask;
            while (keys[pos] != EMPTY) {
                if (keys[pos] == key) return values[pos];
                pos = (pos + 1) & mask;
            }
            return 0;
        }

        void put(int key, int value) {
            if (size >= threshold) rehash();
            int pos = mix(key) & mask;
            while (keys[pos] != EMPTY) {
                if (keys[pos] == key) {
                    values[pos] = value;
                    return;
                }
                pos = (pos + 1) & mask;
            }
            keys[pos] = key;
            values[pos] = value;
            size++;
        }

        /** Apply consumer to each (key, value) pair. */
        void forEach(IntIntConsumer consumer) {
            for (int i = 0; i < keys.length; i++) {
                if (keys[i] != EMPTY) consumer.accept(keys[i], values[i]);
            }
        }

        private void rehash() {
            int[] oldKeys = keys;
            int[] oldValues = values;
            int newCap = oldKeys.length << 1;
            keys = new int[newCap];
            values = new int[newCap];
            Arrays.fill(keys, EMPTY);
            mask = newCap - 1;
            threshold = (int) (newCap * 0.7);
            size = 0;
            for (int i = 0; i < oldKeys.length; i++) {
                if (oldKeys[i] != EMPTY) put(oldKeys[i], oldValues[i]);
            }
        }

        private int mix(int x) {
            x ^= (x >>> 16);
            x *= 0x7feb352d;
            x ^= (x >>> 15);
            x *= 0x846ca68b;
            x ^= (x >>> 16);
            return x;
        }
    }

    /** Callback for IntIntMap.forEach. */
    private interface IntIntConsumer {
        void accept(int key, int value);
    }
}
