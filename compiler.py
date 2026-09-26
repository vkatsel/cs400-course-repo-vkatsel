"""
Compiler for Practice 3 Language (Parser, AST, and Tree-walk Code Generation).

EBNF Grammar:
    program    ::= { statement } exit ;
    statement  ::= decl | assign ;
    decl       ::= "i32" [ "mut" ] ident "{" expr "}" ;
    assign     ::= ident ":=" expr ;
    exit       ::= "exit" operand ;
    expr       ::= term { ( "+" | "-" ) term } ;
    term       ::= factor { "*" factor } ;
    factor     ::= operand ;
    operand    ::= ident | number ;
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

for _p in (
    "/home/ubuntu/lcd/lib/python3.12/site-packages",
    str(Path.home() / "lcd/lib/python3.12/site-packages"),
):
    if _p not in sys.path and Path(_p).exists():
        sys.path.insert(0, _p)

import llvmlite.binding as llvm
from lexer import CompileError, Token, lex, print_tokens
from llvmlite import ir


@dataclass(slots=True)
class Node:
    line: int
    col: int

    def dump(self, indent: int = 0) -> str:
        raise NotImplementedError

    def accept(self, visitor: Any):
        raise NotImplementedError


@dataclass(slots=True)
class ExprNode(Node):
    type: str | None = field(default=None, init=False)


@dataclass(slots=True)
class ConstNode(ExprNode):
    value: int

    def dump(self, indent: int = 0) -> str:
        return f"{' ' * (indent * 2)}Const {self.value}"

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_const(self)


@dataclass(slots=True)
class BoolNode(ExprNode):
    value: bool

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        return f"{prefix}Bool {'true' if self.value else 'false'}"

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_bool(self)


@dataclass(slots=True)
class VarNode(ExprNode):
    name: str
    decl: "DeclNode | None" = field(default=None, init=False)

    def dump(self, indent: int = 0) -> str:
        return f"{' ' * (indent * 2)}Var {self.name}"

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_var(self)


@dataclass(slots=True)
class BinOpNode(ExprNode):
    op: str
    left: ExprNode
    right: ExprNode

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        return (
            f"{prefix}BinOp {self.op}\n"
            f"{self.left.dump(indent + 1)}\n"
            f"{self.right.dump(indent + 1)}"
        )

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_binop(self)


@dataclass(slots=True)
class StmtNode(Node):
    pass


@dataclass(slots=True)
class DeclNode(StmtNode):
    name: str
    type_name: str
    mutable: bool
    init: ExprNode
    alloca: ir.AllocaInstr | None = field(default=None, init=False)

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        kind = "mut" if self.mutable else "const"
        return f"{prefix}Decl {self.name} {self.type_name} {kind}\n{self.init.dump(indent + 1)}"

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_decl(self)


@dataclass(slots=True)
class AssignNode(StmtNode):
    name: str
    value: ExprNode
    decl: "DeclNode | None" = field(default=None, init=False)

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        return f"{prefix}Assign {self.name}\n{self.value.dump(indent + 1)}"

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_assign(self)


@dataclass(slots=True)
class ExitNode(Node):
    value: ExprNode

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        return f"{prefix}Exit\n{self.value.dump(indent + 1)}"

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_exit(self)


@dataclass(slots=True)
class ProgramNode(Node):
    statements: list[StmtNode]
    exit: ExitNode

    def dump(self, indent: int = 0) -> str:
        lines = ["Program"]
        for stmt in self.statements:
            lines.append(stmt.dump(indent + 1))
        lines.append(self.exit.dump(indent + 1))
        return "\n".join(lines)

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_program(self)


class Parser:
    def __init__(self, raw_lines: list[list[Token]]) -> None:
        self.raw_lines = raw_lines
        self.toks: list[Token] = []
        self.pos: int = 0
        self.last_consumed: Token | None = None

    def peek(self) -> Token | None:
        return self.toks[self.pos] if self.pos < len(self.toks) else None

    def eat(self) -> Token:
        tok = self.toks[self.pos]
        self.pos += 1
        self.last_consumed = tok
        return tok

    def _end_of_line_loc(self) -> tuple[int, int]:
        if self.last_consumed is not None:
            return (
                self.last_consumed.line,
                self.last_consumed.col + len(self.last_consumed.text),
            )
        return (1, 1)

    def parse_factor(self) -> ExprNode:
        tok = self.peek()
        if tok is None:
            line, col = self._end_of_line_loc()
            raise CompileError(
                line, col, "expected a constant or a variable, found end of line"
            )
        if tok.is_number:
            self.eat()
            return ConstNode(tok.line, tok.col, int(tok.text))
        if tok.is_boolean or (tok.is_keyword and tok.text in ("true", "false")):
            self.eat()
            return BoolNode(tok.line, tok.col, tok.text == "true")
        if tok.is_identifier:
            self.eat()
            return VarNode(tok.line, tok.col, tok.text)
        raise CompileError(
            tok.line, tok.col, f"expected a constant or a variable, got '{tok.text}'"
        )

    def parse_operand(self) -> ExprNode:
        return self.parse_factor()

    def parse_term(self) -> ExprNode:
        node = self.parse_factor()
        while True:
            tok = self.peek()
            if tok is not None and tok.is_operator and tok.text == "*":
                op_tok = self.eat()
                right = self.parse_factor()
                node = BinOpNode(op_tok.line, op_tok.col, op_tok.text, node, right)
            else:
                break
        return node

    def parse_arith(self) -> ExprNode:
        node = self.parse_term()
        while True:
            tok = self.peek()
            if tok is not None and tok.is_operator and tok.text in ("+", "-"):
                op_tok = self.eat()
                right = self.parse_term()
                node = BinOpNode(op_tok.line, op_tok.col, op_tok.text, node, right)
            else:
                break
        return node

    def parse_expr(self) -> ExprNode:
        node = self.parse_arith()
        tok = self.peek()
        if tok is not None and tok.is_operator and tok.text in ("==", "!="):
            op_tok = self.eat()
            right = self.parse_arith()
            node = BinOpNode(op_tok.line, op_tok.col, op_tok.text, node, right)
            next_tok = self.peek()
            if next_tok is not None and next_tok.is_operator and next_tok.text in ("==", "!="):
                raise CompileError(
                    next_tok.line,
                    next_tok.col,
                    "multiple comparisons in one expression are not allowed",
                )
        return node

    def parse_decl(self) -> DeclNode:
        type_tok = self.eat()  # "i32", "i64", "bool"
        type_name = type_tok.text
        mutable = False
        tok = self.peek()
        if tok is not None and tok.text == "mut":
            self.eat()
            mutable = True

        name_tok = self.peek()
        if name_tok is None:
            line, col = self._end_of_line_loc()
            raise CompileError(line, col, "expected a variable name, found end of line")
        if not name_tok.is_identifier:
            raise CompileError(
                name_tok.line,
                name_tok.col,
                f"expected a variable name, got '{name_tok.text}'",
            )
        self.eat()

        open_brace = self.peek()
        if open_brace is None or open_brace.text != "{":
            raise CompileError(
                name_tok.line,
                name_tok.col,
                f"variable '{name_tok.text}' needs an initialiser in {{}}",
            )
        self.eat()

        init_expr = self.parse_expr()

        close_brace = self.peek()
        if close_brace is None or close_brace.text != "}":
            line, col = (
                self._end_of_line_loc()
                if close_brace is None
                else (close_brace.line, close_brace.col)
            )
            raise CompileError(line, col, "expected '}'")
        self.eat()

        if (extra := self.peek()) is not None:
            raise CompileError(
                extra.line, extra.col, f"unexpected '{extra.text}' after the statement"
            )

        return DeclNode(
            name_tok.line, name_tok.col, name_tok.text, type_name, mutable, init_expr
        )

    def parse_assign(self) -> AssignNode:
        name_tok = self.eat()
        assign_op = self.peek()
        if assign_op is None:
            line, col = self._end_of_line_loc()
            raise CompileError(
                line, col, f"expected ':=' after '{name_tok.text}', found end of line"
            )
        if assign_op.text != ":=":
            raise CompileError(
                assign_op.line,
                assign_op.col,
                f"expected ':=' after '{name_tok.text}', got '{assign_op.text}'",
            )
        self.eat()

        value_expr = self.parse_expr()

        if (extra := self.peek()) is not None:
            raise CompileError(
                extra.line, extra.col, f"unexpected '{extra.text}' after the statement"
            )

        return AssignNode(name_tok.line, name_tok.col, name_tok.text, value_expr)

    def parse_exit(self) -> ExitNode:
        exit_tok = self.eat()
        operand = self.parse_factor()
        if (extra := self.peek()) is not None:
            raise CompileError(
                extra.line, extra.col, f"unexpected '{extra.text}' after the statement"
            )
        return ExitNode(exit_tok.line, exit_tok.col, operand)

    def parse_statement(self) -> StmtNode:
        tok = self.peek()
        if tok is None:
            line, col = self._end_of_line_loc()
            raise CompileError(line, col, "unexpected end of line")
        if tok.text in ("i32", "i64", "bool"):
            return self.parse_decl()
        if tok.is_identifier:
            return self.parse_assign()
        raise CompileError(
            tok.line, tok.col, f"cannot start a statement with '{tok.text}'"
        )

    def parse_program(self) -> ProgramNode:
        stmts: list[StmtNode] = []
        exit_node: ExitNode | None = None
        last_line_number = 1

        for raw_toks in self.raw_lines:
            tokens = [t for t in raw_toks if not t.is_endline]
            if not tokens:
                continue

            first_tok = tokens[0]
            last_line_number = first_tok.line

            if exit_node is not None:
                raise CompileError(first_tok.line, first_tok.col, "code after exit")

            self.toks = tokens
            self.pos = 0
            self.last_consumed = None

            tok = self.peek()
            if tok is not None and tok.text == "exit":
                exit_node = self.parse_exit()
            else:
                stmts.append(self.parse_statement())

        if exit_node is None:
            raise CompileError(last_line_number, 1, "missing exit statement")

        return ProgramNode(1, 1, stmts, exit_node)


class SemanticChecker:
    def __init__(self) -> None:
        self.symbols: dict[str, DeclNode] = {}

    def visit_const(self, node: ConstNode) -> str:
        if 0 <= node.value <= 2147483647:
            node.type = "i32"
        elif node.value <= 9223372036854775807:
            node.type = "i64"
        else:
            raise CompileError(
                node.line, node.col, f"constant {node.value} does not fit in i64"
            )
        return node.type

    def visit_bool(self, node: BoolNode) -> str:
        node.type = "bool"
        return node.type

    def visit_var(self, node: VarNode) -> str:
        if node.name not in self.symbols:
            raise CompileError(
                node.line,
                node.col,
                f"variable '{node.name}' is used before its declaration",
            )
        node.decl = self.symbols[node.name]
        node.type = node.decl.type_name
        return node.type

    def visit_binop(self, node: BinOpNode) -> str:
        lt = node.left.accept(self)
        rt = node.right.accept(self)
        if node.op in ("+", "-", "*"):
            if lt == "bool" or rt == "bool":
                raise CompileError(
                    node.line, node.col, f"cannot apply '{node.op}' to bool"
                )
            node.type = "i64" if (lt == "i64" or rt == "i64") else "i32"
            return node.type
        elif node.op in ("==", "!="):
            if (lt in ("i32", "i64") and rt in ("i32", "i64")) or (
                lt == "bool" and rt == "bool"
            ):
                node.type = "bool"
                return node.type
            raise CompileError(node.line, node.col, f"cannot compare {lt} with {rt}")
        raise CompileError(node.line, node.col, f"unsupported operator '{node.op}'")

    def check_assignable(
        self, expr: ExprNode, want: str, at: Node, what: str
    ) -> None:
        have = expr.type
        if have == want or (have == "i32" and want == "i64"):
            return
        if isinstance(expr, ConstNode) and want == "i32" and have == "i64":
            raise CompileError(
                expr.line,
                expr.col,
                f"constant {expr.value} does not fit in i32",
            )
        raise CompileError(
            at.line,
            at.col,
            f"cannot {what} of type {want} with a value of type {have}",
        )

    def visit_decl(self, node: DeclNode) -> None:
        if node.name in self.symbols:
            raise CompileError(
                node.line, node.col, f"variable '{node.name}' is already declared"
            )
        node.init.accept(self)
        self.check_assignable(
            node.init, node.type_name, node, f"initialise '{node.name}'"
        )
        self.symbols[node.name] = node

    def visit_assign(self, node: AssignNode) -> None:
        if node.name not in self.symbols:
            raise CompileError(
                node.line,
                node.col,
                f"variable '{node.name}' is used before its declaration",
            )
        node.decl = self.symbols[node.name]
        if not node.decl.mutable:
            raise CompileError(
                node.line, node.col, f"cannot assign to '{node.name}': it is not mut"
            )
        node.value.accept(self)
        self.check_assignable(
            node.value, node.decl.type_name, node, f"assign to '{node.name}'"
        )

    def visit_exit(self, node: ExitNode) -> None:
        val_type = node.value.accept(self)
        if val_type not in ("i32", "i64", "bool"):
            raise CompileError(
                node.value.line,
                node.value.col,
                f"unsupported exit type '{val_type}'",
            )

    def visit_program(self, node: ProgramNode) -> None:
        for stmt in node.statements:
            stmt.accept(self)
        node.exit.accept(self)


class CodeGenVisitor:
    def __init__(self, module: ir.Module) -> None:
        self.module = module
        self.i64_type = ir.IntType(64)
        self.i32_type = ir.IntType(32)
        self.i1_type = ir.IntType(1)
        self.i8_type = ir.IntType(8)

        self.main_fn = ir.Function(
            self.module, ir.FunctionType(self.i32_type, []), name="main"
        )
        self.builder = ir.IRBuilder(self.main_fn.append_basic_block("entry"))

        self.printf_fn = ir.Function(
            self.module,
            ir.FunctionType(self.i32_type, [ir.PointerType(self.i8_type)], var_arg=True),
            name="printf",
        )

        fmt_int_bytes = b"Program exit with result %lld\n\0"
        self.fmt_int_var = self._create_global_string("fmt_int", fmt_int_bytes)

        fmt_bool_bytes = b"Program exit with result %s\n\0"
        self.fmt_bool_var = self._create_global_string("fmt_bool", fmt_bool_bytes)

        self.str_true_var = self._create_global_string("str_true", b"true\0")
        self.str_false_var = self._create_global_string("str_false", b"false\0")

    def _create_global_string(self, name: str, data: bytes) -> ir.GlobalVariable:
        arr_t = ir.ArrayType(self.i8_type, len(data))
        var = ir.GlobalVariable(self.module, arr_t, name=name)
        var.linkage = "private"
        var.global_constant = True
        var.initializer = ir.Constant(arr_t, bytearray(data))
        return var

    def _llvm_type(self, type_name: str) -> ir.Type:
        match type_name:
            case "i64":
                return self.i64_type
            case "bool":
                return self.i1_type
            case _:
                return self.i32_type

    def coerce(self, value: ir.Value, have: str | None, want: str | None) -> ir.Value:
        if have == "i32" and want == "i64":
            return self.builder.sext(value, self.i64_type, name="wide")
        return value

    def visit_const(self, node: ConstNode) -> ir.Value:
        if node.type == "i64":
            return ir.Constant(self.i64_type, node.value)
        return ir.Constant(self.i32_type, node.value)

    def visit_bool(self, node: BoolNode) -> ir.Value:
        return ir.Constant(self.i1_type, 1 if node.value else 0)

    def visit_var(self, node: VarNode) -> ir.Value:
        assert node.decl is not None and node.decl.alloca is not None
        return self.builder.load(node.decl.alloca, name=node.name)

    def visit_binop(self, node: BinOpNode) -> ir.Value:
        left_val = node.left.accept(self)
        right_val = node.right.accept(self)
        match node.op:
            case "+":
                left_val = self.coerce(left_val, node.left.type, node.type)
                right_val = self.coerce(right_val, node.right.type, node.type)
                return self.builder.add(left_val, right_val)
            case "-":
                left_val = self.coerce(left_val, node.left.type, node.type)
                right_val = self.coerce(right_val, node.right.type, node.type)
                return self.builder.sub(left_val, right_val)
            case "*":
                left_val = self.coerce(left_val, node.left.type, node.type)
                right_val = self.coerce(right_val, node.right.type, node.type)
                return self.builder.mul(left_val, right_val)
            case "==" | "!=":
                cmp_type = (
                    "i64"
                    if (node.left.type == "i64" or node.right.type == "i64")
                    else node.left.type
                )
                left_val = self.coerce(left_val, node.left.type, cmp_type)
                right_val = self.coerce(right_val, node.right.type, cmp_type)
                return self.builder.icmp_signed(node.op, left_val, right_val)
            case _:
                raise CompileError(node.line, node.col, f"unsupported operator '{node.op}'")

    def visit_decl(self, node: DeclNode) -> None:
        init_val = node.init.accept(self)
        init_val = self.coerce(init_val, node.init.type, node.type_name)
        slot = self.builder.alloca(self._llvm_type(node.type_name), name=node.name)
        self.builder.store(init_val, slot)
        node.alloca = slot

    def visit_assign(self, node: AssignNode) -> None:
        assert node.decl is not None and node.decl.alloca is not None
        val = node.value.accept(self)
        val = self.coerce(val, node.value.type, node.decl.type_name)
        self.builder.store(val, node.decl.alloca)

    def visit_exit(self, node: ExitNode) -> None:
        exit_val = node.value.accept(self)
        val_type = node.value.type
        if val_type in ("i32", "i64"):
            wide_val = self.coerce(exit_val, val_type, "i64")
            fmt_ptr = self.builder.bitcast(self.fmt_int_var, ir.PointerType(self.i8_type))
            self.builder.call(self.printf_fn, [fmt_ptr, wide_val])
        elif val_type == "bool":
            fmt_ptr = self.builder.bitcast(self.fmt_bool_var, ir.PointerType(self.i8_type))
            true_ptr = self.builder.bitcast(self.str_true_var, ir.PointerType(self.i8_type))
            false_ptr = self.builder.bitcast(self.str_false_var, ir.PointerType(self.i8_type))
            selected_str = self.builder.select(exit_val, true_ptr, false_ptr, name="bool_str")
            self.builder.call(self.printf_fn, [fmt_ptr, selected_str])
        self.builder.ret(ir.Constant(self.i32_type, 0))

    def visit_program(self, node: ProgramNode) -> None:
        for stmt in node.statements:
            stmt.accept(self)
        node.exit.accept(self)


def parse_ast(source_bytes: bytes) -> ProgramNode:
    token_lines = lex(source_bytes)
    return Parser(token_lines).parse_program()


def compile_source(source_bytes: bytes) -> ir.Module:
    ast = parse_ast(source_bytes)
    checker = SemanticChecker()
    checker.visit_program(ast)

    module = ir.Module(name="practice4")
    module.triple = llvm.get_default_triple()

    codegen = CodeGenVisitor(module)
    codegen.visit_program(ast)
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

    if len(sys.argv) == 3 and sys.argv[1] == "--ast":
        try:
            with open(sys.argv[2], "rb") as f:
                content = f.read()
            ast = parse_ast(content)
            print(ast.dump())
            sys.exit(0)
        except CompileError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
        except FileNotFoundError:
            print(f"Error: file '{sys.argv[2]}' not found", file=sys.stderr)
            sys.exit(1)

    if len(sys.argv) != 3:
        print(
            "Usage: python3 compiler.py <input.txt> <output.ll> "
            "OR python3 compiler.py --ast <input.txt> "
            "OR python3 compiler.py --lex <input.txt>",
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
