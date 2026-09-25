# CS400 Course Repository - Compiler

Compiler implementation for Languages and Compilers Design (CS400).

## Repository Layout

```text
.
├── compiler.py        # Main compiler entry point (parser, AST, code generation)
├── grammar.ebnf       # Formal EBNF grammar definition
├── examples/          # Example source programs and token dumps
│   ├── worked_example.txt
│   └── worked_example.tokens
├── tests/             # Test cases and expected outputs
│   ├── run_tests.py   # Automated test runner
│   ├── *.txt          # Source test programs
│   ├── *.expected     # Expected outputs / error messages
│   └── *.ast          # Reference AST dumps for valid programs
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

Compile a source program into LLVM IR:

```bash
python3 compiler.py input.txt output.ll
```

Print the Abstract Syntax Tree (AST):

```bash
python3 compiler.py --ast input.txt
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
```

## Running Tests

To run the automated test suite:

```bash
python3 tests/run_tests.py
```
