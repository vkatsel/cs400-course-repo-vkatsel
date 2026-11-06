# CS400 Course Repository - Compiler

Compiler implementation for Languages and Compilers Design (CS400).

## Repository Layout

```text
.
├── compiler.py        # Main compiler entry point (parser, AST, checker, codegen)
├── optimizer.py       # AST optimization pass (--remove-unused)
├── lexer.py           # Lexer and token definitions
├── grammar.ebnf       # Formal EBNF grammar definition
├── run.sh             # Convenience script to compile and run in one step
├── examples/          # Example source programs and manual test cases
│   ├── practice6_demo.txt
│   ├── worked_example.txt
│   └── ...
├── tests/             # Automated test suite
│   ├── run_tests.py   # Test runner executing all tests
│   ├── test_lexer.py  # Unit tests for the lexer
│   ├── ok/            # Valid programs expecting 0 exit and specific stdout
│   │   ├── *.txt, *.expected, *.ast
│   ├── err/           # Invalid programs expecting compilation errors
│   │   ├── *.txt, *.expected
│   ├── opt/           # Optimization pass tests
│   │   ├── *.txt, *.astc, *.expected
│   └── fail*.txt      # Legacy top-level error tests
├── ai_usage.txt       # AI usage log for course submissions
├── README.md          # Project documentation
└── .gitignore         # Git ignore rules
```

## Setup & Prerequisites

- Python 3.12+
- `llvmlite` (version `0.49.*`)
- LLVM toolchain (`lli`, `llc`, `clang`)

Activate the course virtual environment:

```bash
source ~/lcd/bin/activate
```

## Running the Compiler

Compile a source program into LLVM IR (with optional `--remove-unused` optimization):

```bash
python3 compiler.py input.txt output.ll
python3 compiler.py --remove-unused input.txt output.ll
```

Print the Abstract Syntax Tree (parse tree or checked/optimized tree):

```bash
python3 compiler.py --ast input.txt
python3 compiler.py --ast-checked input.txt
python3 compiler.py --remove-unused --ast-checked input.txt
```

Print tokenized output (Lexer):

```bash
python3 compiler.py --lex input.txt
```

### Executing the Compiled IR

Using `lli` directly (fastest for debugging):

```bash
lli output.ll
```

Or compiling to native binary via `llc` and `clang`:

```bash
llc -filetype=obj -relocation-model=pic output.ll -o output.o
clang -fPIE output.o -o program && ./program
```

### One-step Compile and Run

You can compile and run any program in one step using `run.sh`:

```bash
./run.sh input.txt
./run.sh --remove-unused input.txt
```

## Running Tests

To run the automated test suite (both without and with `--remove-unused`):

```bash
python3 tests/run_tests.py
python3 tests/run_tests.py --remove-unused
```

## Optimizations

With `--remove-unused`, an iterative pass (`optimizer.py`) runs on the checked AST before code generation, counting reads per variable declaration (`id(decl)`) and calls per global function until a fixpoint is reached where a round removes nothing.

- **Limits of reference/use counting**: A variable that only feeds itself (such as `k := k + 1` when nobody else reads `k`) survives because the right-hand side of `:=` reads `k`, keeping its read count at 1. For the same reason, two unused global functions that call each other in a cycle never reach zero calls and are kept.
- **Who frees a removed subtree**:
  - **Language & memory model**: The compiler is implemented in **Python 3.12 (CPython)**, which uses **reference counting** as its primary memory management mechanism, backed by a cyclic tracing garbage collector (`gc`) for reference cycles.
  - **Parent pointers**: AST nodes only keep downward references to their children (and resolved `DeclNode` targets on variable/assignment nodes) and **do not keep a `parent` pointer**. Because no dead `VarNode` or live `AssignNode` points back to a declaration with 0 reads, a removed `DeclNode` subtree contains no reference cycles. If nodes stored a `parent` pointer, every parent–child edge (`parent <-> child`) would form a cycle, keeping each node's reference count `>= 1` after unlinking until the cyclic collector (`gc.collect()`) ran.
  - **Measurement**: When `Pruner` rebuilds `statements` without an unused `DeclNode`, its reference count drops to `0` and CPython frees the subtree **immediately**, even with the cyclic garbage collector disabled (`gc.disable()`, without calling `gc.collect()`):

```python
import gc, weakref
from compiler import check_ast
from optimizer import remove_unused

gc.disable()
ast = check_ast(b"i32 unused{42}\nexit 0\n")
ref = weakref.ref(ast.statements[0])
assert ref() is not None
remove_unused(ast)
assert ref() is None  # freed immediately by reference counting without gc.collect()
```
