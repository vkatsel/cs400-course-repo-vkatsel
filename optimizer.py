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


class EffectAnalyzer:
    def __init__(self, tree: ProgramNode) -> None:
        self.tree = tree
        self.direct_effects: set[str] = set()
        self.call_graph: dict[str, set[str]] = {}

    def _callee_key(self, node: CallNode | MemberCallNode) -> str | None:
        match node:
            case CallNode(rewritten_call=rewritten) if rewritten is not None:
                return self._callee_key(rewritten)
            case CallNode(is_this_call=True, struct_name=st, func_name=fn) if st is not None:
                return f"mfn:{st}:{fn}"
            case CallNode(is_this_call=False, func_name=fn):
                return f"fn:{fn}"
            case MemberCallNode(struct_name=st, func_name=fn) if st is not None:
                return f"mfn:{st}:{fn}"
            case _:
                return None

    def _analyze_body(self, key: str, body: BlockNode) -> None:
        has_direct = False
        callees: set[str] = set()

        def walk(n: Node | None) -> None:
            nonlocal has_direct
            if n is None:
                return
            match n:
                case PrintNode() | ReadNode() | WhileNode():
                    has_direct = True
                case CallNode() | MemberCallNode():
                    callee = self._callee_key(n)
                    if callee is not None:
                        callees.add(callee)
            match n:
                case BlockNode(statements=stmts, exit=ex):
                    for s in stmts:
                        walk(s)
                    walk(ex)
                case IfNode(cond=c, then_block=tb, else_block=eb):
                    walk(c)
                    walk(tb)
                    walk(eb)
                case WhileNode(cond=c, body=b):
                    walk(c)
                    walk(b)
                case PrintNode(arg=a):
                    walk(a)
                case ExitNode(value=v):
                    walk(v)
                case DeclNode(inits=inits):
                    for init in inits:
                        walk(init)
                case AssignNode(value=v) | FieldAssignNode(value=v):
                    walk(v)
                case LambdaNode(body=b):
                    walk(b)
                case BinOpNode(left=l, right=r):
                    walk(l)
                    walk(r)
                case NotNode(expr=e):
                    walk(e)
                case StructLiteralNode(inits=inits):
                    for init in inits:
                        walk(init)
                case CallNode(args=args, rewritten_call=rewritten):
                    if rewritten is not None:
                        walk(rewritten)
                    else:
                        for a in args:
                            walk(a)
                case MemberCallNode(target=t, args=args):
                    walk(t)
                    for a in args:
                        walk(a)
                case _:
                    pass

        walk(body)
        if has_direct:
            self.direct_effects.add(key)
        self.call_graph[key] = callees

    def compute_effects(self) -> set[str]:
        all_keys: list[str] = []
        all_structs: list[StructDefNode] = list(self.tree.struct_defs)
        if hasattr(self.tree, "lambda_struct_defs"):
            all_structs.extend(self.tree.lambda_struct_defs)

        def collect_lambdas(stmts: list[StmtNode]) -> None:
            for s in stmts:
                match s:
                    case LambdaNode(struct_def=st_def, body=b):
                        if st_def is not None and st_def not in all_structs:
                            all_structs.append(st_def)
                        collect_lambdas(b.statements)
                    case IfNode(then_block=tb, else_block=eb):
                        collect_lambdas(tb.statements)
                        if eb is not None:
                            collect_lambdas(eb.statements)
                    case WhileNode(body=b):
                        collect_lambdas(b.statements)
                    case _:
                        pass

        collect_lambdas(self.tree.statements)
        for fn in self.tree.fn_defs:
            collect_lambdas(fn.body.statements)
        for s in self.tree.struct_defs:
            for m in s.member_fns:
                collect_lambdas(m.body.statements)

        for s in all_structs:
            for m in s.member_fns:
                key = f"mfn:{s.name}:{m.name}"
                all_keys.append(key)
                self._analyze_body(key, m.body)
                if self._is_mutating_mfn(s.name, m.name, all_structs):
                    self.direct_effects.add(key)

        for fn in self.tree.fn_defs:
            key = f"fn:{fn.name}"
            all_keys.append(key)
            self._analyze_body(key, fn.body)

        effects: set[str] = set(self.direct_effects)

        # Detect recursion/cycles
        for start_k in all_keys:
            if start_k in effects:
                continue
            visited: set[str] = set()
            stack = list(self.call_graph.get(start_k, set()))
            while stack:
                curr = stack.pop()
                if curr == start_k:
                    effects.add(start_k)
                    break
                if curr not in visited:
                    visited.add(curr)
                    stack.extend(self.call_graph.get(curr, set()))

        # Fixpoint propagation
        changed = True
        while changed:
            changed = False
            for caller, callees in self.call_graph.items():
                if caller not in effects:
                    if any(c in effects for c in callees):
                        effects.add(caller)
                        changed = True

        return effects

    def _is_mutating_mfn(self, struct_name: str, fn_name: str, structs: list[StructDefNode] | None = None) -> bool:
        target_structs = structs if structs is not None else self.tree.struct_defs
        for s in target_structs:
            if s.name == struct_name:
                for m in s.member_fns:
                    if m.name == fn_name:
                        return self._mfn_has_mutation(m.body)
        return False

    def _mfn_has_mutation(self, body: BlockNode) -> bool:
        has_mut = False

        def check(n: Node | None) -> None:
            nonlocal has_mut
            if n is None or has_mut:
                return
            match n:
                case AssignNode(is_this_field=True) | FieldAssignNode(is_this_field=True):
                    has_mut = True
                case BlockNode(statements=stmts, exit=ex):
                    for s in stmts:
                        check(s)
                    check(ex)
                case IfNode(then_block=tb, else_block=eb):
                    check(tb)
                    check(eb)
                case WhileNode(body=b):
                    check(b)
                case _:
                    pass

        check(body)
        return has_mut


