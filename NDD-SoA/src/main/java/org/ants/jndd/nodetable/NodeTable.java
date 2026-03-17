/**
 * Node table of NDD (Node Decision Diagram).
 * Manages node storage, unique table lookup, and reference counting.
 *
 * @author Zechun Li & Yichi Zhang - XJTU ANTS NetVerify Lab
 * @version 1.0
 */
package org.ants.jndd.nodetable;

import jdd.bdd.BDD;
import org.ants.jndd.diagram.NDD;

import java.util.ArrayList;
import java.util.Arrays;

public class NodeTable {
    /**
     * The total number of nodes ever created.
     */
    private long totalCreated;

    /**
     * The current number of stored nodes.
     */
    private long currentSize;

    /**
     * The max size of the node table before gc or grow.
     */
    private long nddTableSize;

    /**
     * Per-field unique tables for node deduplication.
     */
    private final ArrayList<UniqueTable> nodeTable;

    /**
     * The internal BDD engine for edge labels.
     */
    private final BDD bddEngine;

    /**
     * If the number of free nodes is less than this threshold after garbage collection, the node table will grow.
     */
    private final double QUICK_GROW_THRESHOLD = 0.1;

    /**
     * Capacity of node arrays (nodeField, nodeEdgeStart, etc.).
     */
    private int nodeCapacity;

    /**
     * Capacity of edge arrays (edgeTarget, edgeLabel).
     */
    private int edgeCapacity;

    /**
     * Next node id to allocate (0=FALSE, 1=TRUE, 2+ = internal nodes).
     */
    private int nextNodeId;

    /**
     * Next free index in edge arrays.
     */
    private int edgeTop;

    /**
     * Head of the free-node list (reused after gc).
     */
    private int freeNodeHead = 0;

    /**
     * Field index for each node (index 0/1 reserved for terminals).
     */
    private int[] nodeField;

    /**
     * Start index in edge arrays for each node's edges.
     */
    private int[] nodeEdgeStart;

    /**
     * Number of edges for each node.
     */
    private int[] nodeEdgeCount;

    /**
     * Next node in the same unique-table bucket (linked list).
     */
    private int[] nodeNext;

    /**
     * Hash value for each node (for unique table lookup).
     */
    private int[] nodeHash;

    /**
     * Reference count of each node.
     */
    private int[] refCount;

    /**
     * Target node id for each edge.
     */
    private int[] edgeTarget;

    /**
     * BDD handle for each edge label.
     */
    private int[] edgeLabel;

    /**
     * Construct the node table.
     *
     * @param nddTableSize The max size of the ndd node table.
     * @param bddTableSize The BDD node table size.
     * @param bddCacheSize The BDD cache size.
     */
    public NodeTable(long nddTableSize, int bddTableSize, int bddCacheSize) {
        this.totalCreated = 0L;
        this.currentSize = 0L;
        this.nddTableSize = nddTableSize;
        this.nodeTable = new ArrayList<>();
        this.bddEngine = new BDD(bddTableSize, bddCacheSize);

        int initialNodeCap = (int) Math.max(4, Math.min(4096, nddTableSize + 2));
        int initialEdgeCap = Math.max(16, initialNodeCap * 4);

        this.nodeCapacity = initialNodeCap;
        this.edgeCapacity = initialEdgeCap;
        this.nextNodeId = 2;
        this.edgeTop = 0;

        this.nodeField = new int[nodeCapacity];
        this.nodeEdgeStart = new int[nodeCapacity];
        this.nodeEdgeCount = new int[nodeCapacity];
        this.nodeNext = new int[nodeCapacity];
        this.nodeHash = new int[nodeCapacity];
        this.refCount = new int[nodeCapacity];
        this.edgeTarget = new int[edgeCapacity];
        this.edgeLabel = new int[edgeCapacity];

        Arrays.fill(nodeField, -1);
        nodeField[0] = Integer.MAX_VALUE;
        nodeField[1] = Integer.MAX_VALUE;
        refCount[0] = Integer.MAX_VALUE;
        refCount[1] = Integer.MAX_VALUE;
    }

    /**
     * Get the internal BDD engine.
     *
     * @return The internal BDD engine.
     */
    public BDD getBddEngine() { return bddEngine; }

    /**
     * Declare a new field and add a unique table for it.
     */
    public void declareField() {
        nodeTable.add(new UniqueTable(4096));
    }

    /**
     * Get the number of stored nodes (excluding freed slots).
     *
     * @return The current stored node count.
     */
    public long getCurrentSize() {
        return currentSize;
    }

