#!/usr/bin/env bash
set -e

if [ $# -lt 1 ]; then
    echo "Usage: ./run.sh <source_file.txt> [output.ll]"
    exit 1
fi

INPUT="$1"
OUTPUT="${2:-/tmp/output.ll}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate virtualenv if available
if [ -f "/home/ubuntu/lcd/bin/activate" ]; then
    source "/home/ubuntu/lcd/bin/activate"
elif [ -f "$HOME/lcd/bin/activate" ]; then
    source "$HOME/lcd/bin/activate"
elif [ -f "$DIR/.venv/bin/activate" ]; then
    source "$DIR/.venv/bin/activate"
fi

# Step 1: Compile to LLVM IR
python3 "$DIR/compiler.py" "$INPUT" "$OUTPUT"

# Step 2: Run the IR
if command -v lli &> /dev/null; then
    lli "$OUTPUT"
elif command -v llc &> /dev/null && command -v clang &> /dev/null; then
    OBJ="/tmp/output.o"
    BIN="/tmp/program"
    llc -filetype=obj -relocation-model=pic "$OUTPUT" -o "$OBJ"
    clang -fPIE "$OBJ" -o "$BIN"
    "$BIN"
else
    # Fallback to llvmlite MCJIT JIT runner
    python3 -c "
import llvmlite.binding as llvm
import ctypes

llvm.initialize_native_target()
llvm.initialize_native_asmprinter()

with open(r'$OUTPUT', 'r', encoding='utf-8') as f:
    ll_text = f.read()

llvm_mod = llvm.parse_assembly(ll_text)
target_machine = llvm.Target.from_default_triple().create_target_machine()
engine = llvm.create_mcjit_compiler(llvm_mod, target_machine)
engine.finalize_object()
func_ptr = engine.get_function_address('main')
cfunc = ctypes.CFUNCTYPE(ctypes.c_int32)(func_ptr)
cfunc()
"
fi
