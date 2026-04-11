package org.ants.jndd.diagram;

/**
 * Explicit finite-domain variant of NDD backed by ZDD edge labels.
 *
 * This API intentionally exposes a narrower semantic contract than {@link NDD}:
 * edge labels are interpreted as sets of concrete values within one field, not
 * arbitrary Boolean functions over field bits.
 */
public final class FiniteDomainNDD {
    private FiniteDomainNDD() {}

    public static void init(int nddTableSize, int bddTableSize, int bddCacheSize) {
        NDD.initNDD(nddTableSize, bddTableSize, bddCacheSize, NDD.LabelMode.FINITE_DOMAIN_ZDD);
    }

    public static void init(int nddTableSize, int nddCacheSize, int bddTableSize, int bddCacheSize) {
        NDD.initNDD(nddTableSize, nddCacheSize, bddTableSize, bddCacheSize, NDD.LabelMode.FINITE_DOMAIN_ZDD);
    }

    public static int declareField(int fieldSize) {
        return NDD.declareField(fieldSize);
    }

    public static void generateFields() {
        NDD.generateFields();
    }

    public static int getTrue() {
        return NDD.getTrue();
    }

    public static int getFalse() {
        return NDD.getFalse();
    }

    public static int getVar(int field, int valueIndex) {
        return NDD.getVar(field, valueIndex);
    }

    public static int getNotVar(int field, int valueIndex) {
        return NDD.getNotVar(field, valueIndex);
    }

    public static int ref(int nodeId) {
        return NDD.ref(nodeId);
    }

    public static void deref(int nodeId) {
        NDD.deref(nodeId);
    }

    public static int and(int a, int b) {
        return NDD.and(a, b);
    }

    public static int andTo(int a, int b) {
        return NDD.andTo(a, b);
    }

    public static int or(int a, int b) {
        return NDD.or(a, b);
    }

    public static int orTo(int a, int b) {
        return NDD.orTo(a, b);
    }

    public static int not(int a) {
        return NDD.not(a);
    }

    public static int diff(int a, int b) {
        return NDD.diff(a, b);
    }

    public static int imp(int a, int b) {
        return NDD.imp(a, b);
    }

    public static double satCount(int nodeId) {
        return NDD.satCount(nodeId);
    }

    public static long getTotalCreated() {
        return NDD.getTotalCreated();
    }

    public static long getNodeCount() {
        return NDD.getNodeCount();
    }

    public static void gc() {
        NDD.gc();
    }
}