    /**
     * Get the total number of NDD nodes ever created.
     * @return Total number of nodes created (including those later garbage collected).
     */
    public long getTotalCreated() {
        return totalCreated;
    }

    /**
     * Get the field index of a node.
     *
     * @param nodeId The node id.
     * @return The field index, or Integer.MAX_VALUE for terminal nodes.
     */
    public int getField(int nodeId) {
        if (nodeId <= 1) return Integer.MAX_VALUE;
        return nodeField[nodeId];
    }

    /**
     * Get the start index of edges for a node.
     *
     * @param nodeId The node id.
     * @return The start index in edge arrays.
     */
    public int getEdgeStart(int nodeId) {
        return nodeEdgeStart[nodeId];
    }

    /**
     * Get the number of edges of a node.
     *
     * @param nodeId The node id.
     * @return The edge count.
     */
    public int getEdgeCount(int nodeId) {
        return nodeEdgeCount[nodeId];
    }

    /**
     * Get the target node id of an edge.
     *
     * @param edgeIndex The edge index in edge arrays.
     * @return The target node id.
     */
    public int getEdgeTarget(int edgeIndex) {
        return edgeTarget[edgeIndex];
    }

    /**
     * Get the BDD handle of an edge label.
     *
     * @param edgeIndex The edge index in edge arrays.
     * @return The BDD label handle.
     */
    public int getEdgeLabel(int edgeIndex) {
        return edgeLabel[edgeIndex];
    }

    /**
     * Create or reuse an NDD node with given edges.
     *
     * @param field  The field index.
     * @param targets Array of target node ids.
     * @param labels  Array of BDD label handles (same length as targets).
     * @return The node id (new or reused).
     */
    public int mk(int field, int[] targets, int[] labels) {
        return mk(field, targets, labels, 0, targets.length);
    }

    /**
     * Create or reuse an NDD node with a slice of edges.
     *
     * @param field   The field index.
     * @param targets Array of target node ids.
     * @param labels  Array of BDD label handles.
     * @param offset  Start index in targets/labels.
     * @param length  Number of edges.
     * @return The node id (new or reused).
     */
    public int mk(int field, int[] targets, int[] labels, int offset, int length) {
        UniqueTable table = nodeTable.get(field);
        int hash = computeHash(targets, labels, offset, length);
        int nodeId = table.lookup(hash, targets, labels, offset, length, this);

        if (nodeId != 0) {
            for (int i = 0; i < length; i++) bddEngine.deref(labels[offset + i]);
            return nodeId;
        }

        if (currentSize >= nddTableSize) gcOrGrow();
        int id;
        if (freeNodeHead != 0) {
            id = freeNodeHead;
            freeNodeHead = nodeNext[id]; 
        } else {
            id = nextNodeId++;
            totalCreated++;
            ensureNodeCapacity(id);
        }
        ensureEdgeCapacity(length);

        int start = edgeTop;
        for (int i = 0; i < length; i++) {
            edgeTarget[edgeTop] = targets[offset + i];
            edgeLabel[edgeTop] = labels[offset + i];
            edgeTop++;
        }

        nodeField[id] = field;
        nodeEdgeStart[id] = start;
        nodeEdgeCount[id] = length;
        nodeHash[id] = hash;
        nodeNext[id] = 0;
        refCount[id] = 0;

        for (int i = 0; i < length; i++) {
            int target = targets[offset + i];
            if (target > 1 && nodeField[target] >= 0 && refCount[target] != Integer.MAX_VALUE) {
                refCount[target] += 1;
            }
        }

        table.insert(id, this);
        currentSize++;
        return id;
    }

    /**
     * Ensure node arrays have capacity for the given node id.
     *
     * @param id The node id that must be storable.
     */
    private void ensureNodeCapacity(int id) {
        if (id < nodeCapacity) return;
        int newCap = nodeCapacity;
        while (newCap <= id) newCap <<= 1;

        nodeField = Arrays.copyOf(nodeField, newCap);
        nodeEdgeStart = Arrays.copyOf(nodeEdgeStart, newCap);
        nodeEdgeCount = Arrays.copyOf(nodeEdgeCount, newCap);
        nodeNext = Arrays.copyOf(nodeNext, newCap);
        nodeHash = Arrays.copyOf(nodeHash, newCap);
        refCount = Arrays.copyOf(refCount, newCap);

        Arrays.fill(nodeField, nodeCapacity, newCap, -1);
        nodeCapacity = newCap;
    }

