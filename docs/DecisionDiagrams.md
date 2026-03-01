# DecisionDiagrams 库深度解析

## 1. 概述

DecisionDiagrams 是微软开源的原生 .NET 决策图库，专注于高性能、易用性和正确性。它提供了两种节点实现，可通过泛型参数自由切换：

- **BDDNode**: 传统二元决策图 (Binary Decision Diagram)
- **CBDDNode**: 链式约简二元决策图 (Chain-Reduced Binary Decision Diagram)

两种实现共享同一套 Manager、UniqueTable 和缓存基础设施，仅在节点结构和约简规则上不同。

**来源**: [GitHub - microsoft/DecisionDiagrams](https://github.com/microsoft/DecisionDiagrams)
**参考论文**: [Cache-optimized BDD](https://research.ibm.com/haifa/projects/verification/SixthSense/papers/bdd_iwls_01.pdf), [Chain-reduced BDD](https://link.springer.com/content/pdf/10.1007%2F978-3-319-89960-2_5.pdf)

---

## 2. 架构总览

```
┌──────────────────────────────────────────────────────┐
│  用户代码                                             │
│    var manager = new DDManager<CBDDNode>();           │
│    DD result = manager.And(a, b);                    │
└──────────┬───────────────────────────────────────────┘
           │
┌──────────▼───────────────────────────────────────────┐
│  DDManager<T>  (核心管理器)                           │
│  ┌────────────┐ ┌─────────────┐ ┌──────────────────┐ │
│  │ MemoryPool │ │ UniqueTable │ │ Operation Cache  │ │
│  │ T[] 节点池  │ │ 哈希唯一化  │ │ 运算结果缓存     │ │
│  └────────────┘ └─────────────┘ └──────────────────┘ │
│  ┌────────────────┐ ┌───────────────────────────────┐ │
│  │ HandleTable    │ │ IDDNodeFactory<T>             │ │
│  │ WeakRef → DD   │ │ (BDDNodeFactory/              │ │
│  │ (.NET GC 集成) │ │  CBDDNodeFactory)             │ │
│  └────────────────┘ └───────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
           │
┌──────────▼───────────────────────────────────────────┐
│  节点实现 (可切换)                                     │
│  ┌─────────────────┐  ┌────────────────────────────┐  │
│  │ BDDNode         │  │ CBDDNode                   │  │
│  │ 12 bytes/node   │  │ 12 bytes/node              │  │
│  │ 1 变量/节点     │  │ 多变量/节点 (链式压缩)     │  │
│  │ max 2^31 变量   │  │ max 2^15 变量              │  │
│  └─────────────────┘  └────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

### 源码结构

```
DecisionDiagrams/
├── DecisionDiagrams/          # 核心库
│   ├── DD.cs                  # 用户持有的外部句柄
│   ├── DDIndex.cs             # 内部指针 (32位, 含补边标记)
│   ├── DDManager.cs           # 核心管理器 (1000+ 行)
│   ├── DDOperation.cs         # 操作枚举 (And, Or, Exists...)
│   ├── IDDNode.cs             # 节点接口
│   ├── IDDNodeFactory.cs      # 节点工厂接口
│   ├── BDDNode.cs             # BDD 节点实现
│   ├── BDDNodeFactory.cs      # BDD 工厂 (Apply/Reduce 逻辑)
│   ├── CBDDNode.cs            # CBDD 节点实现
│   ├── CBDDNodeFactory.cs     # CBDD 工厂 (链式约简逻辑)
│   ├── UniqueTable.cs         # 哈希唯一表
│   ├── NodeData32.cs          # BDD 节点位打包
│   ├── NodeData32Packed.cs    # CBDD 节点位打包
│   ├── Variable.cs            # 变量封装
│   ├── VarBool.cs             # 布尔变量
│   ├── VarInt*.cs             # 整数变量 (8/16/32/64位)
│   └── BitVector.cs           # 位向量 (整数运算)
├── DecisionDiagrams.Bench/    # 基准测试
│   ├── Queens.cs              # N-Queens 实现
│   └── Program.cs             # 入口
└── DecisionDiagrams.Tests/    # 单元测试
```

---

## 3. 核心数据结构

### 3.1 DDIndex - 内部指针 (32位)

DDIndex 是整个库的核心数据类型，将节点位置和补边信息编码在一个 32 位整数中：

```
位布局 (32 bits):
┌──────────────────────────────────────┬──────┐
│  30位 节点位置 (Index >> 1)          │ 补边 │
│  bits [31:1]                         │ bit 0│
└──────────────────────────────────────┴──────┘
```

- **位置提取**: `GetPosition() = Index >> 1`
- **补边检测**: `IsComplemented() = (Index & 1) == 1`
- **取反操作**: `Flip() = new DDIndex(Index ^ 1)` — **O(1) 常数时间!**
- **容量**: 最多 2^30 ≈ 10亿个节点

**特殊常量**:
- `DDIndex.False = 0x00000000` (位置0, 不补)
- `DDIndex.True  = 0x00000001` (位置0, 补边) — False 取反即为 True

**关键优势**: 取反操作不创建新节点，仅翻转 1 位。这意味着 `f` 和 `¬f` 共享完全相同的内部结构。

### 3.2 DD - 外部句柄

用户代码持有的类型，内部仅包含：

```csharp
public sealed class DD {
    internal ushort ManagerId;    // 来源 Manager 的 ID
    internal DDIndex Index;       // 内部指针
}
```

通过 `WeakReference<DD>` 与 .NET GC 集成，用户无需手动释放。

### 3.3 BDDNode - 传统 BDD 节点

```csharp
[StructLayout(LayoutKind.Sequential, Pack = 1)]
public struct BDDNode : IDDNode {
    private NodeData32 data;   // 变量索引 (31位) + 标记位 (1位)
    public DDIndex Low;        // false 分支 (变量=0 时走这条边)
    public DDIndex High;       // true 分支  (变量=1 时走这条边)
}
```

```
内存布局 (12 bytes):
┌────────────────────────────┬────────────┬────────────┐
│  NodeData32 (4 bytes)      │ Low (4B)   │ High (4B)  │
│  Variable[30:0] + Mark[31] │ DDIndex    │ DDIndex    │
└────────────────────────────┴────────────┴────────────┘
```

- **每个节点**: 12 字节
- **每个节点表示**: 1 个变量的决策
- **变量范围**: 0 ~ 2^31-1 (约 20 亿个变量)

### 3.4 CBDDNode - 链式约简 BDD 节点

```csharp
public struct CBDDNode : IDDNode {
    private NodeData32Packed data;  // Variable(15位) + NextVariable(16位) + Mark(1位)
    public DDIndex Low;             // false 分支
    public DDIndex High;            // true 分支
}
```

```
内存布局 (12 bytes):
┌──────────────────────────────────────────┬────────────┬────────────┐
│  NodeData32Packed (4 bytes)              │ Low (4B)   │ High (4B)  │
│  Variable[14:0] + NextVar[30:15] + M[31]│ DDIndex    │ DDIndex    │
└──────────────────────────────────────────┴────────────┴────────────┘
```

- **每个节点**: 12 字节 (与 BDD 相同!)
- **每个节点表示**: 一个**变量范围** `[Variable, NextVariable)` 的决策
- **变量范围**: 0 ~ 2^15-1 (最多 32,767 个变量)
- **链长度**: `NextVariable - Variable` (可以压缩多个连续变量)

---

## 4. 两种实现的对比

### 4.1 核心差异

| 维度 | BDDNode | CBDDNode |
|------|---------|----------|
| **节点大小** | 12 字节 | 12 字节 |
| **变量/节点** | 1 个 | 1~多个 (链式压缩) |
| **最大变量数** | 2^31 (~20亿) | 2^15 (~3.2万) |
| **约简规则** | 标准 ROBDD 约简 | ROBDD + 链式约简 |
| **节点计数** (N=12) | 435,181 | 98,900 |
| **运行时间** (N=12) | ~15秒 | ~10秒 |
| **内存消耗** (N=12) | ~200MB | ~100MB |

### 4.2 BDD 约简规则

BDDNodeFactory 的约简规则只有一条：

```
如果 Low == High → 此节点冗余，直接返回 Low
```

即：如果变量的取值不影响结果，则跳过该变量。这是标准 ROBDD (Reduced Ordered BDD) 的约简。

### 4.3 CBDD 约简规则

CBDDNodeFactory 的约简规则有三条：

```
规则 1 (标准约简): Low == High → 返回 Low

规则 2 (链合并):
  如果 Low 子节点的 Variable == 当前节点的 NextVariable
  且 Low 子节点的 High == 当前节点的 High
  → 合并为更长的链

规则 3 (标准约简的扩展): 针对常量节点的处理
```

**链合并示例**:

```
合并前:
  Node_A: Variable=5, NextVariable=6, Low=Node_B, High=H
  Node_B: Variable=6, NextVariable=8, Low=L, High=H

  (Node_A 的 Low 子节点 Node_B 的 Variable == Node_A 的 NextVariable)
  (Node_B 的 High == Node_A 的 High)
  → 满足链合并条件!

合并后:
  Node_A': Variable=5, NextVariable=8, Low=L, High=H

  一个节点表示了变量 5、6、7 三个变量!
  Node_B 被消除!
```

### 4.4 可视化对比

以 N-Queens 中"第 0 行第 0 列的皇后不能与对角线上的皇后共存"这个约束为例：

```
传统 BDD 表示 (检查 (0,0) 与 (1,1), (2,2), ..., (11,11) 的冲突):

  X[0,0] ──→ X[1,1] ──→ X[2,2] ──→ ... ──→ X[11,11] ──→ result
      │           │           │                   │
      ▼           ▼           ▼                   ▼
    (skip)      (skip)      (skip)              (skip)

  节点数: 12个 (每个变量一个节点)

CBDD 表示 (链式压缩后):

  X[0,0] ══════════════════════════════════════→ result
   var=0, nextVar=12
   (一个节点表示整条对角线链!)

  节点数: 1~2个
```

---

## 5. 补边技术 (Complement Edges) 详解

### 5.1 核心思想

传统 BDD 中，取反操作需要遍历整个图，翻转所有终端节点。复杂度 O(n)。

补边技术将"取反"信息编码在**边**上而非**节点**中：

```
传统 BDD 取反:
  f = Node(x, Low, High)
  ¬f = Node(x, ¬Low, ¬High)    ← 需要递归创建新节点

补边 BDD 取反:
  f  的索引: DDIndex(position=42, complemented=0) = 0x54
  ¬f 的索引: DDIndex(position=42, complemented=1) = 0x55

  仅翻转 1 位! O(1)!
  f 和 ¬f 共享完全相同的内部节点!
```

### 5.2 规范化 (Canonicalization)

为了保证唯一性 (每个布尔函数只有一种表示)，库强制执行规范化规则：

```
规则: Low 分支不能是补边

如果分配的节点 Low 是补边:
  Node(var, Low^, High) → Flip → Node(var, Low, High^)^

即: 翻转两个子节点的补边标记，并将结果本身标记为补边
```

这在 DDManager.Allocate() 中实现：

```csharp
internal DDIndex Allocate(T node) {
    bool flipResult = false;
    if (node.Low.IsComplemented()) {
        node = this.factory.Flip(node);   // 翻转两个子节点
        flipResult = true;
    }
    // ... 约简和唯一表查找
    return flipResult ? ret.Flip() : ret;  // 补边标记到结果上
}
```

### 5.3 对 N-Queens 的影响

N-Queens 的核心约束是"互斥"：`X[i,j] → ¬X[k,l]`

```
等价于: ¬X[i,j] ∨ ¬X[k,l]

传统 BDD:  需要为 ¬X[i,j] 和 ¬X[k,l] 创建否定节点
补边 BDD:  ¬X[i,j] 和 ¬X[k,l] 只需翻转边的 1 位标记
           不创建任何新节点!
```

对于 N=12 的棋盘，有 144 个格子，互斥约束数量约为 C(144,2) 量级。每个约束都涉及取反操作。补边技术直接避免了创建大量否定节点。

---

## 6. DDManager 详解

### 6.1 内存池架构

```csharp
public sealed class DDManager<T> where T : IDDNode, IEquatable<T> {
    internal T[] MemoryPool;           // 节点数组 (连续内存)
    private int index;                 // 下一个空闲位置
    private int poolSize;              // 当前容量 (2的幂)

    private UniqueTable<T> uniqueTable;          // 哈希唯一表
    private OperationResult[] operationCache;    // 1参数缓存 (SatCount)
    private OperationResult2[] operation2Cache;  // 2参数缓存 (And/Or/Exists)
    private OperationResult3[] iteCache;         // 3参数缓存 (ITE)

    private Dictionary<DDIndex, WeakReference<DD>> handleTable;  // 外部句柄表
}
```

**内存池特点**:
- 初始大小: 2^19 = 524,288 个节点
- 增长策略: 满时翻倍 (始终保持 2 的幂)
- 节点按分配顺序排列 (年龄不变量)
- 位置 0 保留给常量节点 (True/False)

### 6.2 垃圾回收 (Mark-Sweep-Shift)

当内存池使用率达到 90% 时触发 GC：

```
阶段 1 - 标记 (Mark):
  从 HandleTable 中所有存活的 WeakReference<DD> 出发
  遍历可达节点，设置 Mark 位

阶段 2 - 清除 (Sweep):
  识别未标记的节点 (垃圾)

阶段 3 - 移位 (Shift):
  将存活节点向前紧凑
  更新所有内部指针 (DDIndex)
  保持年龄顺序不变
```

**与 .NET GC 的集成**:
- DD 对象由 .NET GC 追踪
- 当 DD 对象被回收后，WeakReference 失效
- DDManager 的 GC 发现失效的引用后释放对应的内部节点
- 用户无需手动释放 — 无 Dispose()、无引用计数

### 6.3 运算缓存

三种独立缓存提升重复运算性能：

```
1参数缓存 (SatCount):
  Key: DDIndex
  Value: double (解数量)

2参数缓存 (And/Or/Exists/Replace):
  Key: (DDIndex, DDIndex, DDOperation)
  Value: DDIndex (结果)

3参数缓存 (ITE - If-Then-Else):
  Key: (DDIndex, DDIndex, DDIndex)
  Value: DDIndex (结果)
```

**交换律优化**: 对于 And/Or 等交换律操作，参数排序后缓存：
```csharp
// And(x, y) 和 And(y, x) 命中同一缓存项
var arg = xidx < yidx ? new OperationArg2(x, y, op)
                      : new OperationArg2(y, x, op);
```

### 6.4 Or 操作的实现

Or 通过 De Morgan 定律复用 And：

```csharp
// Or(x, y) = ¬(¬x ∧ ¬y)
internal DDIndex Or(DDIndex x, DDIndex y) {
    return Not(Apply(Not(x), Not(y), DDOperation.And));
}
```

由于 Not 是 O(1)，这不会增加任何额外开销。And 的结果缓存也间接被 Or 复用。

---

## 7. UniqueTable - 哈希唯一表

### 7.1 作用

确保结构共享：两个相同的布尔函数一定有相同的 DDIndex。这是 BDD 正确性和效率的基石。

### 7.2 年龄不变量优化

由于节点按分配顺序存储，UniqueTable 利用这个不变量实现**早期终止**：

```csharp
public DDIndex GetOrAdd(T key) {
    int bucket = hash & mask;
    int i = buckets[bucket];

    while (i >= 0) {
        var entry = entries[i];
        var pos = entry.Value.GetPosition();

        // 年龄不变量: 如果子节点都比当前位置年轻，
        // 那么不可能有更早分配的匹配项
        if (loPos >= pos && hiPos >= pos) {
            break;  // 早期终止!
        }

        if (MemoryPool[pos].Equals(key)) {
            return entry.Value;  // 找到已存在的节点
        }

        i = entry.Next;
    }

    // 未找到，分配新节点
    return FreshNode(key);
}
```

---

## 8. N-Queens 基准实现

### 8.1 变量分配

```csharp
// Queens.cs
VarBool<T>[,] variables = new VarBool<T>[boardSize, boardSize];
for (int i = 0; i < boardSize; i++)
    for (int j = 0; j < boardSize; j++)
        variables[i, j] = manager.CreateBool();
```

N=12: 创建 144 个布尔变量，X[i,j] 表示"第 i 行第 j 列是否放置皇后"。

### 8.2 约束编码

**约束 1: 每行至少一个皇后**
```csharp
for (int i = 0; i < boardSize; i++) {
    DD rowConstraint = manager.False();
    for (int j = 0; j < boardSize; j++) {
        rowConstraint = manager.Or(rowConstraint, X[i,j]);
    }
    encoding = manager.And(encoding, rowConstraint);
}
```

**约束 2: 互斥约束 (列 + 两条对角线)**
```csharp
for (int i = 0; i < boardSize; i++) {
    for (int j = 0; j < boardSize; j++) {
        // 同列互斥
        for (int k = 0; k < boardSize; k++) {
            if (k != j)
                a = manager.And(a, manager.Implies(X[i,j], manager.Not(X[i,k])));
        }
        // 同行互斥
        for (int k = 0; k < boardSize; k++) {
            if (k != i)
                b = manager.And(b, manager.Implies(X[i,j], manager.Not(X[k,j])));
        }
        // 对角线互斥 (两个方向)
        // ...
    }
}
```

`Implies(p, q)` 实现为 `Or(Not(p), q)`，其中 Not 是 O(1) 补边翻转。

### 8.3 结果提取

```csharp
double solutions = manager.SatCount(encoding);   // 解的数量
int nodes = manager.NodeCount(encoding);          // 节点数
```

SatCount 递归遍历 BDD，利用缓存避免重复计算。对于跳过的变量层，通过 `2^(跳过层数)` 进行缩放。

---

## 9. 为什么 CBDD 在 N-Queens 上效果特别好

### 9.1 约束结构的规律性

N-Queens 的约束具有高度规律的结构：

- **行约束**: 每行 N 个变量的 OR (形成链)
- **列互斥**: 同列每对变量的 IMPLIES-NOT
- **对角线互斥**: 沿对角线方向的连续变量互斥

这些约束在变量排序上形成**长链模式**，正是 CBDD 链式约简最擅长压缩的结构。

### 9.2 效果量化

| N | BDD 节点数 | CBDD 节点数 | CBDD 节省率 |
|---|-----------|------------|------------|
| 4 | 2,458 | 772 | 68.6% |
| 8 | ~45,000 | ~3,500 | 92.2% |
| 12 | 435,181 | 98,900 | 77.3% |

相比传统 BDD (CUDD 等 ~2470万节点):
- DD-BDD: 435,181 (98.2% 减少) — 因为补边技术
- DD-CBDD: 98,900 (99.6% 减少) — 补边 + 链式约简

### 9.3 三个技术的贡献分解

```
传统 BDD (CUDD): 24,740,519 节点

  ↓ 补边技术 (Complement Edges)
    消除否定节点，结构共享
    → DD-BDD: 435,181 节点 (减少 98.2%)

  ↓ 链式约简 (Chain Reduction)
    压缩对角线约束的长链
    → DD-CBDD: 98,900 节点 (在 DD-BDD 基础上再减少 77.3%)
```

---

## 10. 使用建议

### 何时选择 BDDNode

- 变量数量 > 32,767
- 问题中变量之间没有明显的链式依赖
- 需要与其他工具兼容标准 BDD 格式

### 何时选择 CBDDNode

- 变量数量 < 32,767
- 约束具有规律的链式结构 (如 N-Queens、网络验证)
- 追求最小节点数和最快速度
- 内存受限的场景

### 使用示例

```csharp
// 选择 CBDD (推荐大多数场景)
var manager = new DDManager<CBDDNode>();

// 或选择 BDD (大变量数场景)
var manager = new DDManager<BDDNode>();

// 以下 API 完全相同，无需修改
var a = manager.CreateBool();
var b = manager.CreateBool();
DD f = manager.And(a.Id(), b.Id());
double count = manager.SatCount(f);
```

---

## 11. 与传统 BDD 库的设计差异

| 设计点 | 传统库 (BuDDy/CUDD) | DecisionDiagrams |
|--------|---------------------|-----------------|
| 语言 | C | C# (.NET) |
| 内存管理 | 手动引用计数 | .NET GC + WeakReference |
| 取反操作 | O(n) 或 O(1) 取决于实现 | O(1) 补边 (所有实现) |
| 节点大小 | 16-24 字节 | 12 字节 |
| 变量重排 | 支持动态重排 | 不支持 (静态排序) |
| 缓存策略 | 全局缓存 | 分类缓存 (1/2/3参数) |
| 泛型节点 | 不支持 | 泛型参数切换 BDD/CBDD |
| 并行 | Sylvan 支持 | 不支持 (单线程) |
| 整数运算 | 需外部实现 | 内置 BitVector 抽象 |

---

## 12. 局限性

1. **不支持动态变量重排**: 变量顺序在创建时固定
2. **CBDD 变量数限制**: 最多 32,767 个变量 (15位编码)
3. **单线程**: 不支持并行操作 (对比 Sylvan)
4. **不支持函数组合** (Functional Composition)
5. **内存翻倍增长**: 2 的幂约束使得内存分配不够灵活
