from compiler import (
    AssignNode,
    BinOpNode,
    BlockNode,
    CallNode,
    DeclNode,
    ExitNode,
    ExprNode,
    FieldAccessNode,
    FieldAssignNode,
    FnDefNode,
    IfNode,
    LambdaNode,
    MemberCallNode,
    MemberFnNode,
    Node,
    NotNode,
    PrintNode,
    ProgramNode,
    ReadNode,
    StmtNode,
    StructDefNode,
    StructLiteralNode,
    VarNode,
    WhileNode,
)


def has_call_or_read(expr: ExprNode) -> bool:
    match expr:
        case ReadNode() | CallNode() | MemberCallNode():
            return True
        case BinOpNode(left=left, right=right):
            return has_call_or_read(left) or has_call_or_read(right)
        case NotNode(expr=inner):
            return has_call_or_read(inner)
        case StructLiteralNode(inits=inits):
            return any(has_call_or_read(e) for e in inits)
        case FieldAccessNode(target=target) if target is not None:
            return has_call_or_read(target)
        case _:
            return False


class UseCounter:
    def __init__(self) -> None:
        self.reads: dict[int, int] = {}
        self.fn_calls: dict[str, int] = {}

    def read(self, decl: DeclNode | None) -> None:
        if decl is not None:
            self.reads[id(decl)] = self.reads.get(id(decl), 0) + 1

    def _noop(self, _: Node) -> None:
        pass

    visit_const = visit_bool = visit_read = visit_string_literal = _noop

    def visit_var(self, n: VarNode) -> None:
        self.read(n.decl)

    def visit_field_access(self, n: FieldAccessNode) -> None:
        if n.target is not None:
            n.target.accept(self)
        else:
            self.read(n.decl)

    def visit_struct_literal(self, n: StructLiteralNode) -> None:
        for e in n.inits:
            e.accept(self)

    def visit_call(self, n: CallNode) -> None:
        if n.rewritten_call is not None:
            n.rewritten_call.accept(self)
        else:
            if not n.is_this_call:
                self.fn_calls[n.func_name] = self.fn_calls.get(n.func_name, 0) + 1
            for a in n.args:
                a.accept(self)

    def visit_member_call(self, n: MemberCallNode) -> None:
        n.target.accept(self)
        for a in n.args:
            a.accept(self)

    def visit_binop(self, n: BinOpNode) -> None:
        n.left.accept(self)
        n.right.accept(self)

    def visit_not(self, n: NotNode) -> None:
        n.expr.accept(self)

    def visit_decl(self, n: DeclNode) -> None:
        self.reads.setdefault(id(n), 0)
        if any(has_call_or_read(e) for e in n.inits):
            self.read(n)
        for e in n.inits:
            e.accept(self)

    def visit_assign(self, n: AssignNode) -> None:
        if has_call_or_read(n.value):
            self.read(n.decl)
        n.value.accept(self)

    visit_field_assign = visit_assign

    def visit_exit(self, n: ExitNode) -> None:
        n.value.accept(self)

    def visit_print(self, n: PrintNode) -> None:
        n.arg.accept(self)

    def visit_block(self, n: BlockNode) -> None:
        for s in n.statements:
            s.accept(self)
        if n.exit is not None:
            n.exit.accept(self)

    def visit_if(self, n: IfNode) -> None:
        n.cond.accept(self)
        n.then_block.accept(self)
        if n.else_block is not None:
            n.else_block.accept(self)

    def visit_while(self, n: WhileNode) -> None:
        n.cond.accept(self)
        n.body.accept(self)

    def visit_lambda(self, n: LambdaNode) -> None:
        if n.decl_node is not None:
            for e in n.decl_node.inits:
                e.accept(self)
        n.body.accept(self)

    def visit_struct_def(self, n: StructDefNode) -> None:
        for fn in n.member_fns:
            fn.accept(self)

    def visit_fn_def(self, n: FnDefNode) -> None:
        self.fn_calls.setdefault(n.name, 0)
        n.body.accept(self)

    def visit_member_fn(self, n: MemberFnNode) -> None:
        n.body.accept(self)

    def visit_program(self, n: ProgramNode) -> None:
        for item in (*n.struct_defs, *n.fn_defs, *n.statements, n.exit):
            item.accept(self)


class Pruner:
    def __init__(self, dead_vars: set[int], dead_fns: set[str]) -> None:
        self.dead_vars = dead_vars
        self.dead_fns = dead_fns

    def prune_stmts(self, stmts: list[StmtNode]) -> list[StmtNode]:
        kept: list[StmtNode] = []
        for s in stmts:
            match s:
                case DeclNode() if id(s) in self.dead_vars:
                    continue
                case AssignNode(decl=d) | FieldAssignNode(decl=d) if d is not None and id(d) in self.dead_vars:
                    continue
                case IfNode(then_block=tb, else_block=eb):
                    tb.statements = self.prune_stmts(tb.statements)
                    if eb is not None:
                        eb.statements = self.prune_stmts(eb.statements)
                case WhileNode(body=b) | LambdaNode(body=b):
                    b.statements = self.prune_stmts(b.statements)
            kept.append(s)
        return kept

    def prune(self, tree: ProgramNode) -> None:
        for s in tree.struct_defs:
            for m in s.member_fns:
                m.body.statements = self.prune_stmts(m.body.statements)
        tree.fn_defs = [fn for fn in tree.fn_defs if fn.name not in self.dead_fns]
        for fn in tree.fn_defs:
            fn.body.statements = self.prune_stmts(fn.body.statements)
        tree.statements = self.prune_stmts(tree.statements)


def remove_unused(tree: ProgramNode) -> ProgramNode:
    while True:
        counter = UseCounter()
        tree.accept(counter)
        dead_vars = {d for d, k in counter.reads.items() if k == 0}
        dead_fns = {f for f, k in counter.fn_calls.items() if k == 0}
        if not dead_vars and not dead_fns:
            return tree
        Pruner(dead_vars, dead_fns).prune(tree)

