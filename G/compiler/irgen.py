"""
Hạ mã Typed AST → G-IR.

VỊ TRÍ TRONG ĐƯỜNG ỐNG
======================
    parser → AST → checker (chú thích kiểu) → irgen (Ở ĐÂY) → G-IR → backend

Pass này chạy SAU checker, nên mọi biểu thức đã có `e.gtype`. Nó KHÔNG kiểm tra
lỗi người dùng — checker đã làm. Việc của nó là biến cây cú pháp thành CFG
phẳng, và trong quá trình đó biến các ngữ nghĩa vốn "ẩn trong chuỗi C" thành
lệnh IR nhìn thấy được:

  * `defer` → nhân bản lời gọi ở MỌI điểm thoát (return/break/continue/rơi khỏi
    block), theo thứ tự LIFO. Giá trị trả về được chốt vào temp TRƯỚC khi chạy
    defer — đúng ngữ nghĩa Zig/Go, và giờ verifier nhìn thấy được thứ tự đó.
  * `for mut x in arr` → `elemaddr` rồi ghi thẳng qua địa chỉ, thay vì mẹo
    "biến C thực ra là con trỏ".
  * mảng gán bằng `=` → `memcpy` tường minh (C thì âm thầm chia sẻ con trỏ).
  * `match` → `switch` khi mọi pattern là hằng nguyên; ngược lại chuỗi `branch`.

GIỚI HẠN ĐÃ BIẾT (ghi rõ, không giấu)
=====================================
Đây là pass hạ mã của Phase 1: mục tiêu là CHỨNG MINH IR biểu diễn được toàn bộ
ngôn ngữ, chưa phải sinh mã. Những chỗ chưa hạ chi tiết được gói vào lệnh
`intrinsic` mang đủ thông tin để backend sau này bung ra:

  * built-in in ấn/format (`println`, `format`, `dbg`, `assert_*`) → `intrinsic`
    với `extra['name']`; chuỗi định dạng đã được checker kiểm.
  * `asm` → `intrinsic` op='asm' giữ nguyên template/toán hạng.
  * method của `str` → `call` tới hàm runtime tương ứng (`extra['callee']`).

Backend C hiện tại KHÔNG dùng pass này (nó vẫn đi thẳng từ AST). Xem
ARCHITECTURE.md §3 để biết chiến lược chuyển đổi.
"""

from . import ast_nodes as A
from . import ir as I
from . import types as T


class IRGenError(Exception):
    pass


