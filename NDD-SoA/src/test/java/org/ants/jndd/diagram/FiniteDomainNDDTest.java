package org.ants.jndd.diagram;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public class FiniteDomainNDDTest {

    @Test
    public void finiteDomainApiExposesValueSetSemantics() {
        FiniteDomainNDD.init(1024, 256, 256);
        FiniteDomainNDD.declareField(4);
        FiniteDomainNDD.generateFields();

        int value1 = FiniteDomainNDD.ref(FiniteDomainNDD.getVar(0, 1));
        int notValue1 = FiniteDomainNDD.ref(FiniteDomainNDD.getNotVar(0, 1));
        int value2 = FiniteDomainNDD.ref(FiniteDomainNDD.getVar(0, 2));
        int union = FiniteDomainNDD.ref(FiniteDomainNDD.or(value1, value2));

        assertEquals(1.0, FiniteDomainNDD.satCount(value1), 0.0001);
        assertEquals(3.0, FiniteDomainNDD.satCount(notValue1), 0.0001);
        assertEquals(2.0, FiniteDomainNDD.satCount(union), 0.0001);

        FiniteDomainNDD.deref(value1);
        FiniteDomainNDD.deref(notValue1);
        FiniteDomainNDD.deref(value2);
        FiniteDomainNDD.deref(union);
    }
}
