#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Set PYTHONPATH / activate virtualenv if available
if [ -d "$HOME/lcd/lib/python3.12/site-packages" ]; then
    export PYTHONPATH="$HOME/lcd/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}"
elif [ -d "/home/ubuntu/lcd/lib/python3.12/site-packages" ]; then
    export PYTHONPATH="/home/ubuntu/lcd/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}"
fi

if [ -f "$DIR/.venv/bin/activate" ]; then
    source "$DIR/.venv/bin/activate" || true
elif [ -f "$HOME/lcd/bin/activate" ]; then
    source "$HOME/lcd/bin/activate" || true
elif [ -f "/home/ubuntu/lcd/bin/activate" ]; then
    source "/home/ubuntu/lcd/bin/activate" || true
fi

# If no arguments or test flag, run the test runner
if [ $# -eq 0 ] || [ "$1" = "test" ] || [ "$1" = "--tests" ] || [ "$1" = "-t" ]; then
    exec python3 "$DIR/tests/run_tests.py"
fi

# If --ast or --lex flag, run compiler directly and exit
if [ "$1" = "--ast" ] || [ "$1" = "--lex" ]; then
    exec python3 "$DIR/compiler.py" "$@"
fi

INPUT="$1"
OUTPUT="${2:-/tmp/output.ll}"

# Step 1: Compile to LLVM IR
python3 "$DIR/compiler.py" "$INPUT" "$OUTPUT"

# Determine input pipe if .in file exists and stdin is a terminal
IN_FILE="${INPUT%.*}.in"
INPUT_REDIR=""
if [ -f "$IN_FILE" ] && [ -t 0 ]; then
    exec < "$IN_FILE"
fi

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
