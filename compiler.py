import sys
from dataclasses import dataclass, field
from typing import Any

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
    is_this_field: bool = field(default=False, init=False)
    field_info: Any = field(default=None, init=False)

    def dump(self, indent: int = 0) -> str:
        return f"{' ' * (indent * 2)}Var {self.name}"

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_var(self)


@dataclass(slots=True)
class FieldAccessNode(ExprNode):
    obj_name: str
    fields: list[str]
    target: ExprNode | None = None
    dot_loc: tuple[int, int] | None = None
    decl: "DeclNode | None" = field(default=None, init=False)
    field_indices: list[int] = field(default_factory=list, init=False)
    is_this_field: bool = field(default=False, init=False)
    this_field_info: Any = field(default=None, init=False)

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        if self.target is not None:
            chain = ".".join(self.fields)
            return f"{prefix}Field {chain}\n{self.target.dump(indent + 1)}"
        chain = ".".join([self.obj_name, *self.fields])
        return f"{prefix}Field {chain}"

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_field_access(self)


@dataclass(slots=True)
class StructLiteralNode(ExprNode):
    inits: list[ExprNode]

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        lines = [f"{prefix}StructLiteral"]
        for expr in self.inits:
            lines.append(expr.dump(indent + 1))
        return "\n".join(lines)

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_struct_literal(self)



@dataclass(slots=True)
class CallNode(ExprNode):
    func_name: str
    args: list[ExprNode]
    is_this_call: bool = field(default=False, init=False)
    struct_name: str | None = field(default=None, init=False)
    rewritten_call: "MemberCallNode | None" = field(default=None, init=False)

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        if self.rewritten_call is not None:
            lines = [f"{prefix}CallableCall {self.func_name}"]
            for a in self.args:
                lines.append(a.dump(indent + 1))
            return "\n".join(lines)
        lines = [f"{prefix}Call {self.func_name}"]
        for a in self.args:
            lines.append(a.dump(indent + 1))
        return "\n".join(lines)

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_call(self)


@dataclass(slots=True)
class MemberCallNode(ExprNode):
    target: ExprNode
    func_name: str
    args: list[ExprNode]
    dot_loc: tuple[int, int] | None = None
    struct_name: str | None = field(default=None, init=False)
    is_callable_call: bool = field(default=False, init=False)
    callable_name: str | None = field(default=None, init=False)

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        if self.is_callable_call:
            lines = [f"{prefix}CallableCall {self.callable_name or self.func_name}"]
            lines.append(self.target.dump(indent + 1))
            for a in self.args:
                lines.append(a.dump(indent + 1))
            return "\n".join(lines)
        lines = [f"{prefix}MemberCall {self.func_name}"]
        lines.append(self.target.dump(indent + 1))
        for a in self.args:
            lines.append(a.dump(indent + 1))
        return "\n".join(lines)

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_member_call(self)


@dataclass(slots=True)
class ReadNode(ExprNode):
    def dump(self, indent: int = 0) -> str:
        return f"{' ' * (indent * 2)}Read"

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_read(self)


@dataclass(slots=True)
class StringLiteralNode(ExprNode):
    value: str

    def dump(self, indent: int = 0) -> str:
        return f"{' ' * (indent * 2)}String \"{self.value}\""

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_string_literal(self)


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
class NotNode(ExprNode):
    expr: ExprNode

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        return f"{prefix}Not\n{self.expr.dump(indent + 1)}"

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_not(self)


@dataclass(slots=True)
class FieldDef:
    name: str
    type_name: str
    mutable: bool
    line: int
    col: int


@dataclass(slots=True)
class StructDefNode(Node):
    name: str
    fields: list[FieldDef]
    member_fns: list["MemberFnNode"] = field(default_factory=list)

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        lines = [f"{prefix}Struct {self.name}"]
        for f in self.fields:
            kind = "mut" if f.mutable else "const"
            lines.append(f"{' ' * ((indent + 1) * 2)}Member {f.name} {f.type_name} {kind}")
        for fn in self.member_fns:
            lines.append(fn.dump(indent + 1))
        return "\n".join(lines)

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_struct_def(self)


@dataclass(slots=True)
class ParamDef:
    name: str
    type_name: str
    line: int
    col: int
    alloca: ir.AllocaInstr | None = field(default=None, init=False)
    decl: "DeclNode | None" = field(default=None, init=False)


@dataclass(slots=True)
class FnDefNode(Node):
    name: str
    params: list[ParamDef]
    return_type: str
    body: "BlockNode"

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        params_str = ", ".join(f"{p.type_name} {p.name}" for p in self.params)
        lines = [f"{prefix}Fn {self.name}({params_str}) -> {self.return_type}"]
        lines.append(self.body.dump(indent + 1))
        return "\n".join(lines)

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_fn_def(self)


@dataclass(slots=True)
class MemberFnNode(Node):
    name: str
    params: list[ParamDef]
    return_type: str
    body: "BlockNode"

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        lines = [f"{prefix}MemberFn {self.name} -> {self.return_type}"]
        for p in self.params:
            lines.append(f"{' ' * ((indent + 1) * 2)}Param {p.name} {p.type_name}")
        lines.append(self.body.dump(indent + 1))
        return "\n".join(lines)

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_member_fn(self)


@dataclass(slots=True)
class StmtNode(Node):
    pass


@dataclass(slots=True)
class DeclNode(StmtNode):
    name: str
    type_name: str
    mutable: bool
    inits: list[ExprNode]
    alloca: ir.AllocaInstr | None = field(default=None, init=False)

    @property
    def init(self) -> ExprNode:
        return self.inits[0]

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        kind = "mut" if self.mutable else "const"
        lines = [f"{prefix}Decl {self.name} {self.type_name} {kind}"]
        for expr in self.inits:
            lines.append(expr.dump(indent + 1))
        return "\n".join(lines)

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_decl(self)


@dataclass(slots=True)
class AssignNode(StmtNode):
    name: str
    value: ExprNode
    decl: "DeclNode | None" = field(default=None, init=False)
    is_this_field: bool = field(default=False, init=False)
    field_info: Any = field(default=None, init=False)

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        return f"{prefix}Assign {self.name}\n{self.value.dump(indent + 1)}"

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_assign(self)


@dataclass(slots=True)
class FieldAssignNode(StmtNode):
    obj_name: str
    fields: list[str]
    value: ExprNode
    decl: "DeclNode | None" = field(default=None, init=False)
    field_indices: list[int] = field(default_factory=list, init=False)
    target_type: str | None = field(default=None, init=False)
    is_this_field: bool = field(default=False, init=False)
    this_field_info: Any = field(default=None, init=False)

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        chain = ".".join([self.obj_name, *self.fields])
        return f"{prefix}FieldAssign {chain}\n{self.value.dump(indent + 1)}"

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_field_assign(self)


@dataclass(slots=True)
class ExitNode(Node):
    value: ExprNode

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        return f"{prefix}Exit\n{self.value.dump(indent + 1)}"

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_exit(self)


@dataclass(slots=True)
class BlockNode(Node):
    statements: list[StmtNode]
    exit: ExitNode | None = None

    def dump(self, indent: int = 0) -> str:
        lines = [f"{' ' * (indent * 2)}Block"]
        for stmt in self.statements:
            lines.append(stmt.dump(indent + 1))
        if self.exit is not None:
            lines.append(self.exit.dump(indent + 1))
        return "\n".join(lines)

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_block(self)


@dataclass(slots=True)
class IfNode(StmtNode):
    cond: ExprNode
    then_block: BlockNode
    else_block: BlockNode | None = None

    def dump(self, indent: int = 0) -> str:
        lines = [f"{' ' * (indent * 2)}If"]
        lines.append(self.cond.dump(indent + 1))
        lines.append(self.then_block.dump(indent + 1))
        if self.else_block is not None:
            lines.append(self.else_block.dump(indent + 1))
        return "\n".join(lines)

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_if(self)


@dataclass(slots=True)
class WhileNode(StmtNode):
    cond: ExprNode
    body: BlockNode

    def dump(self, indent: int = 0) -> str:
        lines = [f"{' ' * (indent * 2)}While"]
        lines.append(self.cond.dump(indent + 1))
        lines.append(self.body.dump(indent + 1))
        return "\n".join(lines)

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_while(self)


@dataclass(slots=True)
class PrintNode(StmtNode):
    arg: ExprNode

    def dump(self, indent: int = 0) -> str:
        lines = [f"{' ' * (indent * 2)}Print"]
        lines.append(self.arg.dump(indent + 1))
        return "\n".join(lines)

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_print(self)


@dataclass(slots=True)
class CaptureDef:
    name: str
    mutable: bool
    line: int
    col: int


@dataclass(slots=True)
class LambdaNode(StmtNode):
    name: str
    captures: list[CaptureDef]
    params: list[ParamDef]
    return_type: str
    body: BlockNode
    struct_def: StructDefNode | None = field(default=None, init=False)
    decl_node: DeclNode | None = field(default=None, init=False)

    def dump(self, indent: int = 0) -> str:
        prefix = " " * (indent * 2)
        lines = [f"{prefix}Lambda {self.name} -> {self.return_type}"]
        if self.struct_def is not None and self.decl_node is not None:
            lines.append(self.struct_def.dump(indent + 1))
            lines.append(self.decl_node.dump(indent + 1))
        else:
            for cap in self.captures:
                mut_str = "mut" if cap.mutable else "const"
                lines.append(f"{' ' * ((indent + 1) * 2)}Capture {cap.name} {mut_str}")
            for p in self.params:
                lines.append(f"{' ' * ((indent + 1) * 2)}Param {p.name} {p.type_name}")
            lines.append(self.body.dump(indent + 1))
        return "\n".join(lines)

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_lambda(self)


@dataclass(slots=True)
class ProgramNode(Node):
    struct_defs: list[StructDefNode]
    fn_defs: list[FnDefNode]
    statements: list[StmtNode]
    exit: ExitNode
    lambda_struct_defs: list[StructDefNode] = field(default_factory=list, init=False)

    def dump(self, indent: int = 0) -> str:
        lines = ["Program"]
        for s in self.struct_defs:
            lines.append(s.dump(indent + 1))
        for fn in self.fn_defs:
            lines.append(fn.dump(indent + 1))
        for stmt in self.statements:
            lines.append(stmt.dump(indent + 1))
        lines.append(self.exit.dump(indent + 1))
        return "\n".join(lines)

    def accept(self, visitor: Any) -> Any:
        return visitor.visit_program(self)


