from llvmlite import ir
import llvmlite.binding as llvm
import sys


def error(line_num, msg):
    print(f"compilation error: line {line_num}: {msg}", file=sys.stderr)
    sys.exit(1)


def resolve_operand(token, line_num):
    token = token.strip()
    if token.isdigit():
        return ir.Constant(I32, int(token))
    elif token in symbols:
        return builder.load(symbols[token], name=token)
    else:
        error(line_num, f"undeclared variable: {token}")


if len(sys.argv) == 3 and sys.argv[1] == "--lex":
    from lexer import lex, print_tokens, CompileError

    try:
        with open(sys.argv[2], "rb") as f:
            tokens = lex(f.read())
        print_tokens(tokens)
        sys.exit(0)
    except CompileError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

if len(sys.argv) != 3:
    print(
        "Usage: python3 compiler.py <input_file.txt> <output_file.ll> OR python3 compiler.py --lex <input_file.txt>",
        file=sys.stderr,
    )
    sys.exit(1)

input_file = sys.argv[1]
output_file = sys.argv[2]

I32, I8 = ir.IntType(32), ir.IntType(8)
module = ir.Module(name="practice1")
module.triple = llvm.get_default_triple()

main = ir.Function(module, ir.FunctionType(I32, []), name="main")
builder = ir.IRBuilder(main.append_basic_block("entry"))

printf = ir.Function(
    module, ir.FunctionType(I32, [ir.PointerType(I8)], var_arg=True), name="printf"
)  # declaration only

text = b"Program exit with result %d\n\0"
fmt = ir.GlobalVariable(module, ir.ArrayType(I8, len(text)), name="fmt")
fmt.linkage, fmt.global_constant = "private", True
fmt.initializer = ir.Constant(ir.ArrayType(I8, len(text)), bytearray(text))

symbols = {}

try:
    with open(input_file, "r") as f:
        lines = f.readlines()
except FileNotFoundError:
    error(1, f"file {input_file} not found")

has_exit = False

for line_num, line in enumerate(lines, 1):
    line = line.strip()

    if not line:
        continue

    if has_exit:
        error(line_num, "code after exit")

    if line.startswith("int "):
        parts = line.split(" ")
        name = parts[1] if len(parts) == 2 else error(line_num, "missing variable")

        if not name.isidentifier() or name in ["int", "exit"]:
            error(line_num, f"invalid variable name: {name}")

        if name in symbols:
            error(line_num, f"variable already declared: {name}")
        symbols[name] = builder.alloca(I32, name=name)

    elif ":=" in line:
        parts = line.split(":=")
        if len(parts) != 2:
            error(line_num, f"malformed assignment: {line}")

        lhs = parts[0].strip()
        if lhs not in symbols:
            error(line_num, f"undeclared variable: {lhs}")

        rhs = parts[1].strip()

        # Шукаємо оператор серед +, -, *
        op = None
        for candidate in ["+", "-", "*"]:
            if candidate in rhs:
                op = candidate
                break

        if op:
            op_parts = rhs.split(op)
            if len(op_parts) != 2:
                error(line_num, f"malformed expression: {rhs}")

            left_operand = resolve_operand(op_parts[0], line_num)
            right_operand = resolve_operand(op_parts[1], line_num)

            match op:
                case "+":
                    res = builder.add(left_operand, right_operand)
                case "-":
                    res = builder.sub(left_operand, right_operand)
                case "*":
                    res = builder.mul(left_operand, right_operand)
            builder.store(res, symbols[lhs])
        else:
            val = resolve_operand(rhs, line_num)
            builder.store(val, symbols[lhs])

    elif line.startswith("exit ") or line == "exit":
        parts = line.split()
        if len(parts) != 2:
            error(line_num, "missing variable after exit")
        exit_var = parts[1]
        val = resolve_operand(exit_var, line_num)
        builder.call(printf, [builder.bitcast(fmt, ir.PointerType(I8)), val])
        builder.ret(ir.Constant(I32, 0))
        has_exit = True

    else:
        error(line_num, f"syntax error in line '{line}'")

if not has_exit:
    error(len(lines), "missing exit statement")

with open(output_file, "w") as f:
    f.write(str(module))
