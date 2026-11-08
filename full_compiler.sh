#!/usr/bin/env bash
set -e

SRC="$1"
OUT_BIN="${2:-${SRC%.*}}"

if [ -z "$SRC" ]; then
    echo "Usage: $0 <source.txt> [output_binary]"
    exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

LL_FILE="$TMP_DIR/out.ll"
OBJ_FILE="$TMP_DIR/out.o"

python3 compiler.py "$SRC" "$LL_FILE"
llc -filetype=obj -relocation-model=pic "$LL_FILE" -o "$OBJ_FILE"
clang -fPIE "$OBJ_FILE" -o "$OUT_BIN"

