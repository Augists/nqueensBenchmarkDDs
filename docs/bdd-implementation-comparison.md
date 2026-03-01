# BDD Implementation Comparison Analysis

本文档分析 benchmark 中各 BDD/NDD 库的内部实现差异，解释性能表现背后的设计原因。

## 节点存储结构对比

| 库 | 语言 | 节点大小 | 存储方式 | 补边 (Complement Edge) |
|---|---|---|---|---|
| **DD-BDD/DD-CBDD** | C# | **16 字节** (struct) | 连续数组 `T[]` | 有 (DDIndex bit 0) |
| **BuDDy** | C | 24 字节 | 连续数组 `BddNode*` | 无 |
| **Sylvan** | C | ~16 字节 (hash table entry) | 并行 hash table | 有 |
| **CUDD** | C | 32 字节 | 指针链表 + 子表 | 有 (指针 LSB) |
| **JDD** | Java | 14 字节 (分离数组) | 多个 `int[]`/`short[]` | 无 |
| **JSylvan** | Java/C | 同 Sylvan (JNI 调用) | 同 Sylvan | 有 |
| **NDD** | Java | ~40+ 字节 (HashMap) | `HashMap<NDD, Integer>` | 不适用 |

### DecisionDiagrams (DD-BDD) 节点结构

```
DDIndex (32 bits):
  bit 31:    reserved (invalid marker)
  bit 30-1:  node position (30 bits, 最大 10 亿节点)
  bit 0:     complement bit

BDDNode (16 bytes, struct):
  NodeData32 (4 bytes):  variable ID (31 bits) + GC mark bit (1 bit)
  DDIndex Low  (4 bytes): low child index + complement bit
  DDIndex High (4 bytes): high child index + complement bit
  padding      (4 bytes)
```

### BuDDy 节点结构

```
BddNode (24 bytes):
  refcou : 10 bits  // 引用计数 (最大 1023)
  level  : 22 bits  // 变量层级
  low    : 4 bytes  // low 子节点 index
  high   : 4 bytes  // high 子节点 index
  hash   : 4 bytes  // hash 值
  next   : 4 bytes  // hash 冲突链
```

### CUDD 节点结构

```
DdNode (32 bytes on 64-bit):
  index  : 4 bytes  // 变量索引
  ref    : 4 bytes  // 引用计数
  next   : 8 bytes  // 指针，unique table 冲突链
  type   : 16 bytes // union { double value; struct { DdNode *T, *E; } kids; }
```

### JDD 节点结构

```
// 分散在 3 个数组中
t_nodes[bdd * 3 + 0]: low   (4 bytes)
t_nodes[bdd * 3 + 1]: var   (4 bytes, MSB 为 GC mark bit)
t_nodes[bdd * 3 + 2]: high  (4 bytes)
t_ref[bdd]:           refcount (2 bytes, short)
t_list[bdd * 2 + 0]:  next  (4 bytes, hash 冲突链)
t_list[bdd * 2 + 1]:  prev  (4 bytes)
// 总计：约 22 字节/节点
```

## 补边 (Complement Edges) 的影响

补边是 BDD 库最关键的优化之一。

| 库 | 补边 | NOT 操作代价 | 对 N-Queens 的影响 |
|---|---|---|---|
| **DD-BDD** | 有 | O(1)，翻转 DDIndex bit 0 | `OR(NOT(a), NOT(b))` 中 NOT 零开销 |
| **CUDD** | 有 | O(1)，翻转指针 LSB | 同上 |
| **Sylvan/JSylvan** | 有 | O(1) | 同上 |
| **BuDDy** | **无** | O(n)，递归创建新节点 | 每次 NOT 都要遍历整棵 BDD |
| **JDD** | **无** | O(n)，递归创建新节点 | 同上 |

N-Queens 问题中大量使用 `implies(a, b) = OR(NOT(a), NOT(b))`：
- 有补边的库：NOT 只翻转 1 bit，不创建任何新节点
- 无补边的库：NOT 需要递归遍历整个 BDD，创建镜像节点

DD-BDD 的 `Or(a, b)` 实现：
```csharp
// Or = NOT(AND(NOT(a), NOT(b)))  — De Morgan 定律
// 3 次 NOT 都是 O(1)，只需要缓存 AND 一个操作
internal DDIndex Or(DDIndex x, DDIndex y) {
    return this.Not(this.Apply(this.Not(x), this.Not(y), DDOperation.And));
}
```

## 缓存设计对比

| 库 | 缓存策略 | 缓存操作数 | 大小 |
|---|---|---|---|
| **DD-BDD** | 只缓存 And（其他操作通过补边推导） | 统一 | pool/16 |
| **BuDDy** | 分别缓存各操作 | 分散 | 固定 10000 |
| **CUDD** | computed table，标签区分操作 | 分散 | 动态 |
| **JDD** | SimpleCache/DoubleCache 多类型 | 分散 | 自适应 |

DD-BDD 只缓存 `And` 的优势：
- 所有操作共享同一个 cache，命中率更高
- cache 容量全部集中在一个操作上，不分散
- 前提是 NOT 必须是 O(1)（依赖补边）

## Unique Table 与 Age Invariant

### DD-BDD 的 age invariant 机制

DD-BDD 的 MemoryPool 是一个连续数组，节点按分配顺序存储。**任何节点的子节点一定比它自身更早分配**，因此子节点的 index 一定更小。这个性质被称为 age invariant。

```
MemoryPool: [terminal | node_1 | node_2 | ... | node_k | ... | free space]
                        ↑ 早分配                  ↑ 晚分配
```

