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


@dataclass(slots=True)
class Node:
    line: int
    col: int

    def dump(self, indent: int = 0) -> str:
        raise NotImplementedError


@dataclass(slots=True)
class ExprNode(Node):
    pass


@dataclass(slots=True)
class ConstNode(ExprNode):
    value: int

    def dump(self, indent: int = 0) -> str:
        return f"{' ' * (indent * 2)}Const {self.value}"


@dataclass(slots=True)
class VarNode(ExprNode):
    name: str

    def dump(self, indent: int = 0) -> str:
        return f"{' ' * (indent * 2)}Var {self.name}"


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


@dataclass(slots=True)
class StmtNode(Node):
    pass


@dataclass(slots=True)
class DeclNode(StmtNode):
    name: str
    mutable: bool
    init: ExprNode

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        kind = "mut" if self.mutable else "const"
        return f"{prefix}Decl {self.name} {kind}\n{self.init.dump(indent + 1)}"


@dataclass(slots=True)
class AssignNode(StmtNode):
    name: str
    value: ExprNode

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        return f"{prefix}Assign {self.name}\n{self.value.dump(indent + 1)}"


@dataclass(slots=True)
class ExitNode(StmtNode):
    value: ExprNode

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        return f"{prefix}Exit\n{self.value.dump(indent + 1)}"


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

    def parse_operand(self) -> ExprNode:
        tok = self.peek()
        if tok is None:
            line, col = self._end_of_line_loc()
            raise CompileError(
                line, col, "expected a constant or a variable, found end of line"
            )
        if tok.is_number:
            self.eat()
            return ConstNode(tok.line, tok.col, int(tok.text))
        if tok.is_identifier:
            self.eat()
            return VarNode(tok.line, tok.col, tok.text)
        raise CompileError(
            tok.line, tok.col, f"expected a constant or a variable, got '{tok.text}'"
        )

    def parse_factor(self) -> ExprNode:
        return self.parse_operand()

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

    def parse_expr(self) -> ExprNode:
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

    def parse_decl(self) -> DeclNode:
        self.eat()  # "i32"
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

        return DeclNode(name_tok.line, name_tok.col, name_tok.text, mutable, init_expr)

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
        operand = self.parse_operand()
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
        if tok.text == "i32":
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


class CodeGenVisitor:
    def __init__(self, module: ir.Module) -> None:
        self.module = module
        self.i32_type = ir.IntType(32)
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

        fmt_bytes = b"Program exit with result %d\n\0"
        self.fmt_var = ir.GlobalVariable(
            self.module, ir.ArrayType(self.i8_type, len(fmt_bytes)), name="fmt"
        )
        self.fmt_var.linkage = "private"
        self.fmt_var.global_constant = True
        self.fmt_var.initializer = ir.Constant(
            ir.ArrayType(self.i8_type, len(fmt_bytes)), bytearray(fmt_bytes)
        )

        self.symbols: dict[str, Symbol] = {}

    def visit_expr(self, node: ExprNode) -> ir.Value:
        match node:
            case ConstNode(value=val):
                return ir.Constant(self.i32_type, val)
            case VarNode(line=l, col=c, name=name):
                if name not in self.symbols:
                    raise CompileError(
                        l, c, f"variable '{name}' is used before its declaration"
                    )
                return self.builder.load(self.symbols[name].alloca, name=name)
            case BinOpNode(line=l, col=c, op=op, left=left, right=right):
                left_val = self.visit_expr(left)
                right_val = self.visit_expr(right)
                match op:
                    case "+":
                        return self.builder.add(left_val, right_val)
                    case "-":
                        return self.builder.sub(left_val, right_val)
                    case "*":
                        return self.builder.mul(left_val, right_val)
                    case _:
                        raise CompileError(l, c, f"unsupported operator '{op}'")
            case _:
                raise CompileError(node.line, node.col, "unknown expression node")

    def visit_decl(self, node: DeclNode) -> None:
        if node.name in self.symbols:
            raise CompileError(
                node.line, node.col, f"variable '{node.name}' is already declared"
            )
        init_val = self.visit_expr(node.init)
        slot = self.builder.alloca(self.i32_type, name=node.name)
        self.builder.store(init_val, slot)
        self.symbols[node.name] = Symbol(
            node.name, node.mutable, slot, node.line, node.col
        )

    def visit_assign(self, node: AssignNode) -> None:
        if node.name not in self.symbols:
            raise CompileError(
                node.line,
                node.col,
                f"variable '{node.name}' is used before its declaration",
            )
        sym = self.symbols[node.name]
        if not sym.is_mut:
            raise CompileError(
                node.line, node.col, f"cannot assign to '{node.name}': it is not mut"
            )
        val = self.visit_expr(node.value)
        self.builder.store(val, sym.alloca)

    def visit_exit(self, node: ExitNode) -> None:
        exit_val = self.visit_expr(node.value)
        fmt_ptr = self.builder.bitcast(self.fmt_var, ir.PointerType(self.i8_type))
        self.builder.call(self.printf_fn, [fmt_ptr, exit_val])
        self.builder.ret(ir.Constant(self.i32_type, 0))

    def visit_program(self, node: ProgramNode) -> None:
        for stmt in node.statements:
            match stmt:
                case DeclNode():
                    self.visit_decl(stmt)
                case AssignNode():
                    self.visit_assign(stmt)
        self.visit_exit(node.exit)


def parse_ast(source_bytes: bytes) -> ProgramNode:
    token_lines = lex(source_bytes)
    return Parser(token_lines).parse_program()


def compile_source(source_bytes: bytes) -> ir.Module:
    ast = parse_ast(source_bytes)
    module = ir.Module(name="practice3")
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