class IRGen:
    def __init__(self, prog: A.Program, module_name="main"):
        self.prog = prog
        self.mod = I.Module(name=module_name)
        self._n = 0
        self.fn = None            # I.Func đang sinh
        self.blk = None           # I.Block đang sinh
        self.scopes = []          # [{tên G: (Value địa chỉ, GType)}]
        self.loops = []           # [(nhãn_continue, nhãn_break, độ_sâu_defer)]
        self.defers = []          # ngăn xếp scope: [[stmt, ...], ...]
        self._dead = False        # đang sinh mã trong vùng không thể tới?
        self.structs = {}         # tên -> [(trường, GType)]
        self.enums = {}           # tên -> {biến thể: giá trị}
        self.enum_of_variant = {}

    # ------------------------------------------------------------------
    # tiện ích
    # ------------------------------------------------------------------
    def tmp(self, ty, hint="t") -> I.Value:
        self._n += 1
        return I.temp(f"{hint}{self._n}", ty)

    def label(self, hint="L") -> str:
        self._n += 1
        return f"{hint}{self._n}"

    def block(self, label) -> I.Block:
        b = I.Block(label)
        self.fn.blocks.append(b)
        return b

    def start(self, b: I.Block):
        self.blk = b

    def emit(self, op, args=None, ty=None, dst=None, node=None, **extra):
        """Phát một lệnh vào block hiện tại. Trả về dst (nếu có)."""
        if self.blk is None or self.blk.term is not None:
            # Mã nằm sau một điểm thoát (checker đã cảnh báo "không thể tới
            # được"). Mở một block mới đánh dấu 'dead' để IR vẫn đúng cấu trúc;
            # verifier bỏ qua block có tiền tố này.
            dead = I.Block(self.label("dead"))
            self.fn.blocks.append(dead)
            self.blk = dead
        ins = I.Instr(op, dst=dst, args=list(args or []), type=ty,
                      extra=extra,
                      line=getattr(node, "line", 0), col=getattr(node, "col", 0))
        self.blk.instrs.append(ins)
        return dst

    def emit_val(self, op, args=None, ty=None, node=None, hint="t", **extra):
        d = self.tmp(ty, hint)
        self.emit(op, args, ty=ty, dst=d, node=node, **extra)
        return d

    def term(self, t: I.Term):
        if self.blk is not None and self.blk.term is None:
            self.blk.term = t

    def gtype(self, e):
        return getattr(e, "gtype", None) or T.UNKNOWN

    def _targets_label(self, lbl) -> bool:
        """Có block nào trong hàm hiện tại nhảy tới nhãn này không? Dùng để
        biết một vòng lặp có 'break' hay là vô hạn."""
        for b in self.fn.blocks:
            if b.term is not None and lbl in b.term.labels:
                return True
        return False

    # ---- scope biến ----
    def push_scope(self):
        self.scopes.append({})
        self.defers.append([])

    def pop_scope(self):
        self.scopes.pop()
        return self.defers.pop()

    def declare(self, name, addr, ty):
        self.scopes[-1][name] = (addr, ty)

    def lookup(self, name):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        return None

    # ------------------------------------------------------------------
    # điểm vào
    # ------------------------------------------------------------------
    def generate(self) -> I.Module:
        # bố cục kiểu trước (backend cần offset; ABI test cần khoá lại)
        for it in self.prog.items:
            if isinstance(it, A.StructDef):
                fields = [(f.name, self.resolve(f.type)) for f in it.fields]
                self.structs[it.name] = fields
                packed = any(getattr(a, "name", "") == "packed"
                             for a in getattr(it, "attrs", []) or [])
                align = 0
                for a in getattr(it, "attrs", []) or []:
                    if getattr(a, "name", "") == "align":
                        try:
                            align = int(getattr(a, "arg", 0) or 0)
                        except (TypeError, ValueError):
                            align = 0
                self.mod.structs.append(
                    I.StructLayout(it.name, fields, packed=packed, align=align))
            elif isinstance(it, A.EnumDef):
                vals, nxt = [], 0
                for vname, vexpr in it.variants:
                    if vexpr is not None:
                        cv = getattr(vexpr, "const_value", None)
                        if cv is None and isinstance(vexpr, A.IntLit):
                            cv = int(vexpr.value, 0)
                        if cv is not None:
                            nxt = int(cv)
                    vals.append((vname, nxt))
                    self.enum_of_variant[vname] = it.name
                    nxt += 1
                self.enums[it.name] = dict(vals)
                self.mod.enums.append(I.EnumLayout(it.name, vals))

        for it in self.prog.items:
            if isinstance(it, A.GlobalVar):
                self.gen_global(it)

        for it in self.prog.items:
            if isinstance(it, A.Function):
                self.gen_func(it)
            elif isinstance(it, A.Impl):
                for m in it.methods:
                    self.gen_func(m, recv=it.struct)
        return self.mod

    def resolve(self, ty):
        """A.Type → GType. Checker đã phân giải; ở đây dùng lại chú thích nếu có."""
        if ty is None:
            return T.VOID
        if isinstance(ty, T.GType):
            return ty
        r = getattr(ty, "resolved", None)
        if isinstance(r, T.GType):
            return r
        return self._resolve_syntax(ty)

    def _resolve_syntax(self, ty):
        """Phân giải tối giản từ cú pháp (dự phòng khi thiếu chú thích)."""
        base = getattr(ty, "name", "unknown")
        prim = {
            "void": T.VOID, "bool": T.BOOL, "char": T.CHAR, "str": T.STR,
            "int": T.I32, "i8": T.I8, "i16": T.I16, "i32": T.I32, "i64": T.I64,
            "u8": T.U8, "u16": T.U16, "u32": T.U32, "u64": T.U64,
            "f32": T.F32, "f64": T.F64,
        }
        out = prim.get(base)
        if out is None:
            if base in self.structs:
                out = T.GType("struct", name=base)
            elif base in self.enums:
                out = T.GType("enum", name=base)
            else:
                out = T.UNKNOWN
        dims = getattr(ty, "dims", None) or []
        for d in reversed(dims):
            n = d
            if hasattr(d, "value"):
                try:
                    n = int(d.value, 0)
                except (TypeError, ValueError):
                    n = "dyn"
            out = T.GType("array", elem=out, n=n)
        for _ in range(getattr(ty, "ptr", 0) or 0):
            out = T.GType("ptr", elem=out)
        return out

    # ------------------------------------------------------------------
    # global
    # ------------------------------------------------------------------
    def gen_global(self, g: A.GlobalVar):
        ty = self.resolve(g.type) if g.type is not None else \
            (self.gtype(g.value) if g.value is not None else T.I32)
        init = None
        if g.value is not None:
            init = self._const_value(g.value, ty)
        self.mod.globals.append(I.Global(
            g.name, ty, init=init, is_const=g.is_const,
            is_extern=getattr(g, "is_extern", False), mutable=g.mutable))

    def _const_value(self, e, ty=None):
        """Giá trị khởi tạo hằng (hoặc None nếu phải tính lúc chạy)."""
        if isinstance(e, A.IntLit):
            try:
                return I.const_int(int(e.value, 0), ty)
            except ValueError:
                return None
        if isinstance(e, A.FloatLit):
            return I.const_float(e.value, ty)
        if isinstance(e, A.BoolLit):
            return I.const_bool(e.value)
        if isinstance(e, A.StrLit):
            return I.const_str(e.value)
        if isinstance(e, A.CharLit):
            return I.Value("const", const=e.value, type=T.CHAR)
        if isinstance(e, A.NullLit):
            return I.const_null(ty)
        if isinstance(e, A.ArrayLit):
            out = []
            for x in e.elements:
                cv = self._const_value(x)
                if cv is None:
                    return None
                out.append(cv)
            return out
        cv = getattr(e, "const_value", None)
        if cv is not None:
            return I.const_int(cv, ty)
        return None

    # ------------------------------------------------------------------
    # hàm
    # ------------------------------------------------------------------
    def gen_func(self, fn: A.Function, recv=None):
        name = f"{recv}__{fn.name}" if recv else fn.name
        params = []
        if recv:
            params.append(I.Param("self", T.GType("ptr", elem=T.GType("struct", name=recv))))
        for p in fn.params:
            if p.name == "self" and recv:
                continue
            params.append(I.Param(p.name, self.resolve(p.type),
                                  getattr(p, "mutable", False)))
        f = I.Func(name, params, self.resolve(fn.ret),
                   is_extern=fn.is_extern or fn.body is None,
                   attrs=list(getattr(fn, "attrs", []) or []),
                   src_file=getattr(fn, "src_file", None))
        self.mod.funcs.append(f)
        if f.is_extern:
            return

        self.fn, self._n_save = f, self._n
        self.scopes, self.loops, self.defers = [], [], []
        self._dead = False
        self.start(self.block("entry"))
        self.push_scope()

        # tham số → alloca + store (dạng địa chỉ, đồng nhất với biến cục bộ)
        for p in params:
            pty = T.GType("ptr", elem=p.type)
            addr = self.emit_val("alloca", [], ty=pty, hint="p", name=p.name)
            self.emit("store", [addr, I.temp(p.name, p.type)], node=fn)
            self.declare(p.name, addr, p.type)

        for st in (fn.body or []):
            self.gen_stmt(st)

        # Rơi khỏi cuối hàm: chỉ xả defer khi block hiện tại CÒN SỐNG. Nếu thân
        # hàm đã return ở mọi nhánh thì defer đã được xả tại các điểm return đó
        # rồi — xả thêm lần nữa sẽ sinh block chết (verifier bắt được).
        if self.blk is not None and self.blk.term is None:
            self._flush_defers_upto(0)
            if f.ret is not None and f.ret.kind != "void":
                self.term(I.Term("unreach"))
            else:
                self.term(I.Term("ret"))
        self.pop_scope()
        self.fn = None

    # ------------------------------------------------------------------
    # defer
    # ------------------------------------------------------------------
    def _flush_defers_upto(self, depth):
        """Chạy defer từ scope trong cùng ra tới `depth` (không gồm depth-1...).
        LIFO trong từng scope. Dùng khi return (depth=0) / break / continue."""
        for lvl in range(len(self.defers) - 1, depth - 1, -1):
            for st in reversed(self.defers[lvl]):
                self.gen_stmt(st, in_defer=True)

    # ------------------------------------------------------------------
    # câu lệnh
    # ------------------------------------------------------------------
    def gen_stmt(self, st, in_defer=False):
        # Vùng chết: mọi nhánh trước đó đã thoát nên câu lệnh này không bao giờ
        # chạy. KHÔNG hạ mã cho nó — sinh IR cho mã không thể tới chẳng mang
        # thêm ngữ nghĩa nào, mà chỉ tạo block/nhãn mồ côi. Checker đã cảnh báo
        # "mã không thể tới được" ở tầng nguồn.
        if self._dead:
            return
        if isinstance(st, A.Let):
            self.gen_let(st)
        elif isinstance(st, A.Multi):
            for s in st.stmts:
                self.gen_stmt(s)
        elif isinstance(st, A.Return):
            # Chốt giá trị TRƯỚC khi xả defer (ngữ nghĩa Zig/Go).
            val = self.gen_expr(st.value) if st.value is not None else None
            self._flush_defers_upto(0)
            self.term(I.Term("ret", [val] if val is not None else [],
                             line=st.line, col=st.col))
        elif isinstance(st, A.ExprStmt):
            self.gen_expr(st.expr, want_value=False)
        elif isinstance(st, A.Assign):
            self.gen_assign(st)
        elif isinstance(st, A.If):
            self.gen_if(st)
        elif isinstance(st, A.While):
            self.gen_while(st)
        elif isinstance(st, A.Loop):
            self.gen_loop(st)
        elif isinstance(st, A.For):
            self.gen_for(st)
        elif isinstance(st, A.ForEach):
            self.gen_foreach(st)
        elif isinstance(st, A.Match):
            self.gen_match(st)
        elif isinstance(st, A.Block):
            self.push_scope()
            for s in st.body:
                self.gen_stmt(s)
            for d in reversed(self.pop_scope()):
                self.gen_stmt(d, in_defer=True)
        elif isinstance(st, A.Defer):
            if in_defer:
                raise IRGenError("defer lồng trong defer")
            self.defers[-1].append(st.stmt)
        elif isinstance(st, A.Break):
            if self.loops:
                cont, brk, depth = self.loops[-1]
                self._flush_defers_upto(depth)
                self.term(I.Term("jump", labels=[brk], line=st.line, col=st.col))
        elif isinstance(st, A.Continue):
            if self.loops:
                cont, brk, depth = self.loops[-1]
                self._flush_defers_upto(depth)
                self.term(I.Term("jump", labels=[cont], line=st.line, col=st.col))
        elif isinstance(st, A.Asm):
            self.emit("asm", [], node=st, template=st.code,
                      outputs=len(st.outputs), inputs=len(st.inputs),
                      extended=getattr(st, "extended", False))
        else:
            raise IRGenError(f"chưa hạ được câu lệnh {type(st).__name__}")

    def gen_let(self, st: A.Let):
        ty = getattr(st, "resolved_type", None) or (
            self.gtype(st.value) if st.value is not None else T.I32)
        pty = T.GType("ptr", elem=ty)
        addr = self.emit_val("alloca", [], ty=pty, node=st, hint="v", name=st.name)
        if st.value is not None:
            if ty.kind == "array":
                # Mảng có ngữ nghĩa GIÁ TRỊ: sao chép, không chia sẻ con trỏ.
                if isinstance(st.value, A.ArrayLit):
                    self._store_array_lit(addr, st.value, ty)
                else:
                    src = self.gen_expr(st.value)
                    self.emit("memcpy", [addr, src], node=st)
            else:
                self.emit("store", [addr, self.gen_expr(st.value)], node=st)
        self.declare(st.name, addr, ty)

    def _store_array_lit(self, addr, lit: A.ArrayLit, ty):
        elem = ty.elem if ty.elem is not None else T.UNKNOWN
        eptr = T.GType("ptr", elem=elem)
        elems = lit.elements
        rep = getattr(lit, "repeat", None)
        if rep is not None and len(elems) == 1:
            n = ty.n if isinstance(ty.n, int) else 0
            v = self.gen_expr(elems[0])
            for i in range(n):
                slot = self.emit_val("elemaddr", [addr, I.const_int(i)],
                                     ty=eptr, node=lit, hint="ea")
                self.emit("store", [slot, v], node=lit)
            return
        for i, x in enumerate(elems):
            slot = self.emit_val("elemaddr", [addr, I.const_int(i)],
                                 ty=eptr, node=lit, hint="ea")
            if isinstance(x, A.ArrayLit) and elem.kind == "array":
                self._store_array_lit(slot, x, elem)
            else:
                self.emit("store", [slot, self.gen_expr(x)], node=lit)

    def gen_assign(self, st: A.Assign):
        addr, ty = self.gen_addr(st.target)
        if st.op == "=":
            if ty is not None and ty.kind == "array":
                self.emit("memcpy", [addr, self.gen_expr(st.value)], node=st)
            else:
                self.emit("store", [addr, self.gen_expr(st.value)], node=st)
            return
        # gán phức hợp: đọc - tính - ghi
        cur = self.emit_val("load", [addr], ty=ty, node=st, hint="ld")
        rhs = self.gen_expr(st.value)
        op = {"+=": "add", "-=": "sub", "*=": "mul", "/=": "div", "%=": "mod",
              "&=": "and", "|=": "or", "^=": "xor",
              "<<=": "shl", ">>=": "shr"}[st.op]
        if op in ("div", "mod"):
            self.emit("check", [rhs], node=st, kind="divzero")
        res = self.emit_val(op, [cur, rhs], ty=ty, node=st, hint="ar")
        self.emit("store", [addr, res], node=st)

    # ---- điều khiển ----
    def gen_if(self, st: A.If):
        cond = self.gen_expr(st.cond)
        Lt, Le, Lend = self.label("then"), self.label("else"), self.label("endif")
        self.term(I.Term("branch", [cond], [Lt, Le if st.els else Lend],
                         line=st.line, col=st.col))
        self.start(self.block(Lt))
        self.push_scope()
        for s in st.then:
            self.gen_stmt(s)
        for d in reversed(self.pop_scope()):
            self.gen_stmt(d, in_defer=True)
        self.term(I.Term("jump", labels=[Lend]))
        if st.els:
            self.start(self.block(Le))
            self.push_scope()
            for s in st.els:
                self.gen_stmt(s)
            for d in reversed(self.pop_scope()):
                self.gen_stmt(d, in_defer=True)
            self.term(I.Term("jump", labels=[Lend]))
        self.start(self.block(Lend))

    def gen_while(self, st: A.While):
        Lc, Lb, Le = self.label("wcond"), self.label("wbody"), self.label("wend")
        self.term(I.Term("jump", labels=[Lc]))
        self.start(self.block(Lc))
        cond = self.gen_expr(st.cond)
        self.term(I.Term("branch", [cond], [Lb, Le], line=st.line, col=st.col))
        self.start(self.block(Lb))
        self.loops.append((Lc, Le, len(self.defers)))
        self.push_scope()
        for s in st.body:
            self.gen_stmt(s)
        for d in reversed(self.pop_scope()):
            self.gen_stmt(d, in_defer=True)
        self.loops.pop()
        self.term(I.Term("jump", labels=[Lc]))
        self.start(self.block(Le))

    def gen_loop(self, st: A.Loop):
        Lb, Le = self.label("lbody"), self.label("lend")
        self.term(I.Term("jump", labels=[Lb]))
        self.start(self.block(Lb))
        self.loops.append((Lb, Le, len(self.defers)))
        self.push_scope()
        for s in st.body:
            self.gen_stmt(s)
        for d in reversed(self.pop_scope()):
            self.gen_stmt(d, in_defer=True)
        self.loops.pop()
        self.term(I.Term("jump", labels=[Lb]))
        # 'loop { }' KHÔNG có break là vòng lặp vô hạn (vd 'fn hang()' của
        # kernel): block thoát không ai nhảy tới. Chỉ tạo nó khi thật sự có
        # break — nếu không sẽ thành block không thể tới.
        if self._targets_label(Le):
            self.start(self.block(Le))
        else:
            self.blk = None
            self._dead = True

    def gen_for(self, st: A.For):
        """for i in a..b [step N] — hạ thành khởi tạo + while."""
        ity = self.gtype(st.start)
        if ity.kind not in ("int", "char"):
            ity = T.I32
        pty = T.GType("ptr", elem=ity)
        self.push_scope()
        iv = self.emit_val("alloca", [], ty=pty, node=st, hint="i", name=st.var)
        self.emit("store", [iv, self.gen_expr(st.start)], node=st)
        self.declare(st.var, iv, ity)
        endv = self.emit_val("alloca", [], ty=pty, node=st, hint="e", name="__end")
        self.emit("store", [endv, self.gen_expr(st.end)], node=st)

        Lc, Lb, Ls, Le = (self.label("fcond"), self.label("fbody"),
                          self.label("fstep"), self.label("fend"))
        self.term(I.Term("jump", labels=[Lc]))
        self.start(self.block(Lc))
        cur = self.emit_val("load", [iv], ty=ity, node=st, hint="ld")
        lim = self.emit_val("load", [endv], ty=ity, node=st, hint="ld")
        cmp_op = "le" if st.inclusive else "lt"
        cond = self.emit_val(cmp_op, [cur, lim], ty=T.BOOL, node=st, hint="c")
        self.term(I.Term("branch", [cond], [Lb, Le], line=st.line, col=st.col))

        self.start(self.block(Lb))
        self.loops.append((Ls, Le, len(self.defers)))
        self.push_scope()
        for s in st.body:
            self.gen_stmt(s)
        for d in reversed(self.pop_scope()):
            self.gen_stmt(d, in_defer=True)
        self.loops.pop()
        self.term(I.Term("jump", labels=[Ls]))

        self.start(self.block(Ls))
        c2 = self.emit_val("load", [iv], ty=ity, node=st, hint="ld")
        step = self.gen_expr(st.step) if st.step is not None else I.const_int(1, ity)
        nxt = self.emit_val("add", [c2, step], ty=ity, node=st, hint="nx")
        self.emit("store", [iv, nxt], node=st)
        self.term(I.Term("jump", labels=[Lc]))
        self.start(self.block(Le))
        self.pop_scope()

    def gen_foreach(self, st: A.ForEach):
        """for [mut] x in arr — duyệt theo CHỈ SỐ; 'mut' ghi thẳng qua elemaddr."""
        ity = T.I32
        pity = T.GType("ptr", elem=ity)
        aty = self.gtype(st.iterable)
        elem = aty.elem if aty.kind == "array" and aty.elem is not None else T.UNKNOWN
        n = aty.n if aty.kind == "array" and isinstance(aty.n, int) else 0

        self.push_scope()
        base, _ = self.gen_addr_or_value(st.iterable)
        idx = self.emit_val("alloca", [], ty=pity, node=st, hint="i", name="__idx")
        self.emit("store", [idx, I.const_int(0)], node=st)

        Lc, Lb, Ls, Le = (self.label("ecnd"), self.label("ebdy"),
                          self.label("estp"), self.label("eend"))
        self.term(I.Term("jump", labels=[Lc]))
        self.start(self.block(Lc))
        cur = self.emit_val("load", [idx], ty=ity, node=st, hint="ld")
        cond = self.emit_val("lt", [cur, I.const_int(n)], ty=T.BOOL, node=st, hint="c")
        self.term(I.Term("branch", [cond], [Lb, Le], line=st.line, col=st.col))

        self.start(self.block(Lb))
        eptr = T.GType("ptr", elem=elem)
        slot = self.emit_val("elemaddr", [base, cur], ty=eptr, node=st, hint="ea")
        if st.mutable:
            # ghi xuyên vào mảng: biến lặp CHÍNH LÀ ô nhớ phần tử
            self.declare(st.var, slot, elem)
        else:
            # bản sao chỉ đọc
            cp = self.emit_val("alloca", [], ty=eptr, node=st, hint="x", name=st.var)
            if elem.kind == "array":
                self.emit("memcpy", [cp, slot], node=st)
            else:
                v = self.emit_val("load", [slot], ty=elem, node=st, hint="ld")
                self.emit("store", [cp, v], node=st)
            self.declare(st.var, cp, elem)
        self.loops.append((Ls, Le, len(self.defers)))
        self.push_scope()
        for s in st.body:
            self.gen_stmt(s)
        for d in reversed(self.pop_scope()):
            self.gen_stmt(d, in_defer=True)
        self.loops.pop()
        self.term(I.Term("jump", labels=[Ls]))

        self.start(self.block(Ls))
        c2 = self.emit_val("load", [idx], ty=ity, node=st, hint="ld")
        nxt = self.emit_val("add", [c2, I.const_int(1)], ty=ity, node=st, hint="nx")
        self.emit("store", [idx, nxt], node=st)
        self.term(I.Term("jump", labels=[Lc]))
        self.start(self.block(Le))
        self.pop_scope()

    def gen_match(self, st: A.Match):
        """match — 'switch' khi mọi pattern là hằng nguyên, ngược lại chuỗi branch."""
        subj = self.gen_expr(st.subject)
        sty = self.gtype(st.subject)
        Lend = self.label("mend")

        arm_labels, cases, default = [], [], None
        simple = True
        for arm in st.arms:
            pats = arm[0]
            lbl = self.label("arm")
            arm_labels.append(lbl)
            if pats is None:
                default = lbl
                continue
            if arm[1] is not None:          # có guard -> không dùng switch được
                simple = False
            for p in pats:
                cv = self._const_pat(p)
                if cv is None:
                    simple = False
                else:
                    cases.append((cv, lbl))

        if simple and cases and sty.kind in ("int", "char", "enum", "bool"):
            labels = [l for _, l in cases]
            labels.append(default or Lend)
            self.term(I.Term("switch", [subj], labels,
                             extra={"cases": [c for c, _ in cases]},
                             line=st.line, col=st.col))
        else:
            # chuỗi so sánh tuần tự
            for i, arm in enumerate(st.arms):
                pats, guard, _ = arm
                if pats is None:
                    self.term(I.Term("jump", labels=[arm_labels[i]]))
                    break
                Lnext = self.label("mnext")
                acc = None
                for p in pats:
                    c = self._pat_cond(p, subj, sty)
                    acc = c if acc is None else self.emit_val(
                        "lor", [acc, c], ty=T.BOOL, node=st, hint="or")
                if guard is not None:
                    g = self.gen_expr(guard)
                    acc = self.emit_val("land", [acc, g], ty=T.BOOL, node=st,
                                        hint="gd") if acc is not None else g
                self.term(I.Term("branch", [acc], [arm_labels[i], Lnext],
                                 line=st.line, col=st.col))
                self.start(self.block(Lnext))
            else:
                self.term(I.Term("jump", labels=[default or Lend]))
            if default is not None and self.blk.term is None:
                self.term(I.Term("jump", labels=[default]))

        used_end = False
        for i, arm in enumerate(st.arms):
            self.start(self.block(arm_labels[i]))
            self.push_scope()
            for s in arm[2]:
                self.gen_stmt(s)
            for d in reversed(self.pop_scope()):
                self.gen_stmt(d, in_defer=True)
            # Nhánh nào cũng return/break thì KHÔNG nhảy tới Lend — nếu không
            # Lend trở thành block không thể tới (verifier bắt).
            if self.blk is not None and self.blk.term is None:
                self.term(I.Term("jump", labels=[Lend]))
                used_end = True
        # Nhánh mặc định khuyết: switch/branch cuối vẫn trỏ tới Lend.
        if default is None:
            used_end = True
        if used_end:
            self.start(self.block(Lend))
        else:
            # Mọi nhánh đều thoát (return/break) và có nhánh mặc định: KHÔNG tạo
            # block Lend — tạo ra sẽ thành block không thể tới. Mã sau match
            # (nếu có) nằm trong vùng chết.
            self.blk = None
            self._dead = True

    def _const_pat(self, p):
        cv = getattr(p, "const_value", None)
        if cv is not None:
            return cv
        if isinstance(p, A.IntLit):
            try:
                return int(p.value, 0)
            except ValueError:
                return None
        if isinstance(p, A.CharLit):
            return ord(p.value) if len(p.value) == 1 else None
        if isinstance(p, A.BoolLit):
            return int(p.value)
        if isinstance(p, A.Ident) and p.name in self.enum_of_variant:
            return self.enums[self.enum_of_variant[p.name]][p.name]
        if isinstance(p, A.FieldAccess) and getattr(p, "is_enum_variant", False):
            v = getattr(p, "enum_variant", None)
            if v is not None and v in self.enum_of_variant:
                return self.enums[self.enum_of_variant[v]][v]
        return None

    def _pat_cond(self, p, subj, sty):
        if isinstance(p, A.RangePat):
            lo = self.gen_expr(p.lo)
            hi = self.gen_expr(p.hi)
            c1 = self.emit_val("ge", [subj, lo], ty=T.BOOL, node=p, hint="lo")
            c2 = self.emit_val("le" if p.inclusive else "lt", [subj, hi],
                               ty=T.BOOL, node=p, hint="hi")
            return self.emit_val("land", [c1, c2], ty=T.BOOL, node=p, hint="rg")
        if sty.kind == "str":
            v = self.gen_expr(p)
            return self.emit_val("call", [subj, v], ty=T.BOOL, node=p,
                                 hint="se", callee="g_str_eq")
        return self.emit_val("eq", [subj, self.gen_expr(p)], ty=T.BOOL,
                             node=p, hint="pe")

    # ------------------------------------------------------------------
    # địa chỉ (lvalue)
    # ------------------------------------------------------------------
    def gen_addr(self, e):
        """Trả về (Value địa chỉ, GType của ô nhớ)."""
        if isinstance(e, A.Ident):
            found = self.lookup(e.name)
            if found is not None:
                return found
            ty = self.gtype(e)
            return I.Value("global", name=e.name,
                           type=T.GType("ptr", elem=ty)), ty
        if isinstance(e, A.FieldAccess):
            base_ty = self.gtype(e.base)
            if base_ty.kind == "ptr":
                base = self.gen_expr(e.base)
                sname = base_ty.elem.name if base_ty.elem is not None else ""
            else:
                base, bt = self.gen_addr(e.base)
                sname = bt.name if bt is not None else ""
            fty = self.gtype(e)
            addr = self.emit_val("fieldaddr",
                                 [base, I.Value("const", const=e.field, type=T.STR)],
                                 ty=T.GType("ptr", elem=fty), node=e, hint="fa",
                                 struct=sname, field=e.field)
            return addr, fty
        if isinstance(e, A.Index):
            bt = self.gtype(e.base)
            if bt.kind == "ptr" or (bt.kind == "array" and bt.n == "dyn"):
                base = self.gen_expr(e.base)
            else:
                base, _ = self.gen_addr(e.base)
            idx = self.gen_expr(e.index)
            ety = self.gtype(e)
            if bt.kind == "array" and isinstance(bt.n, int):
                self.emit("check", [idx, I.const_int(bt.n)], node=e, kind="bounds")
            addr = self.emit_val("elemaddr", [base, idx],
                                 ty=T.GType("ptr", elem=ety), node=e, hint="ea")
            return addr, ety
        if isinstance(e, A.Unary) and e.op == "*":
            p = self.gen_expr(e.operand)
            pt = self.gtype(e.operand)
            ety = pt.elem if pt.elem is not None else self.gtype(e)
            return p, ety
        # rvalue: vật hoá vào ô tạm rồi lấy địa chỉ
        ty = self.gtype(e)
        addr = self.emit_val("alloca", [], ty=T.GType("ptr", elem=ty),
                             node=e, hint="tmp")
        self.emit("store", [addr, self.gen_expr(e)], node=e)
        return addr, ty

    def gen_addr_or_value(self, e):
        """Mảng: trả địa chỉ. Con trỏ: trả chính giá trị con trỏ."""
        ty = self.gtype(e)
        if ty.kind == "array" and isinstance(ty.n, int):
            return self.gen_addr(e)
        return self.gen_expr(e), ty

    # ------------------------------------------------------------------
    # biểu thức
    # ------------------------------------------------------------------
    def gen_expr(self, e, want_value=True):
        ty = self.gtype(e)

        if isinstance(e, A.IntLit):
            try:
                return I.const_int(int(e.value, 0), ty)
            except ValueError:
                return I.const_int(0, ty)
        if isinstance(e, A.FloatLit):
            return I.const_float(e.value, ty)
        if isinstance(e, A.BoolLit):
            return I.const_bool(e.value)
        if isinstance(e, A.StrLit):
            return I.const_str(e.value)
        if isinstance(e, A.CharLit):
            return I.Value("const", const=e.value, type=T.CHAR)
        if isinstance(e, A.NullLit):
            return I.const_null(ty)

        if isinstance(e, A.Ident):
            if getattr(e, "is_enum_variant", False) or e.name in self.enum_of_variant:
                en = self.enum_of_variant.get(e.name)
                if en is not None:
                    return I.Value("const", const=self.enums[en][e.name],
                                   type=T.GType("enum", name=en))
            found = self.lookup(e.name)
            if found is None:
                if ty.kind == "func" or getattr(e, "is_fn", False):
                    return I.Value("func", name=e.name, type=ty)
                g = I.Value("global", name=e.name, type=T.GType("ptr", elem=ty))
                return self.emit_val("load", [g], ty=ty, node=e, hint="gl")
            addr, vty = found
            if vty.kind == "array":
                return addr            # mảng dùng ở dạng địa chỉ
            return self.emit_val("load", [addr], ty=vty, node=e, hint="ld")

        if isinstance(e, A.Binary):
            return self.gen_binary(e)
        if isinstance(e, A.Unary):
            return self.gen_unary(e)
        if isinstance(e, A.Ternary):
            return self.gen_ternary(e)
        if isinstance(e, A.Cast):
            v = self.gen_expr(e.expr)
            return self.emit_val("cast", [v], ty=ty, node=e, hint="cs",
                                 to=str(ty), frm=str(self.gtype(e.expr)))
        if isinstance(e, A.Index):
            addr, ety = self.gen_addr(e)
            if ety.kind == "array":
                return addr
            return self.emit_val("load", [addr], ty=ety, node=e, hint="ix")
        if isinstance(e, A.FieldAccess):
            if getattr(e, "is_enum_variant", False):
                v = getattr(e, "enum_variant", e.field)
                en = self.enum_of_variant.get(v)
                if en is not None:
                    return I.Value("const", const=self.enums[en][v],
                                   type=T.GType("enum", name=en))
            addr, fty = self.gen_addr(e)
            if fty.kind == "array":
                return addr
            return self.emit_val("load", [addr], ty=fty, node=e, hint="fl")
        if isinstance(e, A.Call) or isinstance(e, A.MethodCall):
            return self.gen_call(e, want_value)
        if isinstance(e, A.StructLit):
            return self.gen_struct_lit(e, ty)
        if isinstance(e, A.ArrayLit):
            addr = self.emit_val("alloca", [], ty=T.GType("ptr", elem=ty),
                                 node=e, hint="al")
            self._store_array_lit(addr, e, ty)
            return addr
        if isinstance(e, A.SizeOf):
            return self.emit_val("intrinsic", [], ty=T.U64, node=e, hint="sz",
                                 name="alignof" if getattr(e, "align", False)
                                 else "sizeof", arg=str(self.resolve(e.type)))
        if isinstance(e, A.SizeOfExpr):
            return self.emit_val("intrinsic", [], ty=T.U64, node=e, hint="sz",
                                 name="sizeof", arg=str(self.gtype(e.expr)))
        if isinstance(e, A.Slice):
            base = self.gen_expr(e.base)
            lo = self.gen_expr(e.lo) if e.lo is not None else I.const_int(0)
            hi = (self.gen_expr(e.hi) if e.hi is not None
                  else self.emit_val("call", [base], ty=T.I64, node=e,
                                     hint="sl", callee="g_str_len_i"))
            return self.emit_val("call", [base, lo, hi], ty=T.STR, node=e,
                                 hint="sc", callee="g_str_slice",
                                 inclusive=e.inclusive)
        if isinstance(e, A.MatchExpr):
            return self.gen_match_expr(e, ty)
        if isinstance(e, A.IfExpr):
            return self.gen_ternary(e)
        raise IRGenError(f"chưa hạ được biểu thức {type(e).__name__}")

    def gen_binary(self, e):
        ty = self.gtype(e)
        op_map = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod",
                  "&": "and", "|": "or", "^": "xor", "<<": "shl", ">>": "shr",
                  "==": "eq", "!=": "ne", "<": "lt", "<=": "le",
                  ">": "gt", ">=": "ge"}
        if e.op in ("&&", "||"):
            # đoản mạch: cần rẽ nhánh thật
            res = self.emit_val("alloca", [], ty=T.GType("ptr", elem=T.BOOL),
                                node=e, hint="sc")
            lhs = self.gen_expr(e.left)
            self.emit("store", [res, lhs], node=e)
            Lrhs, Lend = self.label("sc_rhs"), self.label("sc_end")
            if e.op == "&&":
                self.term(I.Term("branch", [lhs], [Lrhs, Lend]))
            else:
                self.term(I.Term("branch", [lhs], [Lend, Lrhs]))
            self.start(self.block(Lrhs))
            self.emit("store", [res, self.gen_expr(e.right)], node=e)
            self.term(I.Term("jump", labels=[Lend]))
            self.start(self.block(Lend))
            return self.emit_val("load", [res], ty=T.BOOL, node=e, hint="sv")

        l = self.gen_expr(e.left)
        r = self.gen_expr(e.right)
        lt, rt = self.gtype(e.left), self.gtype(e.right)
        if e.op in ("==", "!=") and lt.kind == "str" and rt.kind == "str":
            c = self.emit_val("call", [l, r], ty=T.BOOL, node=e, hint="se",
                              callee="g_str_eq")
            if e.op == "!=":
                return self.emit_val("lnot", [c], ty=T.BOOL, node=e, hint="ne")
            return c
        if e.op in ("/", "%") and lt.is_integer() and rt.is_integer():
            self.emit("check", [r], node=e, kind="divzero")
        return self.emit_val(op_map[e.op], [l, r], ty=ty, node=e, hint="b")

    def gen_unary(self, e):
        ty = self.gtype(e)
        if e.op == "&":
            addr, _ = self.gen_addr(e.operand)
            return addr
        if e.op == "*":
            p = self.gen_expr(e.operand)
            self.emit("check", [p], node=e, kind="null")
            return self.emit_val("load", [p], ty=ty, node=e, hint="dr")
        v = self.gen_expr(e.operand)
        return self.emit_val({"-": "neg", "!": "lnot", "~": "not"}[e.op],
                             [v], ty=ty, node=e, hint="u")

    def gen_ternary(self, e):
        ty = self.gtype(e)
        res = self.emit_val("alloca", [], ty=T.GType("ptr", elem=ty),
                            node=e, hint="tv")
        cond = self.gen_expr(e.cond)
        Lt, Lf, Le = self.label("tt"), self.label("tf"), self.label("tend")
        self.term(I.Term("branch", [cond], [Lt, Lf], line=e.line, col=e.col))
        self.start(self.block(Lt))
        self.emit("store", [res, self.gen_expr(e.then)], node=e)
        self.term(I.Term("jump", labels=[Le]))
        self.start(self.block(Lf))
        self.emit("store", [res, self.gen_expr(e.els)], node=e)
        self.term(I.Term("jump", labels=[Le]))
        self.start(self.block(Le))
        return self.emit_val("load", [res], ty=ty, node=e, hint="tr")

    def gen_match_expr(self, e, ty):
        res = self.emit_val("alloca", [], ty=T.GType("ptr", elem=ty),
                            node=e, hint="mv")
        subj = self.gen_expr(e.subject)
        sty = self.gtype(e.subject)
        Lend = self.label("mxend")
        for pats, guard, val in e.arms:
            if pats is None:
                self.emit("store", [res, self.gen_expr(val)], node=e)
                self.term(I.Term("jump", labels=[Lend]))
                break
            Lhit, Lnext = self.label("mxhit"), self.label("mxnext")
            acc = None
            for p in pats:
                c = self._pat_cond(p, subj, sty)
                acc = c if acc is None else self.emit_val(
                    "lor", [acc, c], ty=T.BOOL, node=e, hint="or")
            if guard is not None:
                g = self.gen_expr(guard)
                acc = self.emit_val("land", [acc, g], ty=T.BOOL, node=e, hint="gd")
            self.term(I.Term("branch", [acc], [Lhit, Lnext]))
            self.start(self.block(Lhit))
            self.emit("store", [res, self.gen_expr(val)], node=e)
            self.term(I.Term("jump", labels=[Lend]))
            self.start(self.block(Lnext))
        self.term(I.Term("jump", labels=[Lend]))
        self.start(self.block(Lend))
        return self.emit_val("load", [res], ty=ty, node=e, hint="mr")

    def gen_struct_lit(self, e, ty):
        addr = self.emit_val("alloca", [], ty=T.GType("ptr", elem=ty),
                             node=e, hint="sl")
        for fname, fval in e.fields:
            fty = self.gtype(fval)
            slot = self.emit_val("fieldaddr",
                                 [addr, I.Value("const", const=fname, type=T.STR)],
                                 ty=T.GType("ptr", elem=fty), node=e, hint="fa",
                                 struct=ty.name, field=fname)
            if fty.kind == "array":
                if isinstance(fval, A.ArrayLit):
                    self._store_array_lit(slot, fval, fty)
                else:
                    self.emit("memcpy", [slot, self.gen_expr(fval)], node=e)
            else:
                self.emit("store", [slot, self.gen_expr(fval)], node=e)
        return self.emit_val("load", [addr], ty=ty, node=e, hint="sv")

    # ---- lời gọi ----
    # Built-in in ấn/kiểm thử: giữ ở dạng intrinsic (backend tự bung).
    _PRINT_BUILTINS = {
        "print", "println", "eprint", "eprintln", "printf", "format", "dbg",
        "assert", "assert_eq", "assert_ne", "check_eq", "check_ne",
        "assert_lt", "assert_le", "assert_gt", "assert_ge",
        "check_lt", "check_le", "check_gt", "check_ge", "test_summary",
        "panic", "unreachable", "todo", "typeof", "swap", "static_assert",
    }

    def gen_call(self, e, want_value=True):
        ty = self.gtype(e)

        # method của str -> hàm runtime
        if getattr(e, "is_str_method", False):
            args = [self.gen_expr(e.recv)] + [self.gen_expr(a) for a in e.args]
            return self.emit_val("call", args, ty=ty, node=e, hint="sm",
                                 callee=e.str_c_fn)

        # method của struct/enum -> hàm đã mangle, self là con trỏ
        if getattr(e, "is_method", False):
            if getattr(e, "recv_is_ptr", False):
                recv = self.gen_expr(e.recv)
            else:
                recv, _ = self.gen_addr(e.recv)
            args = [recv] + [self.gen_expr(a) for a in e.args]
            return self.emit_val("call", args, ty=ty, node=e, hint="mc",
                                 callee=f"{e.struct}__{e.method}")

        if getattr(e, "is_static_method", False):
            args = [self.gen_expr(a) for a in e.args]
            return self.emit_val("call", args, ty=ty, node=e, hint="sm",
                                 callee=f"{e.struct}__{e.method}")

        fname = e.func.name if isinstance(getattr(e, "func", None), A.Ident) else None

        if fname in self._PRINT_BUILTINS:
            args = []
            for a in e.args:
                try:
                    args.append(self.gen_expr(a))
                except IRGenError:
                    args.append(I.undef(self.gtype(a)))
            return self.emit_val("intrinsic", args, ty=ty, node=e, hint="bi",
                                 name=fname, argc=len(args))

        if fname in ("g_alloc", "g_realloc", "g_free", "memcpy", "memset",
                     "memmove", "memcmp", "vol_read", "vol_write",
                     "len", "min", "max", "abs", "clamp"):
            args = []
            for a in e.args:
                if isinstance(a, A.Ident) and a.name in getattr(self, "_typenames", ()):
                    continue
                try:
                    args.append(self.gen_expr(a))
                except IRGenError:
                    args.append(I.undef(self.gtype(a)))
            return self.emit_val("intrinsic", args, ty=ty, node=e, hint="mi",
                                 name=fname, argc=len(args))

        if fname is not None and fname not in ("",):
            found = self.lookup(fname)
            if found is None:
                args = [self.gen_expr(a) for a in e.args]
                return self.emit_val("call", args, ty=ty, node=e, hint="c",
                                     callee=fname)

        # gọi qua con trỏ hàm
        fp = self.gen_expr(e.func)
        args = [fp] + [self.gen_expr(a) for a in e.args]
        return self.emit_val("callptr", args, ty=ty, node=e, hint="cp")


def generate(prog: A.Program, module_name="main") -> I.Module:
    return IRGen(prog, module_name).generate()