class Parser:
    def __init__(self, raw_lines: list[list[Token]]) -> None:
        self.raw_lines = raw_lines
        self.lines: list[list[Token]] = [
            clean for raw in raw_lines if (clean := [t for t in raw if not t.is_endline])
        ]
        self.line_idx: int = 0
        self.toks: list[Token] = []
        self.pos: int = 0
        self.last_consumed: Token | None = None
        self.known_structs: set[str] = set()
        self._set_current_line()

    def current_line(self) -> list[Token] | None:
        return self.lines[self.line_idx] if self.line_idx < len(self.lines) else None

    def peek_line(self) -> list[Token] | None:
        return (
            self.lines[self.line_idx + 1]
            if self.line_idx + 1 < len(self.lines)
            else None
        )

    def next_line(self) -> list[Token] | None:
        self.line_idx += 1
        self._set_current_line()
        return self.current_line()

    def _set_current_line(self) -> None:
        line = self.current_line()
        if line is not None:
            self.toks = line
            self.pos = 0
            self.last_consumed = None
        else:
            self.toks = []
            self.pos = 0
            self.last_consumed = None

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
        cur = self.current_line()
        if cur:
            return (cur[0].line, cur[0].col)
        return (1, 1)

    def parse_factor(self) -> ExprNode:
        tok = self.peek()
        if tok is None:
            line, col = self._end_of_line_loc()
            raise CompileError(
                line, col, "expected a constant or a variable, found end of line"
            )
        if tok.text in ("(", ")"):
            raise CompileError(tok.line, tok.col, f"unexpected byte '{tok.text}'")
        if tok.is_operator and tok.text == "!":
            op_tok = self.eat()
            operand = self.parse_factor()
            return NotNode(op_tok.line, op_tok.col, operand)
        if tok.is_number:
            self.eat()
            return ConstNode(tok.line, tok.col, int(tok.text))
        if tok.is_boolean or (tok.is_keyword and tok.text in ("true", "false")):
            self.eat()
            return BoolNode(tok.line, tok.col, tok.text == "true")
        if tok.text == "read":
            read_tok = self.eat()
            open_paren = self.peek()
            if open_paren is None or open_paren.text != "(":
                if open_paren is None:
                    line, col = self._end_of_line_loc()
                    raise CompileError(line, col, "expected '(' after 'read', found end of line")
                raise CompileError(open_paren.line, open_paren.col, f"expected '(' after 'read', got '{open_paren.text}'")
            self.eat()
            if self.peek() is not None and self.peek().text != ")":
                arg_tok = self.peek()
                raise CompileError(arg_tok.line, arg_tok.col, "read takes no arguments")
            close_paren = self.peek()
            if close_paren is None or close_paren.text != ")":
                if close_paren is None:
                    line, col = self._end_of_line_loc()
                    raise CompileError(line, col, "expected ')' after 'read(', found end of line")
                raise CompileError(close_paren.line, close_paren.col, f"expected ')' after 'read(', got '{close_paren.text}'")
            self.eat()
            return ReadNode(read_tok.line, read_tok.col)
        if tok.text == "print":
            raise CompileError(tok.line, tok.col, "'print' is a statement and has no value")
        if tok.is_string or tok.kind == "string":
            raise CompileError(tok.line, tok.col, "a string literal is only allowed as an argument to 'print'")
        if tok.is_identifier:
            id_tok = self.eat()
            if id_tok.text in self.known_structs:
                raise CompileError(
                    id_tok.line,
                    id_tok.col,
                    f"cannot call member function on type '{id_tok.text}'",
                )

            next_tok = self.peek()
            base_node: ExprNode
            if next_tok is not None and next_tok.text == "(":
                self.eat()
                args: list[ExprNode] = []
                if self.peek() is not None and self.peek().text != ")":
                    args.append(self.parse_expr())
                    while self.peek() is not None and self.peek().text == ",":
                        self.eat()
                        args.append(self.parse_expr())
                close_paren = self.peek()
                if close_paren is None or close_paren.text != ")":
                    if close_paren is None:
                        line, col = self._end_of_line_loc()
                        raise CompileError(line, col, "expected ')', found end of line")
                    raise CompileError(close_paren.line, close_paren.col, "expected ')'")
                self.eat()
                base_node = CallNode(id_tok.line, id_tok.col, id_tok.text, args)
            else:
                base_node = VarNode(id_tok.line, id_tok.col, id_tok.text)

            while self.peek() is not None and self.peek().text == ".":
                dot_tok = self.eat()
                name_tok = self.peek()
                if name_tok is None:
                    line, col = self._end_of_line_loc()
                    raise CompileError(line, col, "expected field or member name after '.', found end of line")
                if name_tok.text in ("read", "print"):
                    raise CompileError(
                        name_tok.line,
                        name_tok.col,
                        f"cannot use reserved keyword '{name_tok.text}' as a member name",
                    )
                if not name_tok.is_identifier:
                    raise CompileError(
                        name_tok.line,
                        name_tok.col,
                        f"expected field or member name after '.', got '{name_tok.text}'",
                    )
                self.eat()

                is_call_target = isinstance(base_node, (CallNode, MemberCallNode)) or (
                    isinstance(base_node, FieldAccessNode) and base_node.target is not None
                )
                dot_loc = (dot_tok.line, dot_tok.col) if is_call_target else None

                if self.peek() is not None and self.peek().text == "(":
                    self.eat()
                    args = []
                    if self.peek() is not None and self.peek().text != ")":
                        args.append(self.parse_expr())
                        while self.peek() is not None and self.peek().text == ",":
                            self.eat()
                            args.append(self.parse_expr())
                    close_paren = self.peek()
                    if close_paren is None or close_paren.text != ")":
                        if close_paren is None:
                            line, col = self._end_of_line_loc()
                            raise CompileError(line, col, "expected ')', found end of line")
                        raise CompileError(close_paren.line, close_paren.col, "expected ')'")
                    self.eat()
                    base_node = MemberCallNode(name_tok.line, name_tok.col, base_node, name_tok.text, args, dot_loc=dot_loc)
                else:
                    if isinstance(base_node, VarNode):
                        base_node = FieldAccessNode(base_node.line, base_node.col, base_node.name, [name_tok.text])
                    elif isinstance(base_node, FieldAccessNode):
                        base_node.fields.append(name_tok.text)
                    else:
                        base_node = FieldAccessNode(name_tok.line, name_tok.col, "", [name_tok.text], target=base_node, dot_loc=dot_loc)

            return base_node
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
        type_tok = self.eat()
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
        if name_tok.text in ("read", "print"):
            raise CompileError(
                name_tok.line,
                name_tok.col,
                f"cannot use reserved keyword '{name_tok.text}' as a variable name",
            )
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

        def parse_init_item() -> ExprNode:
            item_tok = self.peek()
            if item_tok is not None and item_tok.text == "{":
                open_b = self.eat()
                inner_inits: list[ExprNode] = [parse_init_item()]
                while self.peek() is not None and self.peek().text == ",":
                    self.eat()
                    inner_inits.append(parse_init_item())
                close_b = self.peek()
                if close_b is None or close_b.text != "}":
                    if close_b is None:
                        line, col = self._end_of_line_loc()
                        raise CompileError(line, col, "expected '}', found end of line")
                    raise CompileError(close_b.line, close_b.col, "expected '}'")
                self.eat()
                return StructLiteralNode(open_b.line, open_b.col, inner_inits)
            return self.parse_expr()

        inits: list[ExprNode] = [parse_init_item()]
        while True:
            tok = self.peek()
            if tok is not None and tok.text == ",":
                self.eat()
                inits.append(parse_init_item())
            else:
                break

        close_brace = self.peek()
        if close_brace is None or close_brace.text != "}":
            if close_brace is None:
                line, col = self._end_of_line_loc()
                raise CompileError(line, col, "expected '}', found end of line")
            raise CompileError(close_brace.line, close_brace.col, "expected '}'")
        self.eat()

        if (extra := self.peek()) is not None:
            raise CompileError(
                extra.line, extra.col, f"unexpected '{extra.text}' after the statement"
            )

        return DeclNode(
            name_tok.line, name_tok.col, name_tok.text, type_name, mutable, inits
        )

    def parse_assign(self) -> AssignNode | FieldAssignNode:
        name_tok = self.eat()
        if self.peek() is not None and self.peek().text == "(":
            raise CompileError(
                self.peek().line,
                self.peek().col,
                "cannot assign to a call result",
            )
        fields: list[str] = []
        while self.peek() is not None and self.peek().text == ".":
            dot_tok = self.eat()
            field_tok = self.peek()
            if field_tok is None:
                line, col = self._end_of_line_loc()
                raise CompileError(line, col, "expected field name after '.', found end of line")
            if not field_tok.is_identifier:
                raise CompileError(
                    field_tok.line,
                    field_tok.col,
                    f"expected field name after '.', got '{field_tok.text}'",
                )
            self.eat()
            if self.peek() is not None and self.peek().text == "(":
                raise CompileError(
                    self.peek().line,
                    self.peek().col,
                    "cannot assign to a call result",
                )
            fields.append(field_tok.text)

        assign_op = self.peek()
        target_name = name_tok.text if not fields else f"{name_tok.text}.{'.'.join(fields)}"
        if assign_op is None:
            line, col = self._end_of_line_loc()
            raise CompileError(
                line, col, f"expected ':=' after '{target_name}', found end of line"
            )
        if assign_op.text != ":=":
            raise CompileError(
                assign_op.line,
                assign_op.col,
                f"expected ':=' after '{target_name}', got '{assign_op.text}'",
            )
        self.eat()

        value_expr = self.parse_expr()

        if (extra := self.peek()) is not None:
            raise CompileError(
                extra.line, extra.col, f"unexpected '{extra.text}' after the statement"
            )

        if fields:
            return FieldAssignNode(name_tok.line, name_tok.col, name_tok.text, fields, value_expr)
        return AssignNode(name_tok.line, name_tok.col, name_tok.text, value_expr)

    def parse_exit(self) -> ExitNode:
        exit_tok = self.eat()
        operand = self.parse_factor()
        if (extra := self.peek()) is not None:
            raise CompileError(
                extra.line, extra.col, f"unexpected '{extra.text}' after the statement"
            )
        return ExitNode(exit_tok.line, exit_tok.col, operand)

    def parse_block(self, context: str) -> BlockNode:
        cur = self.current_line()
        if cur is None or cur[0].text != "{":
            if cur is not None:
                tok = cur[0]
                raise CompileError(
                    tok.line,
                    tok.col,
                    f"expected '{{' on its own line {context}, got '{tok.text}'",
                )
            line, col = self._end_of_line_loc()
            raise CompileError(
                line, col, f"expected '{{' on its own line {context}, found end of file"
            )

        open_brace = cur[0]
        if len(cur) > 1:
            raise CompileError(
                cur[1].line, cur[1].col, f"unexpected '{cur[1].text}' after '{{'"
            )
        self.next_line()

        cur = self.current_line()
        if cur is None:
            raise CompileError(open_brace.line, open_brace.col, "'{' is never closed")
        if cur[0].text == "}":
            raise CompileError(open_brace.line, open_brace.col, "empty block")

        stmts: list[StmtNode] = []
        block_exit: ExitNode | None = None

        while True:
            cur = self.current_line()
            if cur is None:
                raise CompileError(open_brace.line, open_brace.col, "'{' is never closed")

            first_tok = cur[0]
            if first_tok.text == "}":
                if len(cur) > 1:
                    raise CompileError(
                        cur[1].line, cur[1].col, f"unexpected '{cur[1].text}' after '}}'"
                    )
                self.next_line()
                break

            if block_exit is not None:
                raise CompileError(
                    first_tok.line,
                    first_tok.col,
                    "statement after 'exit' in the same block",
                )

            if first_tok.text == "exit":
                block_exit = self.parse_exit()
                self.next_line()
            else:
                stmt = self.parse_statement()
                stmts.append(stmt)

        return BlockNode(open_brace.line, open_brace.col, stmts, block_exit)

    def parse_if(self) -> IfNode:
        if_tok = self.eat()
        cond = self.parse_expr()

        if (extra := self.peek()) is not None:
            if extra.text == "{":
                raise CompileError(
                    extra.line, extra.col, "unexpected '{' after the statement"
                )
            raise CompileError(
                extra.line, extra.col, f"unexpected '{extra.text}' after the statement"
            )

        self.next_line()
        then_block = self.parse_block(context="after 'if'")

        else_block: BlockNode | None = None
        cur = self.current_line()
        if cur is not None and cur[0].text == "else":
            else_tok = cur[0]
            if len(cur) > 1:
                raise CompileError(
                    cur[1].line, cur[1].col, f"unexpected '{cur[1].text}' after 'else'"
                )
            self.next_line()
            else_block = self.parse_block(context="after 'else'")

        return IfNode(if_tok.line, if_tok.col, cond, then_block, else_block)

    def parse_while(self) -> WhileNode:
        while_tok = self.eat()
        cond = self.parse_expr()

        if (extra := self.peek()) is not None:
            if extra.text == "{":
                raise CompileError(
                    extra.line, extra.col, "unexpected '{' after the statement"
                )
            raise CompileError(
                extra.line, extra.col, f"unexpected '{extra.text}' after the statement"
            )

        self.next_line()
        body = self.parse_block(context="after 'while'")
        return WhileNode(while_tok.line, while_tok.col, cond, body)

    def parse_struct_def(self) -> StructDefNode:
        line = self.current_line()
        assert line is not None
        struct_tok = line[0]
        if len(line) < 2:
            line_no, col = self._end_of_line_loc()
            raise CompileError(line_no, col, "expected struct name, found end of line")
        name_tok = line[1]
        if name_tok.text in ("read", "print"):
            raise CompileError(
                name_tok.line,
                name_tok.col,
                f"cannot use reserved keyword '{name_tok.text}' as a struct name",
            )
        if not name_tok.is_identifier:
            raise CompileError(
                name_tok.line,
                name_tok.col,
                f"expected struct name, got '{name_tok.text}'",
            )
        if len(line) > 2:
            extra = line[2]
            raise CompileError(
                extra.line, extra.col, f"unexpected '{extra.text}' after struct name"
            )
        self.next_line()

        cur = self.current_line()
        if cur is None:
            line_no, col = self._end_of_line_loc()
            raise CompileError(
                line_no, col, "expected '{' on its own line, found end of file"
            )
        if cur[0].text != "{":
            tok = cur[0]
            raise CompileError(
                tok.line,
                tok.col,
                f"expected '{{' on its own line, got '{tok.text}'",
            )
        if len(cur) > 1:
            raise CompileError(
                cur[1].line, cur[1].col, f"unexpected '{cur[1].text}' after '{{'"
            )
        open_brace = cur[0]
        self.next_line()

        fields: list[FieldDef] = []
        member_fns: list[MemberFnNode] = []
        field_names: set[str] = set()
        member_names: set[str] = set()

        while True:
            cur = self.current_line()
            if cur is None:
                raise CompileError(open_brace.line, open_brace.col, "'{' is never closed")
            first_tok = cur[0]
            if first_tok.text == "}":
                if not fields:
                    raise CompileError(open_brace.line, open_brace.col, "empty struct")
                if len(cur) > 1:
                    raise CompileError(
                        cur[1].line, cur[1].col, f"unexpected '{cur[1].text}' after '}}'"
                    )
                self.next_line()
                return StructDefNode(name_tok.line, name_tok.col, name_tok.text, fields, member_fns)

            if first_tok.text == "fn":
                if not fields:
                    raise CompileError(
                        first_tok.line,
                        first_tok.col,
                        "member function before the first field is an error at its fn",
                    )
                break

            idx = 0
            type_tok = cur[idx]
            if not (type_tok.text in ("i32", "i64", "bool") or type_tok.is_identifier):
                raise CompileError(
                    type_tok.line,
                    type_tok.col,
                    f"expected field type, got '{type_tok.text}'",
                )
            idx += 1
            is_mut = False
            if idx < len(cur) and cur[idx].text == "mut":
                is_mut = True
                idx += 1

            if idx >= len(cur):
                last_tok = cur[-1]
                raise CompileError(
                    last_tok.line,
                    last_tok.col + len(last_tok.text),
                    "expected field name, found end of line",
                )

            field_name_tok = cur[idx]
            if field_name_tok.text in ("read", "print"):
                raise CompileError(
                    field_name_tok.line,
                    field_name_tok.col,
                    f"cannot use reserved keyword '{field_name_tok.text}' as a field name",
                )
            if not field_name_tok.is_identifier:
                raise CompileError(
                    field_name_tok.line,
                    field_name_tok.col,
                    f"expected field name, got '{field_name_tok.text}'",
                )
            idx += 1
            if idx < len(cur):
                extra = cur[idx]
                raise CompileError(
                    extra.line,
                    extra.col,
                    f"unexpected '{extra.text}' after field declaration",
                )

            if field_name_tok.text in field_names:
                raise CompileError(
                    field_name_tok.line,
                    field_name_tok.col,
                    f"field '{field_name_tok.text}' is already declared in struct '{name_tok.text}'",
                )
            field_names.add(field_name_tok.text)

            fields.append(
                FieldDef(
                    field_name_tok.text,
                    type_tok.text,
                    is_mut,
                    field_name_tok.line,
                    field_name_tok.col,
                )
            )
            self.next_line()

        while True:
            cur = self.current_line()
            if cur is None:
                raise CompileError(open_brace.line, open_brace.col, "'{' is never closed")
            first_tok = cur[0]
            if first_tok.text == "}":
                if len(cur) > 1:
                    raise CompileError(
                        cur[1].line, cur[1].col, f"unexpected '{cur[1].text}' after '}}'"
                    )
                self.next_line()
                break

            if first_tok.text != "fn":
                raise CompileError(
                    first_tok.line,
                    first_tok.col,
                    "field after a member function is an error at that field",
                )

            fn_def = self.parse_fn_def()
            if fn_def.name in ("read", "print"):
                raise CompileError(
                    fn_def.line,
                    fn_def.col,
                    f"cannot use reserved keyword '{fn_def.name}' as a member function name",
                )
            if fn_def.name in field_names:
                raise CompileError(
                    fn_def.line,
                    fn_def.col,
                    f"member function '{fn_def.name}' cannot have the same name as a field",
                )
            if fn_def.name in member_names:
                raise CompileError(
                    fn_def.line,
                    fn_def.col,
                    f"member function '{fn_def.name}' is already declared",
                )
            member_names.add(fn_def.name)
            member_fns.append(
                MemberFnNode(
                    fn_def.line,
                    fn_def.col,
                    fn_def.name,
                    fn_def.params,
                    fn_def.return_type,
                    fn_def.body,
                )
            )

        return StructDefNode(name_tok.line, name_tok.col, name_tok.text, fields, member_fns)

    def parse_fn_def(self) -> FnDefNode:
        line = self.current_line()
        assert line is not None
        fn_tok = self.eat()

        name_tok = self.peek()
        if name_tok is None:
            line_no, col = self._end_of_line_loc()
            raise CompileError(line_no, col, "expected function name, found end of line")
        if name_tok.text in ("read", "print"):
            raise CompileError(
                name_tok.line,
                name_tok.col,
                f"cannot use reserved keyword '{name_tok.text}' as a function name",
            )
        if not name_tok.is_identifier:
            raise CompileError(
                name_tok.line,
                name_tok.col,
                f"expected function name, got '{name_tok.text}'",
            )
        self.eat()

        assign_tok = self.peek()
        if assign_tok is None:
            line_no, col = self._end_of_line_loc()
            raise CompileError(line_no, col, "expected ':=' after function name, found end of line")
        if assign_tok.text != ":=":
            raise CompileError(
                assign_tok.line,
                assign_tok.col,
                f"expected ':=' after function name, got '{assign_tok.text}'",
            )
        self.eat()

        open_paren = self.peek()
        if open_paren is None:
            line_no, col = self._end_of_line_loc()
            raise CompileError(line_no, col, "expected '(' after ':=', found end of line")
        if open_paren.text == "[":
            raise CompileError(
                open_paren.line,
                open_paren.col,
                "a member function cannot have a capture list",
            )
        if open_paren.text != "(":
            raise CompileError(
                open_paren.line,
                open_paren.col,
                f"expected '(' after ':=', got '{open_paren.text}'",
            )
        self.eat()

        params: list[ParamDef] = []
        param_names: set[str] = set()

        if self.peek() is not None and self.peek().text != ")":
            while True:
                type_tok = self.peek()
                if type_tok is None:
                    line_no, col = self._end_of_line_loc()
                    raise CompileError(line_no, col, "expected parameter type, found end of line")
                if not (type_tok.text in ("i32", "i64", "bool") or type_tok.is_identifier):
                    raise CompileError(
                        type_tok.line,
                        type_tok.col,
                        f"expected parameter type, got '{type_tok.text}'",
                    )
                self.eat()

                pname_tok = self.peek()
                if pname_tok is None:
                    line_no, col = self._end_of_line_loc()
                    raise CompileError(line_no, col, "expected parameter name, found end of line")
                if pname_tok.text in ("read", "print"):
                    raise CompileError(
                        pname_tok.line,
                        pname_tok.col,
                        f"cannot use reserved keyword '{pname_tok.text}' as a parameter name",
                    )
                if not pname_tok.is_identifier:
                    raise CompileError(
                        pname_tok.line,
                        pname_tok.col,
                        f"expected parameter name, got '{pname_tok.text}'",
                    )
                self.eat()

                if pname_tok.text in param_names:
                    raise CompileError(
                        pname_tok.line,
                        pname_tok.col,
                        f"parameter '{pname_tok.text}' is already declared",
                    )
                param_names.add(pname_tok.text)
                params.append(
                    ParamDef(pname_tok.text, type_tok.text, pname_tok.line, pname_tok.col)
                )

                if self.peek() is not None and self.peek().text == ",":
                    self.eat()
                else:
                    break

        close_paren = self.peek()
        if close_paren is None:
            line_no, col = self._end_of_line_loc()
            raise CompileError(line_no, col, "expected ')' after parameter list, found end of line")
        if close_paren.text != ")":
            raise CompileError(
                close_paren.line,
                close_paren.col,
                f"expected ')' after parameter list, got '{close_paren.text}'",
            )
        self.eat()

        arrow = self.peek()
        if arrow is None:
            line_no, col = self._end_of_line_loc()
            raise CompileError(line_no, col, "expected '->' after parameter list, found end of line")
        if arrow.text != "->":
            raise CompileError(
                arrow.line,
                arrow.col,
                f"expected '->' after parameter list, got '{arrow.text}'",
            )
        self.eat()

        ret_type_tok = self.peek()
        if ret_type_tok is None:
            line_no, col = self._end_of_line_loc()
            raise CompileError(line_no, col, "expected return type, found end of line")
        if not (ret_type_tok.text in ("i32", "i64", "bool") or ret_type_tok.is_identifier):
            raise CompileError(
                ret_type_tok.line,
                ret_type_tok.col,
                f"expected return type, got '{ret_type_tok.text}'",
            )
        self.eat()
        ret_type = ret_type_tok.text

        if (extra := self.peek()) is not None:
            raise CompileError(
                extra.line, extra.col, f"unexpected '{extra.text}' after function signature"
            )

        self.next_line()
        body = self.parse_block(context="after function signature")
        if body.exit is None:
            raise CompileError(
                body.line,
                body.col,
                f"function '{name_tok.text}' must end with an exit statement",
            )

        return FnDefNode(name_tok.line, name_tok.col, name_tok.text, params, ret_type, body)

    def _is_lambda_line(self, line: list[Token]) -> bool:
        return (
            len(line) >= 4
            and line[0].text == "fn"
            and line[2].text == ":="
            and line[3].text == "["
        )

    def parse_lambda(self) -> LambdaNode:
        line = self.current_line()
        assert line is not None
        self.eat()

        name_tok = self.peek()
        if name_tok is None:
            line_no, col = self._end_of_line_loc()
            raise CompileError(line_no, col, "expected lambda name, found end of line")
        if name_tok.text in ("read", "print"):
            raise CompileError(
                name_tok.line,
                name_tok.col,
                f"cannot use reserved keyword '{name_tok.text}' as a lambda name",
            )
        if not name_tok.is_identifier:
            raise CompileError(
                name_tok.line,
                name_tok.col,
                f"expected lambda name, got '{name_tok.text}'",
            )
        self.eat()

        assign_tok = self.peek()
        assert assign_tok is not None and assign_tok.text == ":="
        self.eat()

        open_bracket = self.peek()
        assert open_bracket is not None and open_bracket.text == "["
        self.eat()

        captures: list[CaptureDef] = []
        if self.peek() is not None and self.peek().text != "]":
            while True:
                is_mut = False
                if self.peek() is not None and self.peek().text == "mut":
                    self.eat()
                    is_mut = True

                cap_tok = self.peek()
                if cap_tok is None:
                    line_no, col = self._end_of_line_loc()
                    raise CompileError(line_no, col, "expected capture name, found end of line")
                if cap_tok.text in ("read", "print"):
                    raise CompileError(
                        cap_tok.line,
                        cap_tok.col,
                        f"cannot use reserved keyword '{cap_tok.text}' as a capture name",
                    )
                if not cap_tok.is_identifier:
                    raise CompileError(
                        cap_tok.line,
                        cap_tok.col,
                        f"expected capture name, got '{cap_tok.text}'",
                    )
                self.eat()
                captures.append(
                    CaptureDef(cap_tok.text, is_mut, cap_tok.line, cap_tok.col)
                )

                if self.peek() is not None and self.peek().text == ",":
                    self.eat()
                else:
                    break

        close_bracket = self.peek()
        if close_bracket is None:
            line_no, col = self._end_of_line_loc()
            raise CompileError(line_no, col, "expected ']' after capture list, found end of line")
        if close_bracket.text != "]":
            raise CompileError(
                close_bracket.line,
                close_bracket.col,
                f"expected ']' after capture list, got '{close_bracket.text}'",
            )
        self.eat()

        open_paren = self.peek()
        if open_paren is None:
            line_no, col = self._end_of_line_loc()
            raise CompileError(line_no, col, "expected '(' after capture list, found end of line")
        if open_paren.text != "(":
            raise CompileError(
                open_paren.line,
                open_paren.col,
                f"expected '(' after capture list, got '{open_paren.text}'",
            )
        self.eat()

        params: list[ParamDef] = []
        param_names: set[str] = set()

        if self.peek() is not None and self.peek().text != ")":
            while True:
                type_tok = self.peek()
                if type_tok is None:
                    line_no, col = self._end_of_line_loc()
                    raise CompileError(line_no, col, "expected parameter type, found end of line")
                if not (type_tok.text in ("i32", "i64", "bool") or type_tok.is_identifier):
                    raise CompileError(
                        type_tok.line,
                        type_tok.col,
                        f"expected parameter type, got '{type_tok.text}'",
                    )
                self.eat()

                pname_tok = self.peek()
                if pname_tok is None:
                    line_no, col = self._end_of_line_loc()
                    raise CompileError(line_no, col, "expected parameter name, found end of line")
                if pname_tok.text in ("read", "print"):
                    raise CompileError(
                        pname_tok.line,
                        pname_tok.col,
                        f"cannot use reserved keyword '{pname_tok.text}' as a parameter name",
                    )
                if not pname_tok.is_identifier:
                    raise CompileError(
                        pname_tok.line,
                        pname_tok.col,
                        f"expected parameter name, got '{pname_tok.text}'",
                    )
                self.eat()

                if pname_tok.text in param_names:
                    raise CompileError(
                        pname_tok.line,
                        pname_tok.col,
                        f"parameter '{pname_tok.text}' is already declared",
                    )
                param_names.add(pname_tok.text)
                params.append(
                    ParamDef(pname_tok.text, type_tok.text, pname_tok.line, pname_tok.col)
                )

                if self.peek() is not None and self.peek().text == ",":
                    self.eat()
                else:
                    break

        close_paren = self.peek()
        if close_paren is None:
            line_no, col = self._end_of_line_loc()
            raise CompileError(line_no, col, "expected ')' after parameter list, found end of line")
        if close_paren.text != ")":
            raise CompileError(
                close_paren.line,
                close_paren.col,
                f"expected ')' after parameter list, got '{close_paren.text}'",
            )
        self.eat()

        arrow = self.peek()
        if arrow is None:
            line_no, col = self._end_of_line_loc()
            raise CompileError(line_no, col, "expected '->' after parameter list, found end of line")
        if arrow.text != "->":
            raise CompileError(
                arrow.line,
                arrow.col,
                f"expected '->' after parameter list, got '{arrow.text}'",
            )
        self.eat()

        ret_type_tok = self.peek()
        if ret_type_tok is None:
            line_no, col = self._end_of_line_loc()
            raise CompileError(line_no, col, "expected return type, found end of line")
        if not (ret_type_tok.text in ("i32", "i64", "bool") or ret_type_tok.is_identifier):
            raise CompileError(
                ret_type_tok.line,
                ret_type_tok.col,
                f"expected return type, got '{ret_type_tok.text}'",
            )
        self.eat()
        ret_type = ret_type_tok.text

        if (extra := self.peek()) is not None:
            raise CompileError(
                extra.line, extra.col, f"unexpected '{extra.text}' after lambda signature"
            )

        self.next_line()
        body = self.parse_block(context="after lambda signature")
        if body.exit is None:
            raise CompileError(
                body.line,
                body.col,
                f"lambda '{name_tok.text}' must end with an exit statement",
            )

        return LambdaNode(name_tok.line, name_tok.col, name_tok.text, captures, params, ret_type, body)

    def parse_print(self) -> PrintNode:
        print_tok = self.eat()
        open_paren = self.peek()
        if open_paren is None:
            line, col = self._end_of_line_loc()
            raise CompileError(line, col, "expected '(' after 'print', found end of line")
        if open_paren.text != "(":
            raise CompileError(
                open_paren.line, open_paren.col, f"expected '(' after 'print', got '{open_paren.text}'"
            )
        self.eat()

        if self.peek() is not None and self.peek().text == ")":
            self.eat()
            raise CompileError(
                print_tok.line, print_tok.col, "wrong number of arguments for 'print': expected 1, got 0"
            )

        if self.peek() is None:
            line, col = self._end_of_line_loc()
            raise CompileError(line, col, "expected argument for 'print', found end of line")

        if self.peek().is_string or self.peek().kind == "string":
            str_tok = self.eat()
            arg: ExprNode = StringLiteralNode(str_tok.line, str_tok.col, str_tok.text)
        else:
            arg = self.parse_expr()

        if self.peek() is not None and self.peek().text == ",":
            comma_tok = self.eat()
            raise CompileError(
                comma_tok.line, comma_tok.col, "wrong number of arguments for 'print': expected 1, got more"
            )

        close_paren = self.peek()
        if close_paren is None:
            line, col = self._end_of_line_loc()
            raise CompileError(line, col, "expected ')' after 'print' argument, found end of line")
        if close_paren.text != ")":
            raise CompileError(
                close_paren.line, close_paren.col, f"expected ')' after 'print' argument, got '{close_paren.text}'"
            )
        self.eat()

        if (extra := self.peek()) is not None:
            raise CompileError(
                extra.line, extra.col, f"unexpected '{extra.text}' after the statement"
            )

        return PrintNode(print_tok.line, print_tok.col, arg)

    def parse_statement(self) -> StmtNode:
        tok = self.peek()
        if tok is None:
            line, col = self._end_of_line_loc()
            raise CompileError(line, col, "unexpected end of line")
        if tok.text == "if":
            return self.parse_if()
        if tok.text == "while":
            return self.parse_while()
        if tok.text == "print":
            node = self.parse_print()
            self.next_line()
            return node
        if tok.text in ("i32", "i64", "bool"):
            node = self.parse_decl()
            self.next_line()
            return node
        if tok.is_identifier:
            if len(self.toks) > 1 and (
                self.toks[1].text == "mut"
                or (self.toks[1].is_identifier and len(self.toks) > 2 and self.toks[2].text == "{")
                or tok.text in self.known_structs
            ):
                node = self.parse_decl()
                self.next_line()
                return node
            node = self.parse_assign()
            self.next_line()
            return node
        if tok.text == "else":
            raise CompileError(tok.line, tok.col, "'else' without an 'if'")
        if tok.text == "struct":
            raise CompileError(tok.line, tok.col, "struct declaration after statement")
        if tok.text == "fn":
            if self._is_lambda_line(self.toks):
                return self.parse_lambda()
            raise CompileError(tok.line, tok.col, "function declaration after statement")
        raise CompileError(
            tok.line, tok.col, f"cannot start a statement with '{tok.text}'"
        )

    def parse_program(self) -> ProgramNode:
        self.line_idx = 0
        self._set_current_line()
        self.known_structs = set()
        struct_defs: list[StructDefNode] = []

        while self.current_line() is not None:
            line = self.current_line()
            first_tok = line[0]
            if first_tok.text == "struct":
                s_def = self.parse_struct_def()
                struct_defs.append(s_def)
                self.known_structs.add(s_def.name)
            else:
                break

        fn_defs: list[FnDefNode] = []
        while self.current_line() is not None:
            line = self.current_line()
            first_tok = line[0]
            if first_tok.text == "fn":
                if self._is_lambda_line(line):
                    break
                fn_node = self.parse_fn_def()
                fn_defs.append(fn_node)
            elif first_tok.text == "struct":
                raise CompileError(
                    first_tok.line, first_tok.col, "struct declaration after function"
                )
            else:
                break

        stmts: list[StmtNode] = []
        exit_node: ExitNode | None = None
        last_line_number = len(self.raw_lines) if self.raw_lines else 1

        while self.current_line() is not None:
            line = self.current_line()
            first_tok = line[0]
            last_line_number = first_tok.line

            if exit_node is not None:
                raise CompileError(first_tok.line, first_tok.col, "code after exit")

            if first_tok.text == "exit":
                exit_node = self.parse_exit()
                self.next_line()
            else:
                stmts.append(self.parse_statement())

        if exit_node is None:
            raise CompileError(last_line_number, 1, "missing exit statement")

        return ProgramNode(1, 1, struct_defs, fn_defs, stmts, exit_node)


