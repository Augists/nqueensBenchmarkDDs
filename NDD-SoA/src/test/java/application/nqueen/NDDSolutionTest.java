package application.nqueen;

import static org.junit.Assert.assertTrue;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;

import org.junit.Test;

public class NDDSolutionTest {

    @Test
    public void mainPrintsMetricsForDefaultMode() {
        PrintStream originalOut = System.out;
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try {
            System.setOut(new PrintStream(output));
            NDDSolution.main(new String[] { "4" });
        } finally {
            System.setOut(originalOut);
        }

        String text = output.toString();
        assertTrue(text.contains("NQUEENS_METRICS n=4 solutions=2"));
        assertTrue(text.contains("ndd_nodes_created="));
        assertTrue(text.contains("bdd_nodes_created="));
        assertTrue(text.contains("ndd_nodes_alive="));
        assertTrue(text.contains("bdd_nodes_alive="));
    }

    @Test
    public void mainSupportsFiniteDomainZddMode() {
        PrintStream originalOut = System.out;
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try {
            System.setOut(new PrintStream(output));
            NDDSolution.main(new String[] { "--finite-domain-zdd", "4" });
        } finally {
            System.setOut(originalOut);
        }

        String text = output.toString();
        assertTrue(text.contains("NQUEENS_METRICS n=4 solutions=2"));
        assertTrue(text.contains("mode=FINITE_DOMAIN_ZDD"));
    }

    @Test
    public void mainSupportsComplementedBddMode() {
        PrintStream originalOut = System.out;
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try {
            System.setOut(new PrintStream(output));
            NDDSolution.main(new String[] { "--bcdd", "4" });
        } finally {
            System.setOut(originalOut);
        }

        String text = output.toString();
        assertTrue(text.contains("NQUEENS_METRICS n=4 solutions=2"));
        assertTrue(text.contains("mode=COMPLEMENTED_BDD"));
    }
}
