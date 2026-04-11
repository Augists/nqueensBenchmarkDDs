package org.ants.jndd.diagram;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class NDDLabelModeTest {

    @Test
    public void defaultBddModeStillBehavesLikeBooleanFunctions() {
        NDD.initNDD(1024, 256, 256);
        NDD.declareField(3);
        NDD.generateFields();

        int a = NDD.ref(NDD.getVar(0, 0));
        int notA = NDD.ref(NDD.getNotVar(0, 0));
        int union = NDD.ref(NDD.or(a, notA));
        int intersection = NDD.ref(NDD.and(a, notA));

        assertEquals(8.0, NDD.satCount(union), 0.0001);
        assertEquals(0.0, NDD.satCount(intersection), 0.0001);
        assertTrue(NDD.toBDD(union) != 0);

        NDD.deref(a);
        NDD.deref(notA);
        NDD.deref(union);
        NDD.deref(intersection);
    }

    @Test
    public void finiteDomainZddModeTreatsLabelsAsValueSets() {
        NDD.initNDD(1024, 256, 256, NDD.LabelMode.FINITE_DOMAIN_ZDD);
        NDD.declareField(4);
        NDD.generateFields();

        int value1 = NDD.ref(NDD.getVar(0, 1));
        int notValue1 = NDD.ref(NDD.getNotVar(0, 1));
        int value2 = NDD.ref(NDD.getVar(0, 2));
        int union = NDD.ref(NDD.or(value1, value2));
        int complement = NDD.ref(NDD.not(value1));
        int intersection = NDD.ref(NDD.and(value1, notValue1));

        assertEquals(1.0, NDD.satCount(value1), 0.0001);
        assertEquals(3.0, NDD.satCount(notValue1), 0.0001);
        assertEquals(2.0, NDD.satCount(union), 0.0001);
        assertEquals(3.0, NDD.satCount(complement), 0.0001);
        assertEquals(0.0, NDD.satCount(intersection), 0.0001);

        NDD.deref(value1);
        NDD.deref(notValue1);
        NDD.deref(value2);
        NDD.deref(union);
        NDD.deref(complement);
        NDD.deref(intersection);
    }

    @Test
    public void complementedBddModeStillBehavesLikeBooleanFunctions() {
        NDD.initNDD(1024, 256, 256, NDD.LabelMode.COMPLEMENTED_BDD);
        NDD.declareField(3);
        NDD.generateFields();

        int a = NDD.ref(NDD.getVar(0, 0));
        int notA = NDD.ref(NDD.getNotVar(0, 0));
        int union = NDD.ref(NDD.or(a, notA));
        int complement = NDD.ref(NDD.not(a));
        int intersection = NDD.ref(NDD.and(a, notA));

        assertEquals(8.0, NDD.satCount(union), 0.0001);
        assertEquals(4.0, NDD.satCount(complement), 0.0001);
        assertEquals(0.0, NDD.satCount(intersection), 0.0001);

        NDD.deref(a);
        NDD.deref(notA);
        NDD.deref(union);
        NDD.deref(complement);
        NDD.deref(intersection);
    }
}
