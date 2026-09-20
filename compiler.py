import sys
from dataclasses import dataclass

import llvmlite.binding as llvm
from lexer import CompileError, Token, lex, print_tokens
from llvmlite import ir


@dataclass(slots=True)
class Symbol:
    name: str
    is_mut: bool
    alloca: ir.AllocaInstr
    line: int
    col: int


def resolve_operand(
    tok: Token, symbols: dict[str, Symbol], builder: ir.IRBuilder, i32_type: ir.IntType
) -> ir.Value:
    if tok.is_number:
        return ir.Constant(i32_type, int(tok.text))
    if tok.is_identifier:
        if tok.text not in symbols:
            raise CompileError(
                tok.line,
                tok.col,
                f"variable '{tok.text}' is used before its declaration",
            )
        return builder.load(symbols[tok.text].alloca, name=tok.text)
    raise CompileError(
        tok.line, tok.col, f"expected variable or integer constant, got '{tok.text}'"
    )


def parse_and_build_expr(
    expr_tokens: list[Token],
    symbols: dict[str, Symbol],
    builder: ir.IRBuilder,
    i32_type: ir.IntType,
) -> ir.Value:
    match expr_tokens:
        case [single_tok]:
            return resolve_operand(single_tok, symbols, builder, i32_type)
        case [left_tok, op_tok, right_tok] if op_tok.is_operator:
            left_val = resolve_operand(left_tok, symbols, builder, i32_type)
            right_val = resolve_operand(right_tok, symbols, builder, i32_type)
            match op_tok.text:
                case "+":
                    return builder.add(left_val, right_val)
                case "-":
                    return builder.sub(left_val, right_val)
                case "*":
                    return builder.mul(left_val, right_val)
                case _:
                    raise CompileError(
                        op_tok.line, op_tok.col, f"unsupported operator '{op_tok.text}'"
                    )
        case _:
            first = expr_tokens[0] if expr_tokens else None
            line = first.line if first else 1
            col = first.col if first else 1
            raise CompileError(line, col, "malformed expression")


def compile_source(source_bytes: bytes) -> ir.Module:
    i32_type = ir.IntType(32)
    i8_type = ir.IntType(8)

    module = ir.Module(name="practice2")
    module.triple = llvm.get_default_triple()

    main_fn = ir.Function(module, ir.FunctionType(i32_type, []), name="main")
    builder = ir.IRBuilder(main_fn.append_basic_block("entry"))

    printf_fn = ir.Function(
        module,
        ir.FunctionType(i32_type, [ir.PointerType(i8_type)], var_arg=True),
        name="printf",
    )

    fmt_bytes = b"Program exit with result %d\n\0"
    fmt_var = ir.GlobalVariable(
        module, ir.ArrayType(i8_type, len(fmt_bytes)), name="fmt"
    )
    fmt_var.linkage = "private"
    fmt_var.global_constant = True
    fmt_var.initializer = ir.Constant(
        ir.ArrayType(i8_type, len(fmt_bytes)), bytearray(fmt_bytes)
    )

    token_lines = lex(source_bytes)
    symbols: dict[str, Symbol] = {}
    has_exit = False
    last_line_number = 1

    for raw_tokens in token_lines:
        tokens = [t for t in raw_tokens if not t.is_endline]
        if not tokens:
            continue

        first_tok = tokens[0]
        last_line_number = first_tok.line

        if has_exit:
            raise CompileError(first_tok.line, first_tok.col, "code after exit")

        match tokens:
            case [
                Token(text="i32"),
                Token(text="mut"),
                var_tok,
                Token(text="{"),
                *init_tokens,
                Token(text="}"),
            ] if var_tok.is_identifier:
                name = var_tok.text
                if name in symbols:
                    raise CompileError(
                        var_tok.line,
                        var_tok.col,
                        f"variable '{name}' is already declared",
                    )
                init_val = parse_and_build_expr(init_tokens, symbols, builder, i32_type)
                slot = builder.alloca(i32_type, name=name)
                builder.store(init_val, slot)
                symbols[name] = Symbol(name, True, slot, var_tok.line, var_tok.col)

            case [
                Token(text="i32"),
                var_tok,
                Token(text="{"),
                *init_tokens,
                Token(text="}"),
            ] if var_tok.is_identifier:
                name = var_tok.text
                if name in symbols:
                    raise CompileError(
                        var_tok.line,
                        var_tok.col,
                        f"variable '{name}' is already declared",
                    )
                init_val = parse_and_build_expr(init_tokens, symbols, builder, i32_type)
                slot = builder.alloca(i32_type, name=name)
                builder.store(init_val, slot)
                symbols[name] = Symbol(name, False, slot, var_tok.line, var_tok.col)

            case [Token(text="i32"), Token(text="mut"), var_tok, *_] if (
                var_tok.is_identifier
            ):
                raise CompileError(
                    var_tok.line,
                    var_tok.col,
                    f"variable '{var_tok.text}' needs an initialiser in {{}}",
                )

            case [Token(text="i32"), var_tok, *_] if var_tok.is_identifier:
                raise CompileError(
                    var_tok.line,
                    var_tok.col,
                    f"variable '{var_tok.text}' needs an initialiser in {{}}",
                )

            case [lhs_tok, Token(text=":="), *rhs_tokens] if lhs_tok.is_identifier:
                name = lhs_tok.text
                if name not in symbols:
                    raise CompileError(
                        lhs_tok.line,
                        lhs_tok.col,
                        f"variable '{name}' is used before its declaration",
                    )
                sym = symbols[name]
                if not sym.is_mut:
                    raise CompileError(
                        lhs_tok.line,
                        lhs_tok.col,
                        f"cannot assign to '{name}': it is not mut",
                    )
                rhs_val = parse_and_build_expr(rhs_tokens, symbols, builder, i32_type)
                builder.store(rhs_val, sym.alloca)

            case [Token(text="exit"), exit_tok]:
                exit_val = resolve_operand(exit_tok, symbols, builder, i32_type)
                fmt_ptr = builder.bitcast(fmt_var, ir.PointerType(i8_type))
                builder.call(printf_fn, [fmt_ptr, exit_val])
                builder.ret(ir.Constant(i32_type, 0))
                has_exit = True

            case _:
                raise CompileError(
                    first_tok.line,
                    first_tok.col,
                    "syntax error: unrecognized statement",
                )

    if not has_exit:
        raise CompileError(last_line_number, 1, "missing exit statement")

    return module


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--lex":
        try:
            with open(sys.argv[2], "rb") as f:
                tokens = lex(f.read())
            print_tokens(tokens)
            sys.exit(0)
        except CompileError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
        except FileNotFoundError:
            print(f"Error: file '{sys.argv[2]}' not found", file=sys.stderr)
            sys.exit(1)

    if len(sys.argv) != 3:
        print(
            "Usage: python3 compiler.py <input.txt> <output.ll> OR python3 compiler.py --lex <input.txt>",
            file=sys.stderr,
        )
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    try:
        with open(input_file, "rb") as f:
            content = f.read()
        module = compile_source(content)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(str(module))
    except CompileError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"compilation error: file '{input_file}' not found", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