    /**
     * Ensure edge arrays have capacity for additional edges.
     *
     * @param needed Number of additional edges required.
     */
    private void ensureEdgeCapacity(int needed) {
        if (edgeTop + needed <= edgeCapacity) return;
        int newCap = edgeCapacity;
        while (newCap < edgeTop + needed) newCap <<= 1;
        edgeTarget = Arrays.copyOf(edgeTarget, newCap);
        edgeLabel = Arrays.copyOf(edgeLabel, newCap);
        edgeCapacity = newCap;
    }

    /**
     * Free unused nodes first by garbage collection, then grow table if needed.
     */
    private void gcOrGrow() {
        gc();
        if (nddTableSize - currentSize <= nddTableSize * QUICK_GROW_THRESHOLD) grow();
        NDD.clearCaches();
    }

    /**
     * Garbage collection: remove nodes with zero reference count and compact edges.
     */
    public void gc() {
        NDD.forEachTemporarilyProtect(this::ref);

        IntQueue queue = new IntQueue((int) Math.max(16, currentSize));
        for (int i = 2; i < nextNodeId; i++) {
            if (nodeField[i] >= 0 && refCount[i] == 0) queue.add(i);
        }

        while (!queue.isEmpty()) {
            int deadNode = queue.poll();
            int start = nodeEdgeStart[deadNode];
            int count = nodeEdgeCount[deadNode];

            for (int i = 0; i < count; i++) {
                int target = edgeTarget[start + i];
                if (target <= 1 || nodeField[target] < 0) continue;
                if (refCount[target] != Integer.MAX_VALUE) {
                    int updated = --refCount[target];
                    if (updated == 0) queue.add(target);
                }
            }

            for (int i = 0; i < count; i++) bddEngine.deref(edgeLabel[start + i]);

            nodeTable.get(nodeField[deadNode]).remove(deadNode, this);
            nodeField[deadNode] = -1;
            nodeEdgeStart[deadNode] = 0;
            nodeEdgeCount[deadNode] = 0;
            nodeHash[deadNode] = 0;
            refCount[deadNode] = 0;
            currentSize--;
            
            nodeNext[deadNode] = freeNodeHead;
            freeNodeHead = deadNode;
        }

        compactEdges();
        NDD.forEachTemporarilyProtect(this::deref);
    }

    /**
     * Compact edge arrays by removing gaps left by collected nodes.
     */
    private void compactEdges() {
        int newEdgeTop = 0;
        int[] newEdgeTarget = new int[Math.max(16, edgeTop)];
        int[] newEdgeLabel = new int[newEdgeTarget.length];

        for (int nodeId = 2; nodeId < nextNodeId; nodeId++) {
            if (nodeField[nodeId] < 0) continue;
            int count = nodeEdgeCount[nodeId];
            if (newEdgeTop + count > newEdgeTarget.length) {
                int newCap = newEdgeTarget.length;
                while (newCap < newEdgeTop + count) newCap <<= 1;
                newEdgeTarget = Arrays.copyOf(newEdgeTarget, newCap);
                newEdgeLabel = Arrays.copyOf(newEdgeLabel, newCap);
            }
            int oldStart = nodeEdgeStart[nodeId];
            System.arraycopy(edgeTarget, oldStart, newEdgeTarget, newEdgeTop, count);
            System.arraycopy(edgeLabel, oldStart, newEdgeLabel, newEdgeTop, count);
            nodeEdgeStart[nodeId] = newEdgeTop;
            newEdgeTop += count;
        }

        edgeTarget = newEdgeTarget;
        edgeLabel = newEdgeLabel;
        edgeTop = newEdgeTop;
        edgeCapacity = newEdgeTarget.length;
    }

    /**
     * Grow the max node table size (double).
     */
    private void grow() {
        nddTableSize *= 2;
    }

    /**
     * Increment reference count of a node (protect from gc).
     *
     * @param nodeId The node id.
     * @return The same node id.
     */
    public int ref(int nodeId) {
        if (nodeId <= 1) return nodeId;
        if (nodeField[nodeId] >= 0 && refCount[nodeId] != Integer.MAX_VALUE) {
            refCount[nodeId] += 1;
        }
        return nodeId;
    }

    /**
     * Mark a node as permanently referenced (e.g. variable nodes), so it is never collected.
     *
     * @param nodeId The node id.
     */
    public void fixNDDNodeRefCount(int nodeId) {
        if (nodeId > 1) refCount[nodeId] = Integer.MAX_VALUE;
    }

