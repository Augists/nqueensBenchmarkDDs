#!/bin/bash
# Setup script for DecisionDiagrams benchmark integration
set -e

echo "=== Setting up DecisionDiagrams for benchmark ==="
echo ""

# Check if dotnet is installed
if ! command -v dotnet &> /dev/null; then
    echo "❌ dotnet is not installed"
    echo "Installing .NET SDK 6.0..."
    sudo pacman -S --needed dotnet-sdk-6.0
    echo "✅ .NET SDK 6.0 installed"
else
    echo "✅ dotnet is already installed"
    dotnet --version
fi

echo ""
echo "Building DecisionDiagrams..."
cd DecisionDiagrams
dotnet build -c Release DecisionDiagrams.sln

echo ""
echo "Testing DecisionDiagrams with N=8..."
cd DecisionDiagrams.Bench/bin/Release/net6.0
dotnet DecisionDiagrams.Bench.dll 8

echo ""
echo "=== Setup complete! ==="
echo ""
echo "You can now run benchmarks with:"
echo "  python3 scripts/run_nqueens_benchmarks.py --targets DD-BDD DD-CBDD"
echo "  python3 scripts/run_nqueens_benchmarks.py --targets all"