def has_effect(expr: ExprNode, effect_keys: set[str]) -> bool:
    match expr:
        case ReadNode():
            return True
        case CallNode(rewritten_call=rewritten) if rewritten is not None:
            return has_effect(rewritten, effect_keys)
        case CallNode(is_this_call=True, struct_name=st, func_name=fn) if st is not None:
            return f"mfn:{st}:{fn}" in effect_keys
        case CallNode(is_this_call=False, func_name=fn):
            return f"fn:{fn}" in effect_keys
        case MemberCallNode(struct_name=st, func_name=fn) if st is not None:
            return f"mfn:{st}:{fn}" in effect_keys or has_effect(expr.target, effect_keys)
        case BinOpNode(left=left, right=right):
            return has_effect(left, effect_keys) or has_effect(right, effect_keys)
        case NotNode(expr=inner):
            return has_effect(inner, effect_keys)
        case StructLiteralNode(inits=inits):
            return any(has_effect(e, effect_keys) for e in inits)
        case FieldAccessNode(target=target) if target is not None:
            return has_effect(target, effect_keys)
        case _:
            return False


class UseCounter:
    def __init__(self, effect_keys: set[str]) -> None:
        self.reads: dict[int, int] = {}
        self.fn_calls: dict[str, int] = {}
        self.effect_keys = effect_keys

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
        if any(has_effect(e, self.effect_keys) for e in n.inits):
            self.read(n)
        for e in n.inits:
            e.accept(self)

    def visit_assign(self, n: AssignNode) -> None:
        if has_effect(n.value, self.effect_keys):
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
        effects = EffectAnalyzer(tree).compute_effects()
        counter = UseCounter(effects)
        tree.accept(counter)
        dead_vars = {d for d, k in counter.reads.items() if k == 0}
        dead_fns = {f for f, k in counter.fn_calls.items() if k == 0}
        if not dead_vars and not dead_fns:
            return tree
        Pruner(dead_vars, dead_fns).prune(tree)