    /**
     * Decrement reference count of a node (allow gc when zero).
     *
     * @param nodeId The node id.
     */
    public void deref(int nodeId) {
        if (nodeId <= 1) return;
        if (nodeField[nodeId] >= 0 && refCount[nodeId] != Integer.MAX_VALUE) {
            refCount[nodeId] -= 1;
        }
    }

    /**
     * Compute hash for a set of edges (for unique table).
     *
     * @param targets Target array.
     * @param labels  Label array.
     * @param offset  Start index.
     * @param length  Number of edges.
     * @return Hash value.
     */
    private static int computeHash(int[] targets, int[] labels, int offset, int length) {
        int h = 0;
        for (int i = 0; i < length; i++) {
            h = h * 31 + targets[offset + i];
            h = h * 31 + labels[offset + i];
        }
        return h;
    }

    /**
     * Per-field unique table: hash table for deduplicating nodes by (targets, labels).
     */
    private static class UniqueTable {
        /** Bucket array (head node id per bucket). */
        int[] buckets;
        /** Table capacity (power of two). */
        int size;
        /** size - 1, for fast modulo. */
        int mask;
        /** Number of nodes in the table. */
        int count;
        /** Resize when count >= threshold. */
        int threshold;

        UniqueTable(int initCap) {
            size = 1;
            while (size < initCap) size <<= 1;
            buckets = new int[size];
            mask = size - 1;
            threshold = (int) (size * 0.75);
        }

        /**
         * Look up an existing node with the same edges; 0 if not found.
         */
        int lookup(int hash, int[] targets, int[] labels, int offset, int length, NodeTable table) {
            int pos = hash & mask;
            int curr = buckets[pos];
            while (curr != 0) {
                if (table.nodeHash[curr] == hash && arraysMatch(curr, targets, labels, offset, length, table)) return curr;
                curr = table.nodeNext[curr];
            }
            return 0;
        }

        /** Insert a node into the unique table. */
        void insert(int nodeId, NodeTable table) {
            if (count >= threshold) resize(table);
            int pos = table.nodeHash[nodeId] & mask;
            table.nodeNext[nodeId] = buckets[pos];
            buckets[pos] = nodeId;
            count++;
        }

        /** Remove a node from the unique table. */
        void remove(int nodeId, NodeTable table) {
            int pos = table.nodeHash[nodeId] & mask;
            int curr = buckets[pos];
            int prev = 0;
            while (curr != 0) {
                if (curr == nodeId) {
                    if (prev == 0) buckets[pos] = table.nodeNext[curr];
                    else table.nodeNext[prev] = table.nodeNext[curr];
                    count--;
                    return;
                }
                prev = curr;
                curr = table.nodeNext[curr];
            }
        }

        /** Check if a stored node has the same edges as the given slice. */
        private boolean arraysMatch(int nodeId, int[] targets, int[] labels, int offset, int length, NodeTable table) {
            int count = table.nodeEdgeCount[nodeId];
            if (count != length) return false;
            int start = table.nodeEdgeStart[nodeId];
            for (int i = 0; i < length; i++) {
                if (table.edgeTarget[start + i] != targets[offset + i]) return false;
                if (table.edgeLabel[start + i] != labels[offset + i]) return false;
            }
            return true;
        }

        /** Double the table size and rehash. */
        private void resize(NodeTable table) {
            int newSize = size << 1;
            int[] newBuckets = new int[newSize];
            int newMask = newSize - 1;

            for (int i = 0; i < size; i++) {
                int curr = buckets[i];
                while (curr != 0) {
                    int next = table.nodeNext[curr];
                    int pos = table.nodeHash[curr] & newMask;
                    table.nodeNext[curr] = newBuckets[pos];
                    newBuckets[pos] = curr;
                    curr = next;
                }
            }

            size = newSize;
            buckets = newBuckets;
            mask = newMask;
            threshold = (int) (newSize * 0.75);
        }
    }

    /** Simple int queue for gc dead-node traversal. */
    private static class IntQueue {
        private int[] data;
        private int head;
        private int tail;

        IntQueue(int initialCapacity) {
            data = new int[Math.max(16, initialCapacity)];
        }

        boolean isEmpty() { return head == tail; }

        void add(int value) {
            if (tail >= data.length) grow();
            data[tail++] = value;
        }

        int poll() { return data[head++]; }

        private void grow() {
            data = Arrays.copyOf(data, data.length << 1);
        }
    }
}
