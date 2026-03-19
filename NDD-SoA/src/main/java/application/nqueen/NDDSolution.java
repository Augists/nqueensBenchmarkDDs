package application.nqueen;

import org.ants.jndd.diagram.NDD;

public class NDDSolution {
    public static final int NDD_TABLE_SIZE = 100000000;

    private static final class Result {
        final double solutions;
        final long nodesCreated;
        final long nodesAlive;
        final double seconds;

        Result(double solutions, long nodesCreated, long nodesAlive, double seconds) {
            this.solutions = solutions;
            this.nodesCreated = nodesCreated;
            this.nodesAlive = nodesAlive;
            this.seconds = seconds;
        }
    }

    // declare n fields, n bits per field
    private static void declareFields(int n) {
        for (int i = 0;i < n;i++) {
            NDD.declareField(n);
        }
    }

    private static void build(int i, int j, int n, int[][] impBatch) {
        int a, b, c, d;
        a = b = c = d = NDD.getTrue();

        int k, l;

        /* No one in the same column */
        for (l = 0; l < n; l++) {
            if (l != j) {
                int mp = NDD.ref(NDD.imp(NDD.getVar(i, j), NDD.getNotVar(i, l)));
                a = NDD.andTo(a, mp);
                NDD.deref(mp);
            }
        }

        /* No one in the same row */
        for (k = 0; k < n; k++) {
            if (k != i) {
                int mp = NDD.ref(NDD.imp(NDD.getVar(i, j), NDD.getNotVar(k, j)));
                b = NDD.andTo(b, mp);
                NDD.deref(mp);
            }
        }

        /* No one in the same up-right diagonal */
        for (k = 0; k < n; k++) {
            int ll = k - i + j;
            if (ll >= 0 && ll < n) {
                if (k != i) {
                    int mp = NDD.ref(NDD.imp(NDD.getVar(i, j), NDD.getNotVar(k, ll)));
                    c = NDD.andTo(c, mp);
                    NDD.deref(mp);
                }
            }
        }

        /* No one in the same down-right diagonal */
        for (k = 0; k < n; k++) {
            int ll = i + j - k;
            if (ll >= 0 && ll < n) {
                if (k != i) {
                    int mp = NDD.ref(NDD.imp(NDD.getVar(i, j), NDD.getNotVar(k, ll)));
                    d = NDD.andTo(d, mp);
                    NDD.deref(mp);
                }
            }
        }

        c = NDD.andTo(c, d); 
        NDD.deref(d); 
        b = NDD.andTo(b, c);
        NDD.deref(c); 
        a = NDD.andTo(a, b);
        NDD.deref(b); 
        impBatch[i][j] = a;
    }

    // N is the number of queens, fieldNum is the number of fields in NDD library.
    private static Result solve(int n) {
        long startTimeNanos = System.nanoTime();

        // init NDD library
        NDD.initNDD(NDD_TABLE_SIZE, 1 + Math.max(1000, (int) (Math.pow(4.4, n - 6)) * 1000), 10000);

        // declare ndd fields
        declareFields(n);

        int[] orBatch = new int[n];
        int[][] impBatch = new int[n][n];

        for (int i = 0; i < n; i++) {
            int condition = NDD.getFalse();
            for (int j = 0; j < n; j++) {
                condition = NDD.orTo(condition, NDD.getVar(i, j));
            }
            orBatch[i] = condition;
        }

        for (int i = 0; i < n; i++) {
            for (int j = 0; j < n; j++) {
                build(i, j, n, impBatch);
            }
        }

        int queen = NDD.getTrue();

        for (int i = 0; i < n; i++) {
            queen = NDD.andTo(queen, orBatch[i]);
            NDD.deref(orBatch[i]);
        }
        for (int i = 0; i < n; i++) {
            for (int j = 0; j < n; j++) {
                queen = NDD.andTo(queen, impBatch[i][j]);
                NDD.deref(impBatch[i][j]);
            }
        }
        double solutions = NDD.satCount(queen);
        long nodesCreated = NDD.getTotalCreated();
        NDD.deref(queen);
        double seconds = (System.nanoTime() - startTimeNanos) / 1_000_000_000.0;
        NDD.gc();
        long nodesAlive = NDD.getNodeCount();
        return new Result(solutions, nodesCreated, nodesAlive, seconds);
    }

    /**
     * Legacy helper kept for compatibility with existing experiments.
     */
    public static String Solution(int n) {
        Result result = solve(n);
        return "\t" + String.format("%.3f", result.seconds) + "\t" + result.solutions + "\t" + result.nodesAlive;
    }

    public static void main(String[] args) {
        if (args.length == 0) {
            System.err.println("Usage: NDDSolution <N> [<N> ...]");
            System.exit(1);
        }
        for (String arg : args) {
            int n = Integer.parseInt(arg);
            Result result = solve(n);
            System.out.printf("NQUEENS_METRICS n=%d solutions=%.0f nodes_created=%d nodes_alive=%d seconds=%.6f%n",
                n, result.solutions, result.nodesCreated, result.nodesAlive, result.seconds);
            //System.out.printf(Solution(n));
        }
    }
}
