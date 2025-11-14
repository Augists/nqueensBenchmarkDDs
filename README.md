# Benchmark on all version of BDD and NDD on NQueens

C 语言
1. BuDDy
2. sylvan
3. cudd

Java 语言
1. jdd
2. JSylvan
3. NDD

## 使用方式

### 依赖

在执行脚本前，需提前安装构建工具、pkg-config 以及 GMP 库。例如在 Debian/Ubuntu 上：

```bash
sudo apt update
sudo apt install build-essential pkg-config libgmp-dev openjdk-17-jdk python3 python3-pip
```

若缺少 pkg-config 或 libgmp-dev，JSylvan/Sylvan 的构建会失败。

### 步骤

1. clone 仓库（包含子模块）：
   ```bash
   git clone --recurse-submodules git@github.com:Augists/nqueensBenchmarkDDs.git
   ```
   若忘记加 `--recurse-submodules`，clone 后可执行：
   ```bash
   git submodule update --init --recursive
   ```
2. 运行测试
   ```bash
   python3 scripts/run_nqueens_benchmarks.py
   ```
   - 默认测试 N=4~12，若二进制尚未编译会自动构建
   - 常用参数：`--sizes 8 9 10` 控制规模；`--workers 0` 让 Sylvan/JSylvan 自动检测核心数（默认即 0）；`--targets BuDDy Sylvan NDD` 指定只运行部分实现（默认 `all`）
   - 结果会输出到 `results/nqueens_metrics.csv`
3. 绘图
   ```bash
   python3 scripts/plot_nqueens_results.py --input results/nqueens_metrics.csv --output results
   ```
   会生成 `nqueens_time_sec.png`、`nqueens_max_rss_kb.png`、`nqueens_nodes.png`