Unique table 查找时利用这个性质做**提前终止**：

```csharp
public DDIndex GetOrAdd(T key) {
    var loPos = key.Low.GetPosition();   // 子节点位置
    var hiPos = key.High.GetPosition();

    int i = this.buckets[targetBucket];
    while (i >= 0) {
        var pos = entries[i].Value.GetPosition();

        // 关键优化：如果冲突链中的节点比两个子节点都年轻（index 更大），
        // 那么这个节点不可能是我们要找的（因为它的子节点会更年轻），
        // 而且链表后续的节点只会更年轻，所以可以直接终止搜索
        if (loPos >= pos && hiPos >= pos) {
            break;  // 提前终止
        }

        if (this.manager.MemoryPool[pos].Equals(key)) {
            return idx;  // 找到了
        }
        i = entry.Next;
    }
    // 没找到，分配新节点
}
```

### GC 会复用内存，但保持 age invariant

DD-BDD **有垃圾回收**，而且**会复用内存**。它的 GC 是 sliding compaction（滑动压缩）：

```
GC 前: [T | alive | DEAD | alive | DEAD | alive | free...]
GC 后: [T | alive | alive | alive | free..................]
         ↑ 存活节点左移填补空洞，相对顺序不变
```

具体步骤：
1. **Mark**：从外部引用的根节点出发，标记所有可达节点
2. **Sweep + Compact**：从左到右扫描，存活节点**向左滑动**填补死节点的空洞
3. **Rebuild**：用 forwarding address 数组重建 unique table 和 handle table，更新所有子节点引用

关键点：**存活节点只会向左移动（index 变小），绝不会向右移动**。这保证了：
- 老节点依然在前面，新节点依然在后面
- 子节点的 index 依然小于父节点的 index
- Age invariant 在 GC 后依然成立

GC 之后 `this.index = nextFree`，新分配从压缩后的尾部继续，空间被复用。

### 其他库的 unique table

| 库 | Unique Table 结构 | 特殊优化 |
|---|---|---|
| **DD-BDD** | 全局 hash table + age invariant 提前终止 | 查找可提前终止 |
| **BuDDy** | 全局 hash table，TRIPLE hash | 无 |
| **CUDD** | **按变量层级分子表** (per-level subtable) | 变量重排序友好 |
| **JDD** | 全局 hash table，双链表 | 无 |

## 缓存友好性分析

一个 CPU cache line 通常 64 字节：

| 库 | 节点大小 | 每 cache line 装几个节点 | 备注 |
|---|---|---|---|
| **DD-BDD** | 16 字节 | 4 个 | struct 连续存储 |
| **BuDDy** | 24 字节 | 2 个 | 连续数组 |
| **CUDD** | 32 字节 | 2 个 | 指针追踪有额外 cache miss |
| **JDD** | 22 字节 (分散) | N/A | 访问一个节点需跳 3 个数组 |

DD-BDD 的 struct 值类型直接内嵌在数组中，遍历时顺序访问连续内存。JDD 虽然也用数组，但节点数据分散在 `t_nodes[]`、`t_list[]`、`t_ref[]` 三个数组，每次操作一个节点至少引起 3 次可能不同 cache line 的访问。

## NDD 的特殊性

NDD (Network Decision Diagram) 不是传统 BDD 库，它是面向网络验证的决策图：
- 节点用 `HashMap<NDD, Integer>` 存边，每条边的 label 是一个 BDD
- 相比传统 BDD 的二叉结构，NDD 是多叉结构（一个节点可以有多条出边）
- NDD 内部还嵌套了一个 JDD 实例作为 BDD 引擎
- 适合网络验证中的字段级局部性优化，但在纯 N-Queens 问题上没有结构优势

## N=8 时的 Benchmark 数据

```
实现        nodes_created  nodes_alive  time_sec
BuDDy       53611          2451         0.019s
Sylvan      54531          2451         0.045s
CUDD        52385          2451         0.021s
JDD         53083          2451         0.093s
JSylvan     54140          2451         0.176s
NDD         9877           9877         0.161s
DD-BDD      52181          2458         0.106s
DD-CBDD     46171          772          0.100s
```

注意：N=8 时问题规模太小，时间差异主要来自运行时启动开销（JVM ~100ms, .NET ~80ms），而非算法效率差异。真正能体现实现差异的是 N=11、12 时千万级节点规模的场景。

### nodes_alive 说明

- BuDDy/Sylvan/CUDD/JDD/JSylvan 的 `nodes_alive=2451` 高度一致，说明最终 BDD 结构相同
- DD-BDD 的 `nodes_alive=2458` 略高，可能因补边存储方式的细微差异
- DD-CBDD 的 `nodes_alive=772` 远低于其他，这是 chain reduction 的效果——连续相同分支的变量被压缩成一个节点
- NDD 的 `nodes_created=nodes_alive=9877`，说明 N=8 时未触发 GC，所有创建的节点都存活

## CBDD (Chain-Reduced BDD) 特殊优化

DD-CBDD 使用 CBDDNode，在标准 BDD 基础上做了 chain reduction：

```
标准 BDD:        CBDD:
  x1               x1 (next=x4)
  |                 |
  x2               x4
  |                 ...
  x3
  |
  x4
  ...

如果 x1→x2→x3→x4 的 high child 都相同，
CBDD 将整条链压缩为一个节点 (variable=x1, nextVariable=x4)
```

这解释了 DD-CBDD 在 `nodes_alive` 上远低于其他实现的原因。
