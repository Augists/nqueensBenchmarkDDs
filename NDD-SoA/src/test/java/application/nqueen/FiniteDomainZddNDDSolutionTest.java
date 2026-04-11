package application.nqueen;

import static org.junit.Assert.assertTrue;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;

import org.junit.Test;

public class FiniteDomainZddNDDSolutionTest {

    @Test
    public void mainPrintsMetricsForFiniteDomainImplementation() {
        PrintStream originalOut = System.out;
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try {
            System.setOut(new PrintStream(output));
            FiniteDomainZddNDDSolution.main(new String[] { "4" });
        } finally {
            System.setOut(originalOut);
        }

        String text = output.toString();
        assertTrue(text.contains("NQUEENS_METRICS n=4 solutions=2"));
        assertTrue(text.contains("implementation=FINITE_DOMAIN_ZDD"));
    }
}