@dataclass(slots=True)
class FieldInfo:
    name: str
    type_name: str
    mutable: bool
    index: int
    line: int
    col: int


@dataclass(slots=True)
class MemberFnInfo:
    name: str
    struct_name: str
    params: list[ParamDef]
    return_type: str
    is_mutating: bool
    line: int
    col: int
    node: MemberFnNode
    called_member_fns: list[tuple[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class StructInfo:
    name: str
    fields: list[FieldInfo]
    fields_by_name: dict[str, FieldInfo]
    member_fns: dict[str, MemberFnInfo]
    line: int
    col: int
    is_lambda: bool = False


@dataclass(slots=True)
class FnInfo:
    name: str
    params: list[ParamDef]
    return_type: str
    line: int
    col: int


class SemanticChecker:
    def __init__(self) -> None:
        self.scopes: list[dict[str, DeclNode]] = [{}]
        self.structs: dict[str, StructInfo] = {}
        self.functions: dict[str, FnInfo] = {}
        self.current_fn: FnInfo | None = None
        self.current_struct: StructInfo | None = None
        self.current_member_fn: MemberFnInfo | None = None
        self.program_node: ProgramNode | None = None
        self.enclosing_envs: list[tuple[list[dict[str, DeclNode]], StructInfo | None]] = []
        self.current_lambda_name: str | None = None

    def lookup(self, name: str) -> DeclNode | None:
        for frame in reversed(self.scopes):
            if name in frame:
                return frame[name]
        return None

    def is_lambda_type(self, type_name: str | None) -> bool:
        return (
            type_name is not None
            and type_name in self.structs
            and self.structs[type_name].is_lambda
        )

    def _lambda_display_name(self, expr: ExprNode, type_name: str | None) -> str:
        if isinstance(expr, VarNode):
            return expr.name
        if type_name is not None and type_name.startswith("lambda."):
            return type_name.split(".")[1]
        return type_name or "lambda"

    def is_in_enclosing_env(self, name: str) -> bool:
        for scopes, struct_info in reversed(self.enclosing_envs):
            for frame in reversed(scopes):
                if name in frame:
                    return True
            if struct_info is not None and name in struct_info.fields_by_name:
                return True
        return False

    def is_deeply_mutable(self, type_name: str) -> bool:
        if type_name in ("i32", "i64", "bool"):
            return True
        if type_name in self.structs:
            s_info = self.structs[type_name]
            for f in s_info.fields:
                if not f.mutable:
                    return False
                if not self.is_deeply_mutable(f.type_name):
                    return False
            return True
        return True

    def visit_struct_def(self, node: StructDefNode) -> None:
        if node.name in ("i32", "i64", "bool"):
            raise CompileError(
                node.line, node.col, f"cannot redefine built-in type '{node.name}'"
            )
        if node.name in self.structs:
            raise CompileError(
                node.line, node.col, f"struct '{node.name}' is already declared"
            )
        if not node.fields:
            raise CompileError(node.line, node.col, "empty struct")

        fields: list[FieldInfo] = []
        fields_by_name: dict[str, FieldInfo] = {}

        for idx, f in enumerate(node.fields):
            if f.name in fields_by_name:
                raise CompileError(
                    f.line,
                    f.col,
                    f"field '{f.name}' is already declared in struct '{node.name}'",
                )
            if f.type_name == node.name:
                raise CompileError(
                    f.line,
                    f.col,
                    f"struct '{node.name}' cannot contain itself",
                )
            if (
                f.type_name not in ("i32", "i64", "bool")
                and f.type_name not in self.structs
            ):
                raise CompileError(
                    f.line,
                    f.col,
                    f"unknown type '{f.type_name}' in field '{f.name}'",
                )
            info = FieldInfo(f.name, f.type_name, f.mutable, idx, f.line, f.col)
            fields.append(info)
            fields_by_name[f.name] = info

        member_fns: dict[str, MemberFnInfo] = {}
        for m in node.member_fns:
            if m.name in fields_by_name:
                raise CompileError(
                    m.line,
                    m.col,
                    f"member function '{m.name}' cannot have the same name as a field",
                )
            if m.name in member_fns:
                raise CompileError(
                    m.line,
                    m.col,
                    f"member function '{m.name}' is already declared in struct '{node.name}'",
                )
            if m.return_type not in ("i32", "i64", "bool") and m.return_type not in self.structs and m.return_type != node.name:
                raise CompileError(
                    m.line,
                    m.col,
                    f"unknown return type '{m.return_type}' in member function '{m.name}'",
                )
            for p in m.params:
                if p.type_name not in ("i32", "i64", "bool") and p.type_name not in self.structs and p.type_name != node.name:
                    raise CompileError(
                        p.line,
                        p.col,
                        f"unknown parameter type '{p.type_name}' in member function '{m.name}'",
                    )
            member_fns[m.name] = MemberFnInfo(
                m.name,
                node.name,
                m.params,
                m.return_type,
                False,
                m.line,
                m.col,
                m,
            )

        self.structs[node.name] = StructInfo(
            node.name, fields, fields_by_name, member_fns, node.line, node.col
        )

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

    def visit_read(self, node: ReadNode) -> str:
        node.type = "i32"
        return "i32"

    def visit_string_literal(self, node: StringLiteralNode) -> str:
        node.type = "string"
        return "string"

    def visit_var(self, node: VarNode) -> str:
        decl = self.lookup(node.name)
        if decl is not None:
            node.decl = decl
            node.type = decl.type_name
            return node.type
        if self.current_struct is not None and node.name in self.current_struct.fields_by_name:
            f_info = self.current_struct.fields_by_name[node.name]
            node.is_this_field = True
            node.field_info = f_info
            node.type = f_info.type_name
            return node.type
        if self.current_lambda_name is not None and self.is_in_enclosing_env(node.name):
            raise CompileError(
                node.line,
                node.col,
                f"'{node.name}' is not captured by lambda '{self.current_lambda_name}': add it to the capture list, [{node.name}]",
            )
        raise CompileError(
            node.line,
            node.col,
            f"variable '{node.name}' is used before its declaration",
        )

    def visit_field_access(self, node: FieldAccessNode) -> str:
        if node.target is not None:
            curr_type = node.target.accept(self)
        else:
            decl = self.lookup(node.obj_name)
            if decl is not None:
                node.decl = decl
                curr_type = decl.type_name
            elif self.current_struct is not None and node.obj_name in self.current_struct.fields_by_name:
                f_info = self.current_struct.fields_by_name[node.obj_name]
                node.is_this_field = True
                node.this_field_info = f_info
                curr_type = f_info.type_name
            else:
                if self.current_lambda_name is not None and self.is_in_enclosing_env(node.obj_name):
                    raise CompileError(
                        node.line,
                        node.col,
                        f"'{node.obj_name}' is not captured by lambda '{self.current_lambda_name}': add it to the capture list, [{node.obj_name}]",
                    )
                raise CompileError(
                    node.line,
                    node.col,
                    f"variable '{node.obj_name}' is used before its declaration",
                )

        indices: list[int] = []
        for field_name in node.fields:
            if self.is_lambda_type(curr_type):
                raise CompileError(
                    node.line,
                    node.col,
                    f"cannot access capture '{field_name}' of lambda '{node.obj_name}'",
                )
            if curr_type not in self.structs:
                err_line, err_col = node.dot_loc if node.dot_loc is not None else (node.line, node.col)
                raise CompileError(
                    err_line,
                    err_col,
                    f"type '{curr_type}' is not a struct, cannot access field '{field_name}'",
                )
            st_info = self.structs[curr_type]
            if field_name not in st_info.fields_by_name:
                raise CompileError(
                    node.line,
                    node.col,
                    f"struct '{curr_type}' has no field '{field_name}'",
                )
            f_info = st_info.fields_by_name[field_name]
            indices.append(f_info.index)
            curr_type = f_info.type_name

        node.field_indices = indices
        node.type = curr_type
        return node.type

    def visit_binop(self, node: BinOpNode) -> str:
        lt = node.left.accept(self)
        rt = node.right.accept(self)
        if node.op in ("+", "-", "*"):
            if lt == "bool" or rt == "bool":
                raise CompileError(
                    node.line, node.col, f"cannot apply '{node.op}' to bool"
                )
            if lt not in ("i32", "i64") or rt not in ("i32", "i64"):
                bad_type = lt if lt not in ("i32", "i64") else rt
                raise CompileError(
                    node.line, node.col, f"cannot apply '{node.op}' to {bad_type}"
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

    def visit_not(self, node: NotNode) -> str:
        t = node.expr.accept(self)
        if t != "bool":
            raise CompileError(node.line, node.col, f"cannot apply '!' to {t}")
        node.type = "bool"
        return "bool"

    def visit_if(self, node: IfNode) -> None:
        ct = node.cond.accept(self)
        if ct != "bool":
            raise CompileError(
                node.line, node.col, f"the condition of 'if' must be bool, got {ct}"
            )
        node.then_block.accept(self)
        if node.else_block is not None:
            node.else_block.accept(self)

    def visit_while(self, node: WhileNode) -> None:
        ct = node.cond.accept(self)
        if ct != "bool":
            raise CompileError(
                node.line, node.col, f"the condition of 'while' must be bool, got {ct}"
            )
        node.body.accept(self)

    def visit_print(self, node: PrintNode) -> None:
        arg_type = node.arg.accept(self)
        if self.is_lambda_type(arg_type):
            lam_name = self._lambda_display_name(node.arg, arg_type)
            raise CompileError(
                node.arg.line,
                node.arg.col,
                f"'{lam_name}' is a lambda and cannot be printed: its type has no name",
            )
        if arg_type not in ("i32", "i64", "bool", "string") and arg_type not in self.structs:
            raise CompileError(node.arg.line, node.arg.col, f"cannot print value of type '{arg_type}'")

    def visit_block(self, node: BlockNode) -> None:
        self.scopes.append({})
        for stmt in node.statements:
            stmt.accept(self)
        if node.exit is not None:
            node.exit.accept(self)
        self.scopes.pop()

    def check_assignable(
        self, expr: ExprNode, want: str, at: Node, what: str
    ) -> None:
        have = expr.type
        if self.is_lambda_type(have):
            lam_name = self._lambda_display_name(expr, have)
            raise CompileError(
                expr.line,
                expr.col,
                f"'{lam_name}' is a lambda and cannot {what}: its type has no name",
            )
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
        if (
            node.type_name not in ("i32", "i64", "bool")
            and (node.type_name not in self.structs or self.is_lambda_type(node.type_name))
        ):
            raise CompileError(node.line, node.col, f"unknown type '{node.type_name}'")

        top_frame = self.scopes[-1]
        if node.name in top_frame:
            if len(self.scopes) > 1:
                msg = f"variable '{node.name}' is already declared in this block"
            else:
                msg = f"variable '{node.name}' is already declared"
            raise CompileError(node.line, node.col, msg)

        if node.type_name in ("i32", "i64", "bool"):
            if len(node.inits) != 1:
                raise CompileError(
                    node.line,
                    node.col,
                    f"type '{node.type_name}' requires 1 initialiser, got {len(node.inits)}",
                )
            node.inits[0].accept(self)
            self.check_assignable(
                node.inits[0], node.type_name, node, f"initialise '{node.name}'"
            )
        else:
            s_info = self.structs[node.type_name]
            if len(node.inits) == 1 and not isinstance(node.inits[0], StructLiteralNode):
                init_type = node.inits[0].accept(self)
                if self.is_lambda_type(init_type):
                    lam_name = self._lambda_display_name(node.inits[0], init_type)
                    raise CompileError(
                        node.inits[0].line,
                        node.inits[0].col,
                        f"'{lam_name}' is a lambda and cannot initialise '{node.name}': its type has no name",
                    )
                if init_type == node.type_name:
                    pass
                elif len(s_info.fields) == 1:
                    f = s_info.fields[0]
                    self.check_assignable(
                        node.inits[0],
                        f.type_name,
                        node,
                        f"initialise field '{f.name}'",
                    )
                else:
                    raise CompileError(
                        node.line,
                        node.col,
                        f"wrong number of values in {{}} for '{node.type_name}': expected {len(s_info.fields)}, got 1",
                    )
            else:
                if len(node.inits) != len(s_info.fields):
                    raise CompileError(
                        node.line,
                        node.col,
                        f"wrong number of values in {{}} for '{node.type_name}': expected {len(s_info.fields)}, got {len(node.inits)}",
                    )
                for expr, f in zip(node.inits, s_info.fields):
                    if isinstance(expr, StructLiteralNode):
                        if f.type_name not in self.structs:
                            raise CompileError(
                                expr.line,
                                expr.col,
                                f"cannot initialise built-in field '{f.name}' of type {f.type_name} with {{}}",
                            )
                        self._check_struct_literal(expr, f.type_name)
                    else:
                        expr.accept(self)
                        self.check_assignable(
                            expr, f.type_name, expr, f"initialise field '{f.name}'"
                        )

        top_frame[node.name] = node

    def _check_struct_literal(self, lit: StructLiteralNode, target_struct_name: str) -> None:
        lit.type = target_struct_name
        s_info = self.structs[target_struct_name]
        if len(lit.inits) != len(s_info.fields):
            raise CompileError(
                lit.line,
                lit.col,
                f"wrong number of values in {{}} for '{target_struct_name}': expected {len(s_info.fields)}, got {len(lit.inits)}",
            )
        for expr, f in zip(lit.inits, s_info.fields):
            if isinstance(expr, StructLiteralNode):
                if f.type_name not in self.structs:
                    raise CompileError(
                        expr.line,
                        expr.col,
                        f"cannot initialise built-in field '{f.name}' of type {f.type_name} with {{}}",
                    )
                self._check_struct_literal(expr, f.type_name)
            else:
                expr.accept(self)
                self.check_assignable(
                    expr, f.type_name, expr, f"initialise field '{f.name}'"
                )

    def visit_struct_literal(self, node: StructLiteralNode) -> str:
        assert node.type is not None
        return node.type

    def visit_lambda(self, node: LambdaNode) -> None:
        if node.name in ("i32", "i64", "bool"):
            raise CompileError(
                node.line, node.col, f"cannot name lambda with built-in type '{node.name}'"
            )
        if node.name in self.structs:
            raise CompileError(
                node.line, node.col, f"lambda '{node.name}' clashes with struct '{node.name}'"
            )

        top_frame = self.scopes[-1]
        if node.name in top_frame:
            if len(self.scopes) > 1:
                msg = f"variable '{node.name}' is already declared in this block"
            else:
                msg = f"variable '{node.name}' is already declared"
            raise CompileError(node.line, node.col, msg)

        seen_captures: set[str] = set()
        captured_types: list[str] = []
        for cap in node.captures:
            if cap.name in seen_captures:
                raise CompileError(
                    cap.line,
                    cap.col,
                    f"'{cap.name}' is captured twice",
                )
            seen_captures.add(cap.name)

            decl = self.lookup(cap.name)
            if decl is not None:
                captured_types.append(decl.type_name)
            elif self.current_struct is not None and cap.name in self.current_struct.fields_by_name:
                captured_types.append(self.current_struct.fields_by_name[cap.name].type_name)
            else:
                raise CompileError(
                    cap.line,
                    cap.col,
                    f"cannot capture '{cap.name}': no variable '{cap.name}' is visible here",
                )

        for p in node.params:
            if p.name in seen_captures:
                raise CompileError(
                    p.line,
                    p.col,
                    f"parameter '{p.name}' has the same name as a capture",
                )
            if (
                p.type_name not in ("i32", "i64", "bool")
                and (p.type_name not in self.structs or self.is_lambda_type(p.type_name))
            ):
                raise CompileError(
                    p.line,
                    p.col,
                    f"unknown parameter type '{p.type_name}' in lambda '{node.name}'",
                )

        if (
            node.return_type not in ("i32", "i64", "bool")
            and (node.return_type not in self.structs or self.is_lambda_type(node.return_type))
        ):
            raise CompileError(
                node.line,
                node.col,
                f"unknown return type '{node.return_type}' in lambda '{node.name}'",
            )

        base_struct_name = f"lambda.{node.name}"
        struct_name = base_struct_name
        suffix = 1
        while struct_name in self.structs:
            suffix += 1
            struct_name = f"{base_struct_name}.{suffix}"

        field_defs: list[FieldDef] = []
        field_infos: list[FieldInfo] = []
        fields_by_name: dict[str, FieldInfo] = {}
        for idx, (cap, cap_type) in enumerate(zip(node.captures, captured_types)):
            f_def = FieldDef(cap.name, cap_type, cap.mutable, cap.line, cap.col)
            f_info = FieldInfo(cap.name, cap_type, cap.mutable, idx, cap.line, cap.col)
            field_defs.append(f_def)
            field_infos.append(f_info)
            fields_by_name[cap.name] = f_info

        call_fn_node = MemberFnNode(
            node.line,
            node.col,
            "call",
            node.params,
            node.return_type,
            node.body,
        )
        call_m_info = MemberFnInfo(
            "call",
            struct_name,
            node.params,
            node.return_type,
            False,
            node.line,
            node.col,
            call_fn_node,
        )
        struct_def_node = StructDefNode(
            node.line,
            node.col,
            struct_name,
            field_defs,
            [call_fn_node],
        )
        lambda_struct_info = StructInfo(
            struct_name,
            field_infos,
            fields_by_name,
            {"call": call_m_info},
            node.line,
            node.col,
            is_lambda=True,
        )
        self.structs[struct_name] = lambda_struct_info

        saved_scopes = self.scopes
        saved_struct = self.current_struct
        saved_member_fn = self.current_member_fn
        saved_fn = self.current_fn
        saved_lambda_name = self.current_lambda_name

        self.enclosing_envs.append((saved_scopes, saved_struct))
        self.current_struct = lambda_struct_info
        self.current_member_fn = call_m_info
        self.current_fn = None
        self.current_lambda_name = node.name
        self.scopes = [{}]
        for p in node.params:
            p_decl = DeclNode(p.line, p.col, p.name, p.type_name, mutable=False, inits=[])
            p.decl = p_decl
            self.scopes[0][p.name] = p_decl

        node.body.accept(self)

        self.enclosing_envs.pop()
        self.scopes = saved_scopes
        self.current_struct = saved_struct
        self.current_member_fn = saved_member_fn
        self.current_fn = saved_fn
        self.current_lambda_name = saved_lambda_name

        if not call_m_info.is_mutating:
            for callee_struct, callee_name in call_m_info.called_member_fns:
                if self.structs[callee_struct].member_fns[callee_name].is_mutating:
                    call_m_info.is_mutating = True
                    break

        inits: list[ExprNode] = []
        for cap in node.captures:
            v_node = VarNode(cap.line, cap.col, cap.name)
            v_node.accept(self)
            inits.append(v_node)

        is_decl_mut = any(cap.mutable for cap in node.captures)
        decl_node = DeclNode(
            node.line,
            node.col,
            node.name,
            struct_name,
            mutable=is_decl_mut,
            inits=inits,
        )
        self.scopes[-1][node.name] = decl_node
        node.struct_def = struct_def_node
        node.decl_node = decl_node
        assert self.program_node is not None
        self.program_node.lambda_struct_defs.append(struct_def_node)

    def visit_assign(self, node: AssignNode) -> None:
        decl = self.lookup(node.name)
        if decl is not None:
            node.decl = decl
            if self.is_lambda_type(decl.type_name):
                raise CompileError(
                    node.line,
                    node.col,
                    f"cannot assign to '{node.name}': it is a lambda",
                )
            if not node.decl.mutable:
                raise CompileError(
                    node.line, node.col, f"cannot assign to '{node.name}': it is not mut"
                )
            node.value.accept(self)
            if self.is_lambda_type(node.value.type):
                lam_name = self._lambda_display_name(node.value, node.value.type)
                raise CompileError(
                    node.value.line,
                    node.value.col,
                    f"'{lam_name}' is a lambda and cannot be assigned to '{node.name}': its type has no name",
                )
            if decl.type_name in self.structs:
                if node.value.type != decl.type_name:
                    raise CompileError(
                        node.line,
                        node.col,
                        f"cannot assign to '{node.name}' of type {decl.type_name} with a value of type {node.value.type}",
                    )
                if not self.is_deeply_mutable(decl.type_name):
                    raise CompileError(
                        node.line,
                        node.col,
                        f"cannot replace whole struct '{node.name}': not all fields are mut",
                    )
            else:
                self.check_assignable(
                    node.value, node.decl.type_name, node, f"assign to '{node.name}'"
                )
            return

        if self.current_struct is not None and node.name in self.current_struct.fields_by_name:
            f_info = self.current_struct.fields_by_name[node.name]
            if not f_info.mutable:
                if self.current_struct.is_lambda:
                    raise CompileError(
                        node.line,
                        node.col,
                        f"cannot assign to '{node.name}': the capture '{node.name}' is const, write [mut {node.name}]",
                    )
                raise CompileError(
                    node.line, node.col, f"cannot assign to const field '{node.name}' inside member function"
                )
            if self.is_lambda_type(f_info.type_name):
                raise CompileError(
                    node.line,
                    node.col,
                    f"cannot assign to '{node.name}': it is a lambda",
                )
            node.is_this_field = True
            node.field_info = f_info
            if self.current_member_fn is not None:
                self.current_member_fn.is_mutating = True
            node.value.accept(self)
            if self.is_lambda_type(node.value.type):
                lam_name = self._lambda_display_name(node.value, node.value.type)
                raise CompileError(
                    node.value.line,
                    node.value.col,
                    f"'{lam_name}' is a lambda and cannot be assigned to '{node.name}': its type has no name",
                )
            if f_info.type_name in self.structs:
                if node.value.type != f_info.type_name:
                    raise CompileError(
                        node.line,
                        node.col,
                        f"cannot assign to '{node.name}' of type {f_info.type_name} with a value of type {node.value.type}",
                    )
                if not self.is_deeply_mutable(f_info.type_name):
                    raise CompileError(
                        node.line,
                        node.col,
                        f"cannot replace whole struct '{node.name}': not all fields are mut",
                    )
            else:
                self.check_assignable(
                    node.value, f_info.type_name, node, f"assign to '{node.name}'"
                )
            return

        if self.current_lambda_name is not None and self.is_in_enclosing_env(node.name):
            raise CompileError(
                node.line,
                node.col,
                f"'{node.name}' is not captured by lambda '{self.current_lambda_name}': add it to the capture list, [{node.name}]",
            )
        raise CompileError(
            node.line, node.col, f"variable '{node.name}' is used before its declaration"
        )

    def visit_field_assign(self, node: FieldAssignNode) -> None:
        decl = self.lookup(node.obj_name)
        chain_str = f"{node.obj_name}.{'.'.join(node.fields)}"

        if decl is not None:
            node.decl = decl
            if self.is_lambda_type(decl.type_name):
                raise CompileError(
                    node.line,
                    node.col,
                    f"cannot access capture '{node.fields[0]}' of lambda '{node.obj_name}'",
                )
            if not decl.mutable:
                raise CompileError(
                    node.line,
                    node.col,
                    f"cannot assign to '{chain_str}': '{node.obj_name}' is not mut",
                )
            curr_type = decl.type_name
        elif self.current_struct is not None and node.obj_name in self.current_struct.fields_by_name:
            f_info = self.current_struct.fields_by_name[node.obj_name]
            if self.is_lambda_type(f_info.type_name):
                raise CompileError(
                    node.line,
                    node.col,
                    f"cannot access capture '{node.fields[0]}' of lambda '{node.obj_name}'",
                )
            if not f_info.mutable:
                if self.current_struct.is_lambda:
                    raise CompileError(
                        node.line,
                        node.col,
                        f"cannot assign to '{chain_str}': the capture '{node.obj_name}' is const, write [mut {node.obj_name}]",
                    )
                raise CompileError(
                    node.line,
                    node.col,
                    f"cannot assign to '{chain_str}': field '{node.obj_name}' is not mut",
                )
            node.is_this_field = True
            node.this_field_info = f_info
            if self.current_member_fn is not None:
                self.current_member_fn.is_mutating = True
            curr_type = f_info.type_name
        else:
            if self.current_lambda_name is not None and self.is_in_enclosing_env(node.obj_name):
                raise CompileError(
                    node.line,
                    node.col,
                    f"'{node.obj_name}' is not captured by lambda '{self.current_lambda_name}': add it to the capture list, [{node.obj_name}]",
                )
            raise CompileError(
                node.line,
                node.col,
                f"variable '{node.obj_name}' is used before its declaration",
            )

        indices: list[int] = []
        for field_name in node.fields:
            if curr_type not in self.structs:
                raise CompileError(
                    node.line,
                    node.col,
                    f"type '{curr_type}' is not a struct, cannot access field '{field_name}'",
                )
            st_info = self.structs[curr_type]
            if field_name not in st_info.fields_by_name:
                raise CompileError(
                    node.line,
                    node.col,
                    f"struct '{curr_type}' has no field '{field_name}'",
                )
            f_info = st_info.fields_by_name[field_name]
            if not f_info.mutable:
                raise CompileError(
                    node.line,
                    node.col,
                    f"cannot assign to '{chain_str}': field '{field_name}' is not mut",
                )
            indices.append(f_info.index)
            curr_type = f_info.type_name

        node.field_indices = indices
        node.target_type = curr_type

        node.value.accept(self)
        if self.is_lambda_type(node.value.type):
            lam_name = self._lambda_display_name(node.value, node.value.type)
            raise CompileError(
                node.value.line,
                node.value.col,
                f"'{lam_name}' is a lambda and cannot be assigned to '{chain_str}': its type has no name",
            )
        if curr_type in self.structs:
            if node.value.type != curr_type:
                raise CompileError(
                    node.line,
                    node.col,
                    f"cannot assign to '{chain_str}' of type {curr_type} with a value of type {node.value.type}",
                )
            if not self.is_deeply_mutable(curr_type):
                raise CompileError(
                    node.line,
                    node.col,
                    f"cannot replace whole struct '{chain_str}': not all fields are mut",
                )
        else:
            self.check_assignable(
                node.value, curr_type, node, f"assign to '{chain_str}'"
            )

    def visit_call(self, node: CallNode) -> str:
        is_var = (
            self.lookup(node.func_name) is not None
            or (
                self.current_struct is not None
                and node.func_name in self.current_struct.fields_by_name
            )
        )
        is_fn = (
            (
                self.current_struct is not None
                and not self.current_struct.is_lambda
                and node.func_name in self.current_struct.member_fns
            )
            or node.func_name in self.functions
        )

        if is_var and is_fn:
            raise CompileError(
                node.line,
                node.col,
                f"'{node.func_name}' is both a variable and a function: rename one of them",
            )

        if is_var:
            target_var = VarNode(node.line, node.col, node.func_name)
            var_type = target_var.accept(self)
            if var_type not in self.structs:
                raise CompileError(
                    node.line,
                    node.col,
                    f"'{node.func_name}' is not callable: it is {var_type}",
                )
            s_info = self.structs[var_type]
            if "call" not in s_info.member_fns:
                raise CompileError(
                    node.line,
                    node.col,
                    f"'{node.func_name}' is not callable: {var_type} has no member function 'call'",
                )
            rewritten = MemberCallNode(
                node.line,
                node.col,
                target_var,
                "call",
                node.args,
            )
            rewritten.is_callable_call = True
            rewritten.callable_name = node.func_name
            node.rewritten_call = rewritten
            node.type = self.visit_member_call(rewritten)
            return node.type

        if (
            self.current_struct is not None
            and not self.current_struct.is_lambda
            and node.func_name in self.current_struct.member_fns
        ):
            m_info = self.current_struct.member_fns[node.func_name]
            node.is_this_call = True
            node.struct_name = self.current_struct.name
            if self.current_member_fn is not None:
                self.current_member_fn.called_member_fns.append((self.current_struct.name, node.func_name))
            if len(node.args) != len(m_info.params):
                raise CompileError(
                    node.line,
                    node.col,
                    f"wrong number of arguments for member function '{node.func_name}': expected {len(m_info.params)}, got {len(node.args)}",
                )
            for arg, param in zip(node.args, m_info.params):
                arg_type = arg.accept(self)
                if self.is_lambda_type(arg_type):
                    lam_name = self._lambda_display_name(arg, arg_type)
                    raise CompileError(
                        arg.line,
                        arg.col,
                        f"'{lam_name}' is a lambda and cannot be passed to '{node.func_name}': its type has no name, so no parameter can have it",
                    )
                self.check_assignable(
                    arg,
                    param.type_name,
                    arg,
                    f"pass argument to parameter '{param.name}'",
                )
            node.type = m_info.return_type
            return node.type

        if node.func_name not in self.functions:
            if self.current_lambda_name == node.func_name:
                raise CompileError(
                    node.line,
                    node.col,
                    f"lambda '{node.func_name}' cannot call itself",
                )
            if self.current_lambda_name is not None and self.is_in_enclosing_env(node.func_name):
                raise CompileError(
                    node.line,
                    node.col,
                    f"'{node.func_name}' is not captured by lambda '{self.current_lambda_name}': add it to the capture list, [{node.func_name}]",
                )
            raise CompileError(
                node.line, node.col, f"unknown function '{node.func_name}'"
            )
        fn_info = self.functions[node.func_name]
        if len(node.args) != len(fn_info.params):
            raise CompileError(
                node.line,
                node.col,
                f"wrong number of arguments for '{node.func_name}': expected {len(fn_info.params)}, got {len(node.args)}",
            )
        for arg, param in zip(node.args, fn_info.params):
            arg_type = arg.accept(self)
            if self.is_lambda_type(arg_type):
                lam_name = self._lambda_display_name(arg, arg_type)
                raise CompileError(
                    arg.line,
                    arg.col,
                    f"'{lam_name}' is a lambda and cannot be passed to '{node.func_name}': its type has no name, so no parameter can have it",
                )
            self.check_assignable(
                arg,
                param.type_name,
                arg,
                f"pass argument to parameter '{param.name}'",
            )
        node.type = fn_info.return_type
        return node.type

    def visit_member_call(self, node: MemberCallNode) -> str:
        target_type = node.target.accept(self)
        if target_type not in self.structs:
            err_line, err_col = node.dot_loc if node.dot_loc is not None else (node.line, node.col)
            raise CompileError(
                err_line,
                err_col,
                f"type '{target_type}' is not a struct, cannot call member function '{node.func_name}'",
            )
        s_info = self.structs[target_type]
        if not node.is_callable_call and s_info.is_lambda:
            if node.func_name in s_info.fields_by_name:
                raise CompileError(
                    node.line,
                    node.col,
                    f"cannot access capture '{node.func_name}' of lambda",
                )
        if not node.is_callable_call and node.func_name in s_info.fields_by_name:
            field_name = node.func_name
            if isinstance(node.target, VarNode):
                field_target = FieldAccessNode(
                    node.target.line,
                    node.target.col,
                    node.target.name,
                    [field_name],
                )
            elif isinstance(node.target, FieldAccessNode):
                field_target = FieldAccessNode(
                    node.target.line,
                    node.target.col,
                    node.target.obj_name,
                    [*node.target.fields, field_name],
                    target=node.target.target,
                    dot_loc=node.target.dot_loc,
                )
            else:
                field_target = FieldAccessNode(
                    node.line,
                    node.col,
                    "",
                    [field_name],
                    target=node.target,
                    dot_loc=node.dot_loc,
                )
            field_type = field_target.accept(self)
            if field_type not in self.structs:
                raise CompileError(
                    node.line,
                    node.col,
                    f"'{field_name}' is not callable: it is {field_type}",
                )
            field_struct_info = self.structs[field_type]
            if "call" not in field_struct_info.member_fns:
                raise CompileError(
                    node.line,
                    node.col,
                    f"'{field_name}' is not callable: {field_type} has no member function 'call'",
                )
            node.target = field_target
            node.func_name = "call"
            node.is_callable_call = True
            node.callable_name = field_name
            target_type = field_type
            s_info = field_struct_info

        if node.func_name not in s_info.member_fns:
            raise CompileError(
                node.line,
                node.col,
                f"struct '{target_type}' has no member function '{node.func_name}'",
            )
        m_info = s_info.member_fns[node.func_name]
        node.struct_name = target_type

        if self.current_member_fn is not None:
            if isinstance(node.target, VarNode) and node.target.is_this_field:
                self.current_member_fn.called_member_fns.append((target_type, node.func_name))
            elif isinstance(node.target, FieldAccessNode) and node.target.is_this_field:
                self.current_member_fn.called_member_fns.append((target_type, node.func_name))

        callee_label = (
            (node.callable_name or "call")
            if node.is_callable_call
            else node.func_name
        )
        if len(node.args) != len(m_info.params):
            if node.is_callable_call:
                raise CompileError(
                    node.line,
                    node.col,
                    f"wrong number of arguments for '{callee_label}': expected {len(m_info.params)}, got {len(node.args)}",
                )
            raise CompileError(
                node.line,
                node.col,
                f"wrong number of arguments for member function '{node.func_name}': expected {len(m_info.params)}, got {len(node.args)}",
            )
        for arg, param in zip(node.args, m_info.params):
            arg_type = arg.accept(self)
            if self.is_lambda_type(arg_type):
                lam_name = self._lambda_display_name(arg, arg_type)
                raise CompileError(
                    arg.line,
                    arg.col,
                    f"'{lam_name}' is a lambda and cannot be passed to '{callee_label}': its type has no name, so no parameter can have it",
                )
            what_msg = (
                f"pass argument to '{callee_label}' parameter '{param.name}'"
                if node.is_callable_call
                else f"pass argument to parameter '{param.name}'"
            )
            self.check_assignable(
                arg,
                param.type_name,
                arg,
                what_msg,
            )
        node.type = m_info.return_type
        return node.type

    def visit_exit(self, node: ExitNode) -> None:
        val_type = node.value.accept(self)
        if self.is_lambda_type(val_type):
            lam_name = self._lambda_display_name(node.value, val_type)
            raise CompileError(
                node.value.line,
                node.value.col,
                f"'{lam_name}' is a lambda and cannot be returned from exit: its type has no name",
            )
        if self.current_member_fn is not None:
            want = self.current_member_fn.return_type
            if not (val_type == want or (want == "i64" and val_type == "i32")):
                if self.current_lambda_name is not None:
                    raise CompileError(
                        node.value.line,
                        node.value.col,
                        f"cannot return '{val_type}' from lambda '{self.current_lambda_name}' with return type '{want}'",
                    )
                raise CompileError(
                    node.value.line,
                    node.value.col,
                    f"cannot return '{val_type}' from member function '{self.current_member_fn.name}' with return type '{want}'",
                )
        elif self.current_fn is not None:
            want = self.current_fn.return_type
            if not (val_type == want or (want == "i64" and val_type == "i32")):
                raise CompileError(
                    node.value.line,
                    node.value.col,
                    f"cannot return '{val_type}' from function '{self.current_fn.name}' with return type '{want}'",
                )
        else:
            if val_type not in ("i32", "i64", "bool"):
                raise CompileError(
                    node.value.line,
                    node.value.col,
                    f"unsupported exit type '{val_type}'",
                )

    def _check_target_mut(self, n: MemberCallNode) -> None:
        target = n.target
        if isinstance(target, VarNode):
            if target.is_this_field:
                assert target.field_info is not None
                if not target.field_info.mutable:
                    if n.is_callable_call:
                        raise CompileError(
                            n.line,
                            n.col,
                            f"cannot call '{target.name}': its 'call' changes it, and it is not mut",
                        )
                    raise CompileError(
                        n.line,
                        n.col,
                        f"cannot call mutating member function '{n.func_name}' through const field '{target.name}'",
                    )
            else:
                assert target.decl is not None
                if not target.decl.mutable:
                    if n.is_callable_call:
                        raise CompileError(
                            n.line,
                            n.col,
                            f"cannot call '{target.name}': its 'call' changes it, and it is not mut",
                        )
                    raise CompileError(
                        n.line,
                        n.col,
                        f"cannot call mutating member function '{n.func_name}' on const variable '{target.name}'",
                    )
        elif isinstance(target, FieldAccessNode):
            callable_label = n.callable_name or target.fields[-1]
            if target.target is not None:
                assert target.target.type is not None
                curr_type = target.target.type
            elif target.is_this_field:
                assert target.this_field_info is not None
                if not target.this_field_info.mutable:
                    if n.is_callable_call:
                        raise CompileError(
                            n.line,
                            n.col,
                            f"cannot call '{callable_label}': its 'call' changes it, and '{target.obj_name}' is not mut",
                        )
                    raise CompileError(
                        n.line,
                        n.col,
                        f"cannot call mutating member function '{n.func_name}' through const field '{target.obj_name}'",
                    )
                curr_type = target.this_field_info.type_name
            else:
                assert target.decl is not None
                if not target.decl.mutable:
                    if n.is_callable_call:
                        raise CompileError(
                            n.line,
                            n.col,
                            f"cannot call '{callable_label}': its 'call' changes it, and '{target.obj_name}' is not mut",
                        )
                    raise CompileError(
                        n.line,
                        n.col,
                        f"cannot call mutating member function '{n.func_name}' on const variable '{target.obj_name}'",
                    )
                curr_type = target.decl.type_name

            for f_name in target.fields:
                f_info = self.structs[curr_type].fields_by_name[f_name]
                if not f_info.mutable:
                    if n.is_callable_call:
                        raise CompileError(
                            n.line,
                            n.col,
                            f"cannot call '{callable_label}': its 'call' changes it, and it is not mut",
                        )
                    raise CompileError(
                        n.line,
                        n.col,
                        f"cannot call mutating member function '{n.func_name}' through const field '{f_name}'",
                    )
                curr_type = f_info.type_name

    def check_mutation_rules_program(self, node: ProgramNode) -> None:
        def walk(n: Any) -> None:
            if n is None:
                return
            if isinstance(n, MemberCallNode):
                assert n.struct_name is not None
                s_info = self.structs[n.struct_name]
                m_info = s_info.member_fns[n.func_name]
                if m_info.is_mutating:
                    self._check_target_mut(n)
                walk(n.target)
                for a in n.args:
                    walk(a)
                return
            if isinstance(n, ProgramNode):
                for s in n.struct_defs:
                    for m in s.member_fns:
                        walk(m.body)
                for fn in n.fn_defs:
                    walk(fn.body)
                for stmt in n.statements:
                    walk(stmt)
                walk(n.exit)
            elif isinstance(n, BlockNode):
                for stmt in n.statements:
                    walk(stmt)
                walk(n.exit)
            elif isinstance(n, LambdaNode):
                walk(n.body)
                walk(n.decl_node)
            elif isinstance(n, DeclNode):
                for init in n.inits:
                    walk(init)
            elif isinstance(n, AssignNode):
                walk(n.value)
            elif isinstance(n, FieldAssignNode):
                walk(n.value)
            elif isinstance(n, IfNode):
                walk(n.cond)
                walk(n.then_block)
                walk(n.else_block)
            elif isinstance(n, WhileNode):
                walk(n.cond)
                walk(n.body)
            elif isinstance(n, PrintNode):
                walk(n.arg)
            elif isinstance(n, ExitNode):
                walk(n.value)
            elif isinstance(n, BinOpNode):
                walk(n.left)
                walk(n.right)
            elif isinstance(n, NotNode):
                walk(n.expr)
            elif isinstance(n, CallNode):
                if n.rewritten_call is not None:
                    walk(n.rewritten_call)
                else:
                    for a in n.args:
                        walk(a)
            elif isinstance(n, StructLiteralNode):
                for e in n.inits:
                    walk(e)
            elif isinstance(n, FieldAccessNode):
                if n.target is not None:
                    walk(n.target)

        walk(node)

    def _propagate_mutations(self, structs: list[StructDefNode]) -> None:
        all_member_fns: list[MemberFnInfo] = []
        for s in structs:
            all_member_fns.extend(self.structs[s.name].member_fns.values())

        changed = True
        while changed:
            changed = False
            for m_info in all_member_fns:
                if not m_info.is_mutating:
                    for (callee_struct, callee_name) in m_info.called_member_fns:
                        if self.structs[callee_struct].member_fns[callee_name].is_mutating:
                            m_info.is_mutating = True
                            changed = True
                            break

    def visit_program(self, node: ProgramNode) -> None:
        self.program_node = node
        for s in node.struct_defs:
            s.accept(self)

        for fn in node.fn_defs:
            if fn.name in ("i32", "i64", "bool"):
                raise CompileError(
                    fn.line, fn.col, f"cannot name function with built-in type '{fn.name}'"
                )
            if fn.name in self.functions:
                raise CompileError(
                    fn.line, fn.col, f"function '{fn.name}' is already declared"
                )
            if fn.name in self.structs:
                raise CompileError(
                    fn.line, fn.col, f"function '{fn.name}' clashes with struct '{fn.name}'"
                )
            if fn.return_type not in ("i32", "i64", "bool") and fn.return_type not in self.structs:
                raise CompileError(
                    fn.line, fn.col, f"unknown return type '{fn.return_type}' in function '{fn.name}'"
                )
            for p in fn.params:
                if p.type_name not in ("i32", "i64", "bool") and p.type_name not in self.structs:
                    raise CompileError(
                        p.line, p.col, f"unknown parameter type '{p.type_name}' in function '{fn.name}'"
                    )
            self.functions[fn.name] = FnInfo(
                fn.name, fn.params, fn.return_type, fn.line, fn.col
            )

        # Check member function bodies
        for s in node.struct_defs:
            s_info = self.structs[s.name]
            self.current_struct = s_info
            for m_node in s.member_fns:
                m_info = s_info.member_fns[m_node.name]
                self.current_member_fn = m_info
                saved_scopes = self.scopes
                self.scopes = [{}]
                for p in m_node.params:
                    decl = DeclNode(p.line, p.col, p.name, p.type_name, mutable=False, inits=[])
                    p.decl = decl
                    self.scopes[0][p.name] = decl

                m_node.body.accept(self)
                self.scopes = saved_scopes
                self.current_member_fn = None
            self.current_struct = None

        self._propagate_mutations(node.struct_defs)

        # Check global functions
        for fn in node.fn_defs:
            fn_info = self.functions[fn.name]
            saved_scopes = self.scopes
            self.scopes = [{}]
            for p in fn.params:
                decl = DeclNode(p.line, p.col, p.name, p.type_name, mutable=False, inits=[])
                p.decl = decl
                self.scopes[0][p.name] = decl

            self.current_fn = fn_info
            fn.body.accept(self)
            self.current_fn = None
            self.scopes = saved_scopes

        # Check top-level statements
        for stmt in node.statements:
            stmt.accept(self)
        node.exit.accept(self)

        self._propagate_mutations([*node.struct_defs, *node.lambda_struct_defs])

        # Check mutation rules across all AST call sites
        self.check_mutation_rules_program(node)


class CodeGenVisitor:
    def __init__(self, module: ir.Module) -> None:
        self.module = module
        self.i64_type = ir.IntType(64)
        self.i32_type = ir.IntType(32)
        self.i1_type = ir.IntType(1)
        self.i8_type = ir.IntType(8)
        self.struct_types: dict[str, ir.IdentifiedStructType] = {}
        self.struct_defs: dict[str, StructDefNode] = {}
        self.cached_strings: dict[str, ir.GlobalVariable] = {}
        self.fn_map: dict[str, ir.Function] = {}
        self.current_user_fn: FnDefNode | None = None
        self.current_this: ir.Value | None = None
        self.current_struct_name: str | None = None
        self.current_member_fn: MemberFnNode | None = None

        self.main_fn = ir.Function(
            self.module, ir.FunctionType(self.i32_type, []), name="main"
        )
        self.function = self.main_fn
        self.builder = ir.IRBuilder(self.main_fn.append_basic_block("entry"))

        self.printf_fn = ir.Function(
            self.module,
            ir.FunctionType(self.i32_type, [ir.PointerType(self.i8_type)], var_arg=True),
            name="printf",
        )

        self.scanf_fn = ir.Function(
            self.module,
            ir.FunctionType(self.i32_type, [ir.PointerType(self.i8_type)], var_arg=True),
            name="scanf",
        )

        fmt_int_bytes = b"Program exit with result %lld\n\0"
        self.fmt_int_var = self._create_global_string("fmt_int", fmt_int_bytes)

        fmt_bool_bytes = b"Program exit with result %s\n\0"
        self.fmt_bool_var = self._create_global_string("fmt_bool", fmt_bool_bytes)

        self.str_true_var = self._create_global_string("str_true", b"true\0")
        self.str_false_var = self._create_global_string("str_false", b"false\0")

        self.fmt_d_var = self._create_global_string("fmt_d", b"%d\0")
        self.fmt_d_nl_var = self._create_global_string("fmt_d_nl", b"%d\n\0")
        self.fmt_lld_var = self._create_global_string("fmt_lld", b"%lld\0")
        self.fmt_lld_nl_var = self._create_global_string("fmt_lld_nl", b"%lld\n\0")
        self.fmt_s_var = self._create_global_string("fmt_s", b"%s\0")
        self.fmt_s_nl_var = self._create_global_string("fmt_s_nl", b"%s\n\0")

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
            case "i32":
                return self.i32_type
            case _ if type_name in self.struct_types:
                return self.struct_types[type_name]
            case _:
                return self.i32_type

    def _get_cached_string(self, text: str) -> ir.GlobalVariable:
        if text not in self.cached_strings:
            data = text.encode("utf-8") + b"\0"
            idx = len(self.cached_strings)
            var = self._create_global_string(f"str_cache_{idx}", data)
            self.cached_strings[text] = var
        return self.cached_strings[text]

    def emit_print_str_literal(self, s: str) -> None:
        fmt_s = self.builder.bitcast(self.fmt_s_var, ir.PointerType(self.i8_type))
        g = self._get_cached_string(s)
        s_ptr = self.builder.bitcast(g, ir.PointerType(self.i8_type))
        self.builder.call(self.printf_fn, [fmt_s, s_ptr])

    def emit_print_struct(self, st_ptr: ir.Value, st_name: str) -> None:
        s_def = self.struct_defs[st_name]
        self.emit_print_str_literal(f"{st_name}{{")
        for idx, f in enumerate(s_def.fields):
            if idx > 0:
                self.emit_print_str_literal(", ")
            self.emit_print_str_literal(f"{f.name}: ")
            f_ptr = self.builder.gep(
                st_ptr,
                [ir.Constant(self.i32_type, 0), ir.Constant(self.i32_type, idx)],
                inbounds=True,
                name=f"{f.name}_gep",
            )
            if f.type_name in self.struct_types:
                self.emit_print_struct(f_ptr, f.type_name)
            elif f.type_name == "i32":
                val = self.builder.load(f_ptr, name=f.name)
                fmt_d = self.builder.bitcast(self.fmt_d_var, ir.PointerType(self.i8_type))
                self.builder.call(self.printf_fn, [fmt_d, val])
            elif f.type_name == "i64":
                val = self.builder.load(f_ptr, name=f.name)
                fmt_lld = self.builder.bitcast(self.fmt_lld_var, ir.PointerType(self.i8_type))
                self.builder.call(self.printf_fn, [fmt_lld, val])
            elif f.type_name == "bool":
                val = self.builder.load(f_ptr, name=f.name)
                t_ptr = self.builder.bitcast(self.str_true_var, ir.PointerType(self.i8_type))
                f_p = self.builder.bitcast(self.str_false_var, ir.PointerType(self.i8_type))
                sel = self.builder.select(val, t_ptr, f_p, name="bool_s")
                fmt_s = self.builder.bitcast(self.fmt_s_var, ir.PointerType(self.i8_type))
                self.builder.call(self.printf_fn, [fmt_s, sel])
        self.emit_print_str_literal("}")

    def visit_struct_def(self, node: StructDefNode) -> None:
        self.struct_defs[node.name] = node
        st = self.module.context.get_identified_type(node.name)
        field_types = [self._llvm_type(f.type_name) for f in node.fields]
        st.set_body(*field_types)
        self.struct_types[node.name] = st

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

    def visit_read(self, node: ReadNode) -> ir.Value:
        fmt_ptr = self.builder.bitcast(self.fmt_d_var, ir.PointerType(self.i8_type))
        read_slot = self.builder.alloca(self.i32_type, name="read_slot")
        self.builder.call(self.scanf_fn, [fmt_ptr, read_slot])
        return self.builder.load(read_slot, name="read_val")

    def visit_string_literal(self, node: StringLiteralNode) -> ir.Value:
        g = self._get_cached_string(node.value)
        return self.builder.bitcast(g, ir.PointerType(self.i8_type))

    def visit_var(self, node: VarNode) -> ir.Value:
        if node.is_this_field:
            assert self.current_this is not None and node.field_info is not None
            gep = self.builder.gep(
                self.current_this,
                [
                    ir.Constant(self.i32_type, 0),
                    ir.Constant(self.i32_type, node.field_info.index),
                ],
                inbounds=True,
                name=f"{node.name}_gep",
            )
            return self.builder.load(gep, name=node.name)
        assert node.decl is not None and node.decl.alloca is not None
        return self.builder.load(node.decl.alloca, name=node.name)

    def visit_field_access(self, node: FieldAccessNode) -> ir.Value:
        if node.target is not None:
            val = node.target.accept(self)
            for idx in node.field_indices:
                val = self.builder.extract_value(val, idx, name="field_val")
            return val

        if node.is_this_field:
            assert self.current_this is not None and node.this_field_info is not None
            ptr = self.builder.gep(
                self.current_this,
                [
                    ir.Constant(self.i32_type, 0),
                    ir.Constant(self.i32_type, node.this_field_info.index),
                ],
                inbounds=True,
                name=f"{node.obj_name}_gep",
            )
        else:
            assert node.decl is not None and node.decl.alloca is not None
            ptr = node.decl.alloca

        for idx in node.field_indices:
            ptr = self.builder.gep(
                ptr,
                [
                    ir.Constant(self.i32_type, 0),
                    ir.Constant(self.i32_type, idx),
                ],
                inbounds=True,
                name="field_gep",
            )
        return self.builder.load(ptr, name="field_val")

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

    def visit_not(self, node: NotNode) -> ir.Value:
        val = node.expr.accept(self)
        return self.builder.not_(val, name="not")

    def visit_struct_literal(self, node: StructLiteralNode) -> ir.Value:
        st = self.struct_types[node.type]
        agg_val: ir.Value = ir.Constant(st, ir.Undefined)
        for idx, expr in enumerate(node.inits):
            val = expr.accept(self)
            target_type = st.elements[idx]
            if (
                isinstance(target_type, ir.IntType)
                and target_type.width == 64
                and expr.type == "i32"
            ):
                val = self.builder.sext(val, self.i64_type, name="wide")
            agg_val = self.builder.insert_value(agg_val, val, idx, name=f"ins_{idx}")
        return agg_val

    def visit_decl(self, node: DeclNode) -> None:
        llvm_t = self._llvm_type(node.type_name)
        with self.builder.goto_entry_block():
            slot = self.builder.alloca(llvm_t, name=node.name)
        node.alloca = slot

        if node.type_name in self.struct_types:
            st = self.struct_types[node.type_name]
            if len(node.inits) == 1 and node.inits[0].type == node.type_name:
                src_val = node.inits[0].accept(self)
                self.builder.store(src_val, slot)
            else:
                for idx, expr in enumerate(node.inits):
                    val = expr.accept(self)
                    target_type = st.elements[idx]
                    if (
                        isinstance(target_type, ir.IntType)
                        and target_type.width == 64
                        and expr.type == "i32"
                    ):
                        val = self.builder.sext(val, self.i64_type, name="wide")
                    field_ptr = self.builder.gep(
                        slot,
                        [
                            ir.Constant(self.i32_type, 0),
                            ir.Constant(self.i32_type, idx),
                        ],
                        inbounds=True,
                        name=f"{node.name}_{idx}",
                    )
                    self.builder.store(val, field_ptr)
        else:
            init_val = node.inits[0].accept(self)
            init_val = self.coerce(init_val, node.inits[0].type, node.type_name)
            self.builder.store(init_val, slot)

    def visit_assign(self, node: AssignNode) -> None:
        if node.is_this_field:
            assert self.current_this is not None and node.field_info is not None
            gep = self.builder.gep(
                self.current_this,
                [
                    ir.Constant(self.i32_type, 0),
                    ir.Constant(self.i32_type, node.field_info.index),
                ],
                inbounds=True,
                name=f"{node.name}_gep",
            )
            val = node.value.accept(self)
            if node.field_info.type_name in ("i32", "i64"):
                val = self.coerce(val, node.value.type, node.field_info.type_name)
            self.builder.store(val, gep)
            return

        assert node.decl is not None and node.decl.alloca is not None
        val = node.value.accept(self)
        if node.decl.type_name in ("i32", "i64"):
            val = self.coerce(val, node.value.type, node.decl.type_name)
        self.builder.store(val, node.decl.alloca)

    def visit_field_assign(self, node: FieldAssignNode) -> None:
        if node.is_this_field:
            assert self.current_this is not None and node.this_field_info is not None
            ptr = self.builder.gep(
                self.current_this,
                [
                    ir.Constant(self.i32_type, 0),
                    ir.Constant(self.i32_type, node.this_field_info.index),
                ],
                inbounds=True,
                name=f"{node.obj_name}_gep",
            )
        else:
            assert node.decl is not None and node.decl.alloca is not None
            ptr = node.decl.alloca

        for idx in node.field_indices:
            ptr = self.builder.gep(
                ptr,
                [
                    ir.Constant(self.i32_type, 0),
                    ir.Constant(self.i32_type, idx),
                ],
                inbounds=True,
                name="field_gep",
            )
        val = node.value.accept(self)
        if node.target_type in ("i32", "i64"):
            val = self.coerce(val, node.value.type, node.target_type)
        self.builder.store(val, ptr)

    def visit_block(self, node: BlockNode) -> None:
        for stmt in node.statements:
            stmt.accept(self)
        if node.exit is not None:
            node.exit.accept(self)

    def visit_if(self, node: IfNode) -> None:
        cond_val = node.cond.accept(self)
        then_bb = self.function.append_basic_block("then")
        else_bb = (
            self.function.append_basic_block("else") if node.else_block is not None else None
        )
        merge_bb = self.function.append_basic_block("merge")

        self.builder.cbranch(cond_val, then_bb, else_bb if else_bb is not None else merge_bb)

        self.builder.position_at_end(then_bb)
        node.then_block.accept(self)
        if not self.builder.block.is_terminated:
            self.builder.branch(merge_bb)

        if node.else_block is not None and else_bb is not None:
            self.builder.position_at_end(else_bb)
            node.else_block.accept(self)
            if not self.builder.block.is_terminated:
                self.builder.branch(merge_bb)

        self.builder.position_at_end(merge_bb)

    def visit_while(self, node: WhileNode) -> None:
        cond_bb = self.function.append_basic_block("cond")
        body_bb = self.function.append_basic_block("body")
        end_bb = self.function.append_basic_block("end")

        if not self.builder.block.is_terminated:
            self.builder.branch(cond_bb)

        self.builder.position_at_end(cond_bb)
        cond_val = node.cond.accept(self)
        self.builder.cbranch(cond_val, body_bb, end_bb)

        self.builder.position_at_end(body_bb)
        node.body.accept(self)
        if not self.builder.block.is_terminated:
            self.builder.branch(cond_bb)

        self.builder.position_at_end(end_bb)

    def visit_print(self, node: PrintNode) -> None:
        arg_type = node.arg.type
        if arg_type == "string":
            str_ptr = node.arg.accept(self)
            fmt_s_nl = self.builder.bitcast(self.fmt_s_nl_var, ir.PointerType(self.i8_type))
            self.builder.call(self.printf_fn, [fmt_s_nl, str_ptr])
        elif arg_type == "i32":
            val = node.arg.accept(self)
            fmt_d_nl = self.builder.bitcast(self.fmt_d_nl_var, ir.PointerType(self.i8_type))
            self.builder.call(self.printf_fn, [fmt_d_nl, val])
        elif arg_type == "i64":
            val = node.arg.accept(self)
            fmt_lld_nl = self.builder.bitcast(self.fmt_lld_nl_var, ir.PointerType(self.i8_type))
            self.builder.call(self.printf_fn, [fmt_lld_nl, val])
        elif arg_type == "bool":
            val = node.arg.accept(self)
            fmt_s_nl = self.builder.bitcast(self.fmt_s_nl_var, ir.PointerType(self.i8_type))
            t_ptr = self.builder.bitcast(self.str_true_var, ir.PointerType(self.i8_type))
            f_ptr = self.builder.bitcast(self.str_false_var, ir.PointerType(self.i8_type))
            selected_str = self.builder.select(val, t_ptr, f_ptr, name="bool_str")
            self.builder.call(self.printf_fn, [fmt_s_nl, selected_str])
        elif arg_type in self.struct_types:
            st_ptr: ir.Value
            if isinstance(node.arg, VarNode):
                if node.arg.is_this_field:
                    assert self.current_this is not None and node.arg.field_info is not None
                    st_ptr = self.builder.gep(
                        self.current_this,
                        [
                            ir.Constant(self.i32_type, 0),
                            ir.Constant(self.i32_type, node.arg.field_info.index),
                        ],
                        inbounds=True,
                        name=f"{node.arg.name}_gep",
                    )
                else:
                    assert node.arg.decl is not None and node.arg.decl.alloca is not None
                    st_ptr = node.arg.decl.alloca
            elif isinstance(node.arg, FieldAccessNode):
                if node.arg.target is not None:
                    val = node.arg.target.accept(self)
                    temp_slot = self.builder.alloca(val.type, name="temp_print_receiver")
                    self.builder.store(val, temp_slot)
                    ptr = temp_slot
                elif node.arg.is_this_field:
                    assert self.current_this is not None and node.arg.this_field_info is not None
                    ptr = self.builder.gep(
                        self.current_this,
                        [
                            ir.Constant(self.i32_type, 0),
                            ir.Constant(self.i32_type, node.arg.this_field_info.index),
                        ],
                        inbounds=True,
                        name="field_base_gep",
                    )
                else:
                    assert node.arg.decl is not None and node.arg.decl.alloca is not None
                    ptr = node.arg.decl.alloca

                for idx in node.arg.field_indices:
                    ptr = self.builder.gep(
                        ptr,
                        [
                            ir.Constant(self.i32_type, 0),
                            ir.Constant(self.i32_type, idx),
                        ],
                        inbounds=True,
                        name="field_chain_gep",
                    )
                st_ptr = ptr
            else:
                val = node.arg.accept(self)
                temp_slot = self.builder.alloca(val.type, name="temp_print_struct")
                self.builder.store(val, temp_slot)
                st_ptr = temp_slot

            self.emit_print_struct(st_ptr, arg_type)
            self.emit_print_str_literal("\n")

    def visit_call(self, node: CallNode) -> ir.Value:
        if node.rewritten_call is not None:
            return self.visit_member_call(node.rewritten_call)

        if node.is_this_call:
            callee = self.fn_map[f"{node.struct_name}_{node.func_name}"]
            assert self.current_this is not None
            arg_vals: list[ir.Value] = [self.current_this]
            for arg, param_type in zip(node.args, callee.function_type.args[1:]):
                val = arg.accept(self)
                if isinstance(param_type, ir.IntType) and param_type.width == 64 and arg.type == "i32":
                    val = self.builder.sext(val, self.i64_type, name="wide")
                arg_vals.append(val)
            return self.builder.call(callee, arg_vals, name=f"call_{node.func_name}")

        callee = self.fn_map[node.func_name]
        arg_vals = []
        for arg, param_type in zip(node.args, callee.function_type.args):
            val = arg.accept(self)
            if isinstance(param_type, ir.IntType) and param_type.width == 64 and arg.type == "i32":
                val = self.builder.sext(val, self.i64_type, name="wide")
            arg_vals.append(val)
        return self.builder.call(callee, arg_vals, name=f"call_{node.func_name}")

    def visit_member_call(self, node: MemberCallNode) -> ir.Value:
        assert node.struct_name is not None
        callee = self.fn_map[f"{node.struct_name}_{node.func_name}"]
        target_ptr: ir.Value
        if isinstance(node.target, VarNode):
            if node.target.is_this_field:
                assert self.current_this is not None and node.target.field_info is not None
                target_ptr = self.builder.gep(
                    self.current_this,
                    [
                        ir.Constant(self.i32_type, 0),
                        ir.Constant(self.i32_type, node.target.field_info.index),
                    ],
                    inbounds=True,
                    name="this_field_target_gep",
                )
            else:
                assert node.target.decl is not None and node.target.decl.alloca is not None
                target_ptr = node.target.decl.alloca
        elif isinstance(node.target, FieldAccessNode):
            if node.target.target is not None:
                val = node.target.target.accept(self)
                temp_slot = self.builder.alloca(val.type, name="temp_receiver_slot")
                self.builder.store(val, temp_slot)
                ptr = temp_slot
            elif node.target.is_this_field:
                assert self.current_this is not None and node.target.this_field_info is not None
                ptr = self.builder.gep(
                    self.current_this,
                    [
                        ir.Constant(self.i32_type, 0),
                        ir.Constant(self.i32_type, node.target.this_field_info.index),
                    ],
                    inbounds=True,
                    name="field_base_gep",
                )
            else:
                assert node.target.decl is not None and node.target.decl.alloca is not None
                ptr = node.target.decl.alloca

            for idx in node.target.field_indices:
                ptr = self.builder.gep(
                    ptr,
                    [
                        ir.Constant(self.i32_type, 0),
                        ir.Constant(self.i32_type, idx),
                    ],
                    inbounds=True,
                    name="field_chain_gep",
                )
            target_ptr = ptr
        else:
            val = node.target.accept(self)
            temp_slot = self.builder.alloca(val.type, name="temp_receiver_slot")
            self.builder.store(val, temp_slot)
            target_ptr = temp_slot

        arg_vals: list[ir.Value] = [target_ptr]
        for arg, param_type in zip(node.args, callee.function_type.args[1:]):
            val = arg.accept(self)
            if isinstance(param_type, ir.IntType) and param_type.width == 64 and arg.type == "i32":
                val = self.builder.sext(val, self.i64_type, name="wide")
            arg_vals.append(val)
        return self.builder.call(callee, arg_vals, name=f"call_{node.func_name}")

    def visit_lambda(self, node: LambdaNode) -> None:
        assert node.decl_node is not None
        node.decl_node.accept(self)

    def visit_exit(self, node: ExitNode) -> None:
        exit_val = node.value.accept(self)
        if self.current_member_fn is not None:
            ret_type = self.current_member_fn.return_type
            if ret_type == "i64" and node.value.type == "i32":
                exit_val = self.builder.sext(exit_val, self.i64_type, name="wide")
            self.builder.ret(exit_val)
            return

        if self.current_user_fn is not None:
            ret_type = self.current_user_fn.return_type
            if ret_type == "i64" and node.value.type == "i32":
                exit_val = self.builder.sext(exit_val, self.i64_type, name="wide")
            self.builder.ret(exit_val)
            return

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
        all_structs = [*node.struct_defs, *node.lambda_struct_defs]
        for s in all_structs:
            s.accept(self)

        # Declare member functions
        for s in all_structs:
            for fn in s.member_fns:
                fn_name = f"{s.name}_{fn.name}"
                this_type = ir.PointerType(self.struct_types[s.name])
                param_types = [this_type] + [self._llvm_type(p.type_name) for p in fn.params]
                ret_type = self._llvm_type(fn.return_type)
                fn_type = ir.FunctionType(ret_type, param_types)
                llvm_fn = ir.Function(self.module, fn_type, name=fn_name)
                self.fn_map[fn_name] = llvm_fn

        # Declare global functions
        for fn in node.fn_defs:
            param_types = [self._llvm_type(p.type_name) for p in fn.params]
            ret_type = self._llvm_type(fn.return_type)
            fn_type = ir.FunctionType(ret_type, param_types)
            llvm_fn = ir.Function(self.module, fn_type, name=f"user_{fn.name}")
            self.fn_map[fn.name] = llvm_fn

        saved_builder = self.builder
        saved_function = self.function

        # Generate member function bodies
        for s in all_structs:
            for fn in s.member_fns:
                llvm_fn = self.fn_map[f"{s.name}_{fn.name}"]
                self.function = llvm_fn
                self.builder = ir.IRBuilder(llvm_fn.append_basic_block("entry"))
                self.current_member_fn = fn
                self.current_struct_name = s.name
                self.current_this = llvm_fn.args[0]
                self.current_this.name = "this"

                for param, arg in zip(fn.params, llvm_fn.args[1:]):
                    arg.name = param.name
                    param_slot = self.builder.alloca(arg.type, name=f"{param.name}_slot")
                    self.builder.store(arg, param_slot)
                    param.decl.alloca = param_slot

                fn.body.accept(self)
                self.current_member_fn = None
                self.current_struct_name = None
                self.current_this = None

        # Generate global function bodies
        for fn in node.fn_defs:
            llvm_fn = self.fn_map[fn.name]
            self.function = llvm_fn
            self.builder = ir.IRBuilder(llvm_fn.append_basic_block("entry"))
            self.current_user_fn = fn

            for param, arg in zip(fn.params, llvm_fn.args):
                arg.name = param.name
                param_slot = self.builder.alloca(arg.type, name=f"{param.name}_slot")
                self.builder.store(arg, param_slot)
                param.decl.alloca = param_slot

            fn.body.accept(self)

        self.current_user_fn = None
        self.builder = saved_builder
        self.function = saved_function

        for stmt in node.statements:
            stmt.accept(self)
        node.exit.accept(self)


def parse_ast(source_bytes: bytes) -> ProgramNode:
    token_lines = lex(source_bytes)
    return Parser(token_lines).parse_program()


def check_ast(source_bytes: bytes) -> ProgramNode:
    ast = parse_ast(source_bytes)
    checker = SemanticChecker()
    checker.visit_program(ast)
    return ast


def compile_source(source_bytes: bytes) -> ir.Module:
    ast = check_ast(source_bytes)
    context = ir.Context()
    module = ir.Module(name="practice6", context=context)
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

    if len(sys.argv) == 3 and sys.argv[1] == "--ast-checked":
        try:
            with open(sys.argv[2], "rb") as f:
                content = f.read()
            ast = check_ast(content)
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
            "Usage: python3 compiler.py <input.txt> <output.ll> \n"
            "OR python3 compiler.py --ast <input.txt> \n"
            "OR python3 compiler.py --ast-checked <input.txt> \n"
            "OR python3 compiler.py --lex <input.txt> \n",
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
