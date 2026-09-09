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


def _spec_map():
    """Bảng '{key} -> (specifier, kiểu ép)' của backend C."""
    from .codegen import Codegen
    return Codegen.SPEC_MAP


class _Cast:
    """Đánh dấu: ép đối số sang kiểu C này trước khi truyền cho printf."""
    __slots__ = ("node", "ctype")

    def __init__(self, node, ctype):
        self.node = node
        self.ctype = ctype


def _apply_flags(spec, flags):
    """Áp cờ width/precision/căn lề/dấu vào một printf specifier.

    Dùng lại NGUYÊN VẸN bộ của backend C (Codegen._apply_fmt_flags) — logic này
    đã được 225 ca test phủ; viết lại ở đây chắc chắn sẽ trôi lệch."""
    from .codegen import Codegen
    return Codegen._apply_fmt_flags(spec, flags)


class _EnumName:
    """Đánh dấu: in TÊN biến thể của giá trị enum này."""
    __slots__ = ("node", "enum")

    def __init__(self, node, enum):
        self.node = node
        self.enum = enum


class _BinStr:
    """Đánh dấu: in giá trị này ở dạng NHỊ PHÂN (g_bin_str)."""
    __slots__ = ("node", "gt", "flags")

    def __init__(self, node, gt, flags):
        self.node = node
        self.gt = gt
        self.flags = flags


class _Center:
    """Đánh dấu: kết xuất rồi CĂN GIỮA trong bề rộng cho trước (g_center)."""
    __slots__ = ("node", "gt", "flags", "kbase")

    def __init__(self, node, gt, flags, kbase):
        self.node = node
        self.gt = gt
        self.flags = flags
        self.kbase = kbase


class _SlicePrint:
    """Đánh dấu: in slice qua hàm in riêng cho kiểu phần tử."""
    __slots__ = ("node", "gt")

    def __init__(self, node, gt):
        self.node = node
        self.gt = gt


class _BoolStr:
    """Đánh dấu: in đối số bool này dưới dạng chuỗi "true"/"false"."""
    __slots__ = ("node",)

    def __init__(self, node):
        self.node = node


class IRGen:
    def __init__(self, prog: A.Program, module_name="main", enum_values=None,
                 target=None):
        self.prog = prog
        #: {tên enum: {biến thể: giá trị}} do checker gấp — nguồn chân lý.
        self._enum_values = enum_values or {}
        self._target = target
        self._layout = None
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
        # Kết quả 'void' KHÔNG được cấp temp — C không cho khai báo biến void.
        if ty is not None and ty.kind == "void":
            self.emit(op, args, ty=None, dst=None, node=node, **extra)
            return I.undef(T.VOID)
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
                        av = (getattr(a, "args", None) or [None])[0]
                        if av is not None and hasattr(av, "value"):
                            try:
                                align = int(av.value, 0)
                            except (TypeError, ValueError):
                                align = 0
                self.mod.structs.append(
                    I.StructLayout(it.name, fields, packed=packed, align=align))
            elif isinstance(it, A.EnumDef):
                # Giá trị biến thể do CHECKER gấp (nó xử lý được '-1', '1 << 2',
                # tham chiếu biến thể trước đó...). Tính lại ở đây từng làm mất
                # giá trị âm tường minh: 'Neg = -1' thành 0.
                resolved = getattr(self, "_enum_values", {}).get(it.name)
                vals, nxt = [], 0
                for vname, vexpr in it.variants:
                    if resolved is not None and vname in resolved:
                        nxt = int(resolved[vname])
                    elif vexpr is not None:
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

        self._deferred_globals = []
        # Sắp xếp topo theo phụ thuộc "nhúng THEO GIÁ TRỊ": struct chứa struct
        # khác phải đứng SAU nó. Trường con trỏ không tạo ràng buộc (khai báo
        # tiến là đủ). Làm ở đây — không phải trong backend — để mọi backend
        # nhận danh sách đã đúng thứ tự.
        self.mod.structs = self._topo_sort_structs(self.mod.structs)

        for it in self.prog.items:
            if isinstance(it, A.GlobalVar):
                self.gen_global(it)

        for it in self.prog.items:
            if isinstance(it, A.Function):
                self.gen_func(it)
            elif isinstance(it, A.Impl):
                for m in it.methods:
                    self.gen_func(m, recv=it.struct)
        self._emit_global_ctor()
        return self.mod

    def _emit_global_ctor(self):
        """Hàm '_g_init_globals' gán các global có initializer động, theo đúng
        thứ tự khai báo (global sau tham chiếu được global trước)."""
        if not self._deferred_globals:
            return
        f = I.Func("_g_init_globals", [], T.VOID)
        self.mod.funcs.append(f)
        self.fn = f
        self.scopes, self.loops, self.defers = [], [], []
        self._dead = False
        self.start(self.block("entry"))
        self.push_scope()
        for name, ty, value in self._deferred_globals:
            addr = I.Value("global", name=name, type=T.GType("ptr", elem=ty))
            if ty.kind == "array":
                if isinstance(value, A.ArrayLit):
                    self._store_array_lit(addr, value, ty)
                else:
                    self.emit("memcpy", [addr, self.gen_expr(value)], node=value)
            else:
                self.emit("store", [addr, self.gen_expr(value)], node=value)
        self.term(I.Term("ret"))
        self.pop_scope()
        self.fn = None

    def _layout_of(self, gt, align=False):
        """sizeof/alignof của một GType theo target, hoặc None nếu chưa tính được."""
        lay = getattr(self, "_layout", None)
        if lay is None:
            if self._target is None:
                return None
            from . import layout as _lay
            attrs = {}
            for st in self.mod.structs:
                a = {}
                if st.packed:
                    a["packed"] = True
                if st.align:
                    a["align"] = st.align
                if a:
                    attrs[st.name] = a
            lay = _lay.Layout(self._target,
                              {st.name: list(st.fields) for st in self.mod.structs},
                              attrs)
            self._layout = lay
        try:
            return lay.align_of(gt) if align else lay.size_of(gt)
        except Exception:
            return None

    @staticmethod
    def _topo_sort_structs(structs):
        """Thứ tự định nghĩa hợp lệ cho C. Chu trình (đã bị checker cấm) thì giữ
        nguyên thứ tự khai báo thay vì lặp vô hạn."""
        by_name = {st.name: st for st in structs}

        def deps(st):
            out = []
            for _, fty in st.fields:
                t = fty
                # đi qua mảng để thấy phần tử; con trỏ thì DỪNG (không ràng buộc)
                while t is not None and t.kind == "array":
                    t = t.elem
                if t is not None and t.kind == "struct" and t.name in by_name:
                    out.append(t.name)
            return out

        order, state = [], {}

        def visit(name):
            st = state.get(name)
            if st == 2:
                return
            if st == 1:
                return              # chu trình: checker đã báo lỗi
            state[name] = 1
            for d in deps(by_name[name]):
                visit(d)
            state[name] = 2
            order.append(by_name[name])

        for st in structs:
            visit(st.name)
        return order

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
        """Dự phòng khi node KHÔNG có chú thích 'resolved' của checker.

        Đường chính là `Checker.resolve` ghi `ty.resolved`; hàm này chỉ chạy cho
        node do irgen tự dựng. Nó CỐ Ý không xử lý kiểu hàm/slice — nếu cần
        những kiểu đó thì phải lấy từ chú thích, không đoán lại."""
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
        if getattr(ty, "slice_elem", None) is not None:
            return T.slice_of(self.resolve(ty.slice_elem),
                              mutable=getattr(ty, "slice_mut", False))
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
            if init is None and not getattr(g, "is_extern", False):
                # Initializer KHÔNG phải hằng biên dịch (tham chiếu global khác,
                # lời gọi hàm, g_alloc): C cấm. Hoãn sang một hàm khởi tạo chạy
                # TRƯỚC main, giữ đúng thứ tự khai báo. Trước đây giá trị bị bỏ
                # im lặng -> global mang 0.
                self._deferred_globals.append((g.name, ty, g.value))
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
        # Method TĨNH ('fn of(x, y)' trong impl) KHÔNG có 'self' — chỉ thêm
        # tham số self khi hàm thật sự khai báo nó. Trước đây mọi hàm trong impl
        # đều bị thêm, nên nơi gọi truyền thiếu một đối số.
        has_self = any(p.name == "self" for p in fn.params)
        if recv and has_self:
            elem = (T.GType("enum", name=recv) if recv in self.enums
                    else T.GType("struct", name=recv))
            params.append(I.Param("self", T.GType("ptr", elem=elem)))
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
            # asm MỞ RỘNG có toán hạng: output là ĐỊA CHỈ (ghi vào), input là
            # giá trị. Trước đây IR chỉ giữ template và vứt toán hạng, nên
            # '%0' trong template không còn gì để tham chiếu.
            vals, cons = [], []
            for c, ex in st.outputs:
                addr, _ = self.gen_addr(ex)
                vals.append(addr)
                cons.append(c)
            n_out = len(st.outputs)
            for c, ex in st.inputs:
                vals.append(self.gen_expr(ex))
                cons.append(c)
            self.emit("asm", vals, node=st, template=st.code,
                      constraints=cons, n_out=n_out,
                      clobbers=list(st.clobbers),
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
        stepv = None
        if st.step is not None:
            stepv = self.emit_val("alloca", [], ty=pty, node=st, hint="st",
                                  name="__step")
            self.emit("store", [stepv, self.gen_expr(st.step)], node=st)

        Lc, Lb, Ls, Le = (self.label("fcond"), self.label("fbody"),
                          self.label("fstep"), self.label("fend"))
        self.term(I.Term("jump", labels=[Lc]))
        self.start(self.block(Lc))
        cur = self.emit_val("load", [iv], ty=ity, node=st, hint="ld")
        lim = self.emit_val("load", [endv], ty=ity, node=st, hint="ld")
        # CHIỀU so sánh phụ thuộc DẤU CỦA BƯỚC: 'for i in 5..0 step -1' phải
        # dùng '>' chứ không phải '<' (nếu không vòng lặp không chạy lần nào).
        # Bước hằng -> quyết định lúc biên dịch; bước động -> chọn lúc chạy.
        sign = self._step_sign(st.step)
        if sign < 0:
            cmp_op = "ge" if st.inclusive else "gt"
            cond = self.emit_val(cmp_op, [cur, lim], ty=T.BOOL, node=st, hint="c")
        elif sign > 0:
            cmp_op = "le" if st.inclusive else "lt"
            cond = self.emit_val(cmp_op, [cur, lim], ty=T.BOOL, node=st, hint="c")
        else:
            up = self.emit_val("le" if st.inclusive else "lt", [cur, lim],
                               ty=T.BOOL, node=st, hint="cu")
            dn = self.emit_val("ge" if st.inclusive else "gt", [cur, lim],
                               ty=T.BOOL, node=st, hint="cd")
            sv = self.emit_val("load", [stepv], ty=ity, node=st, hint="ls")
            pos = self.emit_val("ge", [sv, I.const_int(0, ity)], ty=T.BOOL,
                                node=st, hint="sp")
            cond = self.emit_val("select", [pos, up, dn], ty=T.BOOL, node=st,
                                 hint="c")
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

        # Thân LUÔN thoát (vd kết thúc bằng 'break'/'return'): khối tăng biến
        # đếm không ai nhảy tới. Vẫn phải sinh nó vì 'continue' trỏ tới đó —
        # nhưng chỉ khi thật sự có ai nhảy tới, nếu không verifier báo block
        # không thể tới được.
        if not self._targets_label(Ls):
            self.start(self.block(Le))
            self.pop_scope()
            return
        self.start(self.block(Ls))
        c2 = self.emit_val("load", [iv], ty=ity, node=st, hint="ld")
        step = (self.emit_val("load", [stepv], ty=ity, node=st, hint="ls")
                if stepv is not None else I.const_int(1, ity))
        nxt = self.emit_val("add", [c2, step], ty=ity, node=st, hint="nx")
        self.emit("store", [iv, nxt], node=st)
        self.term(I.Term("jump", labels=[Lc]))
        self.start(self.block(Le))
        self.pop_scope()

    @staticmethod
    def _step_sign(step):
        """Dấu của bước nếu biết LÚC BIÊN DỊCH: -1 / +1, hoặc 0 nếu không rõ."""
        if step is None:
            return 1
        cv = getattr(step, "const_value", None)
        if cv is None and isinstance(step, A.IntLit):
            try:
                cv = int(step.value, 0)
            except ValueError:
                cv = None
        if cv is None and isinstance(step, A.Unary) and step.op == "-":
            inner = step.operand
            iv = getattr(inner, "const_value", None)
            if iv is None and isinstance(inner, A.IntLit):
                try:
                    iv = int(inner.value, 0)
                except ValueError:
                    iv = None
            if iv is not None:
                cv = -iv
        if cv is None:
            return 0
        return -1 if cv < 0 else 1

    def gen_foreach(self, st: A.ForEach):
        """for [mut] x in arr — duyệt theo CHỈ SỐ; 'mut' ghi thẳng qua elemaddr."""
        ity = T.I32
        pity = T.GType("ptr", elem=ity)
        aty = self.gtype(st.iterable)
        is_str = aty.kind == "str" or (aty.kind == "ptr" and aty.elem is not None
                                       and aty.elem.kind == "char")
        if is_str:
            # Duyệt CHUỖI: số lần lặp = strlen (biết lúc chạy), phần tử là char.
            elem = T.CHAR
        else:
            elem = (aty.elem if aty.kind == "array" and aty.elem is not None
                    else T.UNKNOWN)
        n = aty.n if aty.kind == "array" and isinstance(aty.n, int) else 0

        self.push_scope()
        base, _ = self.gen_addr_or_value(st.iterable)
        limv = None
        if is_str:
            limv = self.emit_val("alloca", [], ty=pity, node=st, hint="sn",
                                 name="__len")
            ln = self.emit_val("call", [base], ty=T.I64, node=st, hint="sl",
                               callee="g_str_len_i")
            self.emit("store", [limv, ln], node=st)
        idx = self.emit_val("alloca", [], ty=pity, node=st, hint="i", name="__idx")
        self.emit("store", [idx, I.const_int(0)], node=st)

        Lc, Lb, Ls, Le = (self.label("ecnd"), self.label("ebdy"),
                          self.label("estp"), self.label("eend"))
        self.term(I.Term("jump", labels=[Lc]))
        self.start(self.block(Lc))
        cur = self.emit_val("load", [idx], ty=ity, node=st, hint="ld")
        lim = (self.emit_val("load", [limv], ty=ity, node=st, hint="ll")
               if limv is not None else I.const_int(n))
        cond = self.emit_val("lt", [cur, lim], ty=T.BOOL, node=st, hint="c")
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

        if not self._targets_label(Ls):
            self.start(self.block(Le))
            self.pop_scope()
            return
        self.start(self.block(Ls))
        c2 = self.emit_val("load", [idx], ty=ity, node=st, hint="ld")
        nxt = self.emit_val("add", [c2, I.const_int(1)], ty=ity, node=st, hint="nx")
        self.emit("store", [idx, nxt], node=st)
        self.term(I.Term("jump", labels=[Lc]))
        self.start(self.block(Le))
        self.pop_scope()

    def gen_match(self, st: A.Match):
        """match — 'switch' khi mọi pattern là hằng nguyên, ngược lại chuỗi branch."""
        subj, sty = self._match_subject(st)
        Lend = self.label("mend")

        # Binding kiểu Rust ('x =>' / 'x if x > 0 =>'): checker ghi tên C của
        # biến vào st.bindings, song song với arms. Nhánh có binding luôn KHỚP
        # (điều kiện chỉ còn guard) và phải thấy biến đó trong phạm vi.
        bindings = getattr(st, "bindings", None) or [None] * len(st.arms)
        arm_labels, cases, default = [], [], None
        simple = True
        for arm, bname in zip(st.arms, bindings):
            pats = arm[0]
            lbl = self.label("arm")
            arm_labels.append(lbl)
            if bname is not None:
                simple = False
                if arm[1] is None:
                    default = lbl       # binding trần = bắt tất cả
                continue
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
                bname = bindings[i]
                if bname is None and pats is None:
                    self.term(I.Term("jump", labels=[arm_labels[i]]))
                    break
                Lnext = self.label("mnext")
                if bname is not None:
                    # Biến binding phải có trong phạm vi TRƯỚC khi tính guard.
                    self._bind_match_var(bname, subj, sty, st)
                    if guard is None:
                        self.term(I.Term("jump", labels=[arm_labels[i]]))
                        break
                    acc = self.gen_expr(guard)
                else:
                    acc = None
                    for p in pats:
                        c = self._pat_cond(p, subj, sty)
                        acc = c if acc is None else self.emit_val(
                            "lor", [acc, c], ty=T.BOOL, node=st, hint="or")
                    if guard is not None:
                        g = self.gen_expr(guard)
                        acc = self.emit_val("land", [acc, g], ty=T.BOOL,
                                            node=st, hint="gd") \
                            if acc is not None else g
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

    def _type_arg_gtype(self, a):
        """Đối số ở VỊ TRÍ KIỂU của g_alloc/g_realloc -> GType."""
        if isinstance(a, A.Ident):
            if a.name in self.structs:
                return T.GType("struct", name=a.name)
            if a.name in self.enums:
                return T.GType("enum", name=a.name)
            prim = self._resolve_syntax(A.Type(a.name))
            if prim is not None and prim.kind != "unknown":
                return prim
        if isinstance(a, A.Unary) and a.op == "*":
            inner = self._type_arg_gtype(a.operand)
            return T.GType("ptr", elem=inner) if inner is not None else None
        gt = self.gtype(a)
        return gt if gt.kind != "unknown" else None

    def _gen_arith_builtin(self, e, fname, ty):
        """abs/min/max/clamp -> so sánh + select (lệnh IR thật).

        Đối số được VẬT HOÁ vào temp trước: 'min(f(), g())' chỉ được gọi f/g một
        lần, còn macro C của runtime đánh giá lại đối số nhiều lần."""
        vals = [self.gen_expr(a) for a in e.args]
        if fname == "abs" and len(vals) == 1:
            x = vals[0]
            zero = I.const_int(0, ty)
            neg = self.emit_val("neg", [x], ty=ty, node=e, hint="ng")
            c = self.emit_val("lt", [x, zero], ty=T.BOOL, node=e, hint="ac")
            return self.emit_val("select", [c, neg, x], ty=ty, node=e, hint="ab")
        if fname in ("min", "max") and len(vals) == 2:
            a0, a1 = vals
            op = "lt" if fname == "min" else "gt"
            c = self.emit_val(op, [a0, a1], ty=T.BOOL, node=e, hint="mc")
            return self.emit_val("select", [c, a0, a1], ty=ty, node=e, hint="mm")
        if fname == "clamp" and len(vals) == 3:
            x, lo, hi = vals
            c1 = self.emit_val("lt", [x, lo], ty=T.BOOL, node=e, hint="cl")
            t1 = self.emit_val("select", [c1, lo, x], ty=ty, node=e, hint="c1")
            c2 = self.emit_val("gt", [t1, hi], ty=T.BOOL, node=e, hint="ch")
            return self.emit_val("select", [c2, hi, t1], ty=ty, node=e, hint="c2")
        return self.emit_val("intrinsic", vals, ty=ty, node=e, hint="mi",
                             name=fname, argc=len(vals))

    def _bind_match_var(self, bname, subj, sty, node):
        """Đưa biến binding của một nhánh match vào phạm vi (trỏ tới subject)."""
        addr = self.emit_val("alloca", [], ty=T.GType("ptr", elem=sty),
                             node=node, hint="mb", name=bname)
        self.emit("store", [addr, subj], node=node)
        self.declare(bname, addr, sty)

    def _match_subject(self, node):
        """(giá trị, kiểu) của biểu thức được match, TỰ DEREF khi cần.

        'match self' trong 'impl' của enum có subject kiểu '*Enum'; checker đánh
        dấu 'deref_subject'. Bỏ qua dấu đó thì so sánh diễn ra trên ĐỊA CHỈ chứ
        không phải giá trị -> chọn nhầm nhánh (in 'lam' thay vì 'lục')."""
        sty = self.gtype(node.subject)
        v = self.gen_expr(node.subject)
        if getattr(node, "deref_subject", False) or (
                sty.kind == "ptr" and sty.elem is not None
                and sty.elem.kind in ("enum", "int", "char", "bool")):
            inner = sty.elem if sty.elem is not None else T.I32
            v = self.emit_val("load", [v], ty=inner, node=node, hint="ds")
            sty = inner
        return v, sty

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
        if isinstance(p, A.FieldAccess):
            v = self._enum_variant_name(p)
            if v is not None:
                return self.enums[self.enum_of_variant[v]][v]
        return None

    def _enum_variant_name(self, e):
        """Tên biến thể của 'Enum.Variant' (checker ghi tuple (Kiểu, Tên))."""
        ev = getattr(e, "enum_variant", None)
        if isinstance(ev, tuple) and len(ev) == 2:
            ev = ev[1]
        if isinstance(ev, str) and ev in self.enum_of_variant:
            return ev
        if (getattr(e, "is_enum_variant", False)
                and getattr(e, "field", None) in self.enum_of_variant):
            return e.field
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
            # Biến thể enum ('Red') là HẰNG, không phải ô nhớ — phải vật hoá vào
            # ô tạm trước khi lấy địa chỉ. Trước đây nó rơi vào nhánh 'global' và
            # sinh 'Color__is_red(Red)', tức truyền giá trị 0 làm CON TRỎ.
            if (getattr(e, "is_enum_variant", False)
                    or e.name in self.enum_of_variant):
                ty = self.gtype(e)
                addr = self.emit_val("alloca", [], ty=T.GType("ptr", elem=ty),
                                     node=e, hint="ev")
                self.emit("store", [addr, self.gen_expr(e)], node=e)
                return addr, ty
            found = self.lookup(e.name)
            if found is not None:
                return found
            ty = self.gtype(e)
            return I.Value("global", name=e.name,
                           type=T.GType("ptr", elem=ty)), ty
        if isinstance(e, A.FieldAccess):
            if self._enum_variant_name(e) is not None:
                # 'Enum.Variant' là HẰNG, không phải ô nhớ -> vật hoá.
                ty = self.gtype(e)
                addr = self.emit_val("alloca", [], ty=T.GType("ptr", elem=ty),
                                     node=e, hint="ev")
                self.emit("store", [addr, self.gen_expr(e)], node=e)
                return addr, ty
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
            ety = self.gtype(e)
            if bt.kind == "slice":
                # Chỉ số trên SLICE: lấy GIÁ TRỊ slice (ptr+len) rồi kiểm biên
                # bằng độ dài mang theo. KHÔNG được elemaddr trên ô alloca giữ
                # slice — đó là địa chỉ của handle, không phải của dữ liệu.
                sv = self.gen_expr(e.base)
                idx = self.gen_expr(e.index)
                self.emit("check", [idx, sv], node=e, kind="slice_bounds")
                addr = self.emit_val("elemaddr", [sv, idx],
                                     ty=T.GType("ptr", elem=ety), node=e,
                                     hint="sa", on="slice")
                return addr, ety
            # 'str' cũng là con trỏ (const char*): phải LẤY GIÁ TRỊ rồi index.
            # Trước đây nó rơi vào nhánh gen_addr -> index trên ĐỊA CHỈ của biến
            # giữ chuỗi, đọc ra rác.
            if (bt.kind in ("ptr", "str")
                    or (bt.kind == "array" and bt.n == "dyn")):
                base = self.gen_expr(e.base)
            else:
                base, _ = self.gen_addr(e.base)
            idx = self.gen_expr(e.index)
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
        ts = getattr(e, "to_slice", None)
        if ts is not None:
            # Chuyển ngầm mảng tĩnh -> slice (checker đánh dấu). Hạ tường minh
            # thành 'makeslice' để backend không phải tự suy ra.
            n, mut = ts
            gt = self.gtype(e)
            sty = T.slice_of(gt.elem, mutable=mut)
            try:
                addr, _ = self.gen_addr(e)
            except IRGenError:
                addr = self._gen_expr_inner(e)
            return self.emit_val("intrinsic", [addr, I.const_int(0),
                                               I.const_int(n)],
                                 ty=sty, node=e, hint="sl", name="makeslice")
        return self._gen_expr_inner(e, want_value)

    def _gen_expr_inner(self, e, want_value=True):
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
            v = self._enum_variant_name(e)
            if v is not None:
                en = self.enum_of_variant[v]
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
            # Gấp thành HẰNG bằng engine bố cục theo target — backend không phải
            # nhờ 'sizeof' của C, và con số giống nhau ở mọi backend.
            # 'sizeof(x)' với x là BIẾN cũng được parser dựng thành A.SizeOf
            # (tên trần không phân biệt được kiểu/biến), nên phải tra biến trước.
            gt = None
            if getattr(e.type, "resolved", None) is None:
                found = self.lookup(getattr(e.type, "name", ""))
                if found is not None:
                    gt = found[1]
            if gt is None:
                gt = self.resolve(e.type)
            n = self._layout_of(gt, align=getattr(e, "align", False))
            if n is not None:
                return I.const_int(n, T.USIZE)
            return self.emit_val("intrinsic", [], ty=T.USIZE, node=e, hint="sz",
                                 name="alignof" if getattr(e, "align", False)
                                 else "sizeof", arg=str(self.resolve(e.type)))
        if isinstance(e, A.SizeOfExpr):
            n = self._layout_of(self.gtype(e.expr))
            if n is not None:
                return I.const_int(n, T.USIZE)
            return self.emit_val("intrinsic", [], ty=T.USIZE, node=e, hint="sz",
                                 name="sizeof", arg=str(self.gtype(e.expr)))
        if isinstance(e, A.TryExpr):
            # 'v try': nếu !ok thì RETURN sớm một Result lỗi; ngược lại lấy .val.
            rs = getattr(e, "ret_struct", None)
            val = self.gen_expr(e.expr)
            vt = self.gtype(e.expr)
            slot = self.emit_val("alloca", [], ty=T.GType("ptr", elem=vt),
                                 node=e, hint="tr")
            self.emit("store", [slot, val], node=e)
            okp = self.emit_val("fieldaddr",
                                [slot, I.Value("const", const="ok", type=T.STR)],
                                ty=T.GType("ptr", elem=T.BOOL), node=e,
                                hint="tk", struct=vt.name, field="ok")
            ok = self.emit_val("load", [okp], ty=T.BOOL, node=e, hint="to")
            Lok, Lbad = self.label("try_ok"), self.label("try_bad")
            self.term(I.Term("branch", [ok], [Lok, Lbad],
                             line=e.line, col=e.col))
            self.start(self.block(Lbad))
            if rs is not None:
                rty = T.GType("struct", name=rs)
                rslot = self.emit_val("alloca", [], ty=T.GType("ptr", elem=rty),
                                      node=e, hint="tf")
                # Ô mới cấp KHÔNG được coi là đã zero: backend C dùng compound
                # literal (tự zero) còn 'alloca' của LLVM cho bộ nhớ RÁC. Ghi 0
                # tường minh cho mọi trường không phải 'ok'/'err'.
                for fn_, ft_ in (self._struct_fields(rs) or []):
                    if fn_ in ("ok", "err"):
                        continue
                    zp = self.emit_val(
                        "fieldaddr",
                        [rslot, I.Value("const", const=fn_, type=T.STR)],
                        ty=T.GType("ptr", elem=ft_), node=e, hint="tz",
                        struct=rs, field=fn_)
                    self.emit("store", [zp, I.undef(ft_)], node=e)
                # Kiểu của 'err' phải là kiểu THẬT: dùng T.UNKNOWN thì backend
                # sinh 'int' và sao chép sai kích thước (segfault với 'str').
                ety = self._struct_field_type(vt.name, "err") or T.STR
                ep = self.emit_val(
                    "fieldaddr", [slot, I.Value("const", const="err", type=T.STR)],
                    ty=T.GType("ptr", elem=ety), node=e, hint="te",
                    struct=vt.name, field="err")
                ev = self.emit_val("load", [ep], ty=ety, node=e, hint="tv")
                fp = self.emit_val(
                    "fieldaddr", [rslot, I.Value("const", const="err", type=T.STR)],
                    ty=T.GType("ptr", elem=ety), node=e, hint="tw",
                    struct=rs, field="err")
                self.emit("store", [fp, ev], node=e)
                op = self.emit_val(
                    "fieldaddr", [rslot, I.Value("const", const="ok", type=T.STR)],
                    ty=T.GType("ptr", elem=T.BOOL), node=e, hint="tb",
                    struct=rs, field="ok")
                self.emit("store", [op, I.const_bool(False)], node=e)
                rv = self.emit_val("load", [rslot], ty=rty, node=e, hint="tr")
                self._flush_defers_upto(0)
                self.term(I.Term("ret", [rv], line=e.line, col=e.col))
            else:
                self.term(I.Term("unreach"))
            self.start(self.block(Lok))
            vp = self.emit_val(
                "fieldaddr", [slot, I.Value("const", const="val", type=T.STR)],
                ty=T.GType("ptr", elem=ty), node=e, hint="tp",
                struct=vt.name, field="val")
            return self.emit_val("load", [vp], ty=ty, node=e, hint="tl")
        if isinstance(e, A.Slice):
            if ty.kind == "slice":
                # slice hoá: mang theo (ptr, len) — độ dài không tách rời con trỏ
                bt = self.gtype(e.base)
                base = (self.gen_addr(e.base)[0] if bt.kind == "array"
                        else self.gen_expr(e.base))
                lo = self.gen_expr(e.lo) if e.lo is not None else I.const_int(0)
                hi = (self.gen_expr(e.hi) if e.hi is not None
                      else (I.const_int(bt.n) if bt.kind == "array"
                            and isinstance(bt.n, int)
                            else self.emit_val("intrinsic", [base], ty=T.USIZE,
                                               node=e, hint="sl", name="len")))
                if e.inclusive and e.hi is not None:
                    hi = self.emit_val("add", [hi, I.const_int(1, T.USIZE)],
                                       ty=T.USIZE, node=e, hint="hi")
                return self.emit_val("intrinsic", [base, lo, hi], ty=ty, node=e,
                                     hint="sl", name="makeslice")
            base = self.gen_expr(e.base)
            lo = self.gen_expr(e.lo) if e.lo is not None else I.const_int(0)
            hi = (self.gen_expr(e.hi) if e.hi is not None
                  else self.emit_val("call", [base], ty=T.I64, node=e,
                                     hint="sl", callee="g_str_len_i"))
            if e.inclusive and e.hi is not None:
                # 's[a..=b]' bao gồm cận trên: g_str_slice nhận nửa mở nên +1.
                # Trước đây cờ 'inclusive' được ghi vào extra rồi KHÔNG ai dùng,
                # nên 's[0..=4]' cắt thiếu một ký tự.
                hi = self.emit_val("add", [hi, I.const_int(1, T.I64)],
                                   ty=T.I64, node=e, hint="hi")
            return self.emit_val("call", [base, lo, hi], ty=T.STR, node=e,
                                 hint="sc", callee="g_str_slice")
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
        # 'self == Red': checker đánh dấu tự deref (self là con trỏ).
        if getattr(e, "deref_left", False) and lt.elem is not None:
            lt = lt.elem
            l = self.emit_val("load", [l], ty=lt, node=e, hint="dl")
        if getattr(e, "deref_right", False) and rt.elem is not None:
            rt = rt.elem
            r = self.emit_val("load", [r], ty=rt, node=e, hint="dr")
        if e.op in ("==", "!=") and lt.kind == "struct" and rt.kind == "struct":
            # C không so sánh struct bằng '=='; dùng hàm so theo từng trường.
            same = self.emit_val("call", [l, r], ty=T.BOOL, node=e, hint="sq",
                                 callee=f"_g_eq_{lt.name}")
            if e.op == "!=":
                return self.emit_val("lnot", [same], ty=T.BOOL, node=e, hint="nq")
            return same
        if e.op in ("==", "!=") and lt.kind == "slice" and rt.kind == "slice":
            pa = self.emit_val("intrinsic", [l], ty=T.GType("ptr", elem=lt.elem),
                               node=e, hint="sp", name="slice_ptr")
            pb = self.emit_val("intrinsic", [r], ty=T.GType("ptr", elem=rt.elem),
                               node=e, hint="sp", name="slice_ptr")
            la = self.emit_val("intrinsic", [l], ty=T.USIZE, node=e, hint="sn",
                               name="len")
            lb = self.emit_val("intrinsic", [r], ty=T.USIZE, node=e, hint="sn",
                               name="len")
            c1 = self.emit_val("eq", [pa, pb], ty=T.BOOL, node=e, hint="s1")
            c2 = self.emit_val("eq", [la, lb], ty=T.BOOL, node=e, hint="s2")
            same = self.emit_val("land", [c1, c2], ty=T.BOOL, node=e, hint="sa")
            if e.op == "!=":
                return self.emit_val("lnot", [same], ty=T.BOOL, node=e, hint="nq")
            return same
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
        subj, sty = self._match_subject(e)
        Lend = self.label("mxend")
        bindings = getattr(e, "bindings", None) or [None] * len(e.arms)
        for (pats, guard, val), bname in zip(e.arms, bindings):
            if bname is None and pats is None:
                self.emit("store", [res, self.gen_expr(val)], node=e)
                self.term(I.Term("jump", labels=[Lend]))
                break
            Lhit, Lnext = self.label("mxhit"), self.label("mxnext")
            if bname is not None:
                # Binding phải vào phạm vi trước cả guard lẫn giá trị nhánh.
                self.push_scope()
                self._bind_match_var(bname, subj, sty, e)
                if guard is None:
                    self.emit("store", [res, self.gen_expr(val)], node=e)
                    self.pop_scope()
                    self.term(I.Term("jump", labels=[Lend]))
                    break
                acc = self.gen_expr(guard)
                self.term(I.Term("branch", [acc], [Lhit, Lnext]))
                self.start(self.block(Lhit))
                self.emit("store", [res, self.gen_expr(val)], node=e)
                self.pop_scope()
                self.term(I.Term("jump", labels=[Lend]))
                self.start(self.block(Lnext))
                continue
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

    def _gen_print(self, e, fname, ty):
        """Hạ print/println/eprint/eprintln thành lời gọi 'printf' TƯỜNG MINH.

        Chuỗi định dạng của G ('{}', '{:>8}', ...) được giải quyết thành chuỗi
        printf của C NGAY TẠI ĐÂY, kèm danh sách đối số đã ép kiểu. Nhờ vậy
        backend chỉ việc phát 'fprintf(stream, fmt, ...)' — không backend nào
        phải cài lại bộ định dạng của G.

        Việc dựng chuỗi định dạng dùng lại chính bộ của backend C (build_format)
        để hai đường KHÔNG trôi lệch — đó là logic đã được 225 ca test phủ."""
        stream = "stderr" if fname.startswith("e") else "stdout"
        newline = fname.endswith("ln")
        if not e.args:
            fmt = "\n" if newline else ""
            return self.emit_val("call", [I.const_str(fmt)], ty=T.VOID, node=e,
                                 hint="pr", callee="g_print_raw", stream=stream)
        first = e.args[0]
        if isinstance(first, A.StrLit):
            template, value_args = first.value, e.args[1:]
        else:
            template, value_args = "{}", e.args
        fmt, argexprs = self._resolve_format(template, value_args, newline)
        vals = [I.const_str(fmt)]
        for a in argexprs:
            vals.append(self._fmt_arg_value(a, e))
        return self.emit_val("call", vals, ty=T.VOID, node=e, hint="pr",
                             callee="printf", stream=stream, is_print=True)

    #: Số phần tử tối đa in ra cho mảng (khớp Codegen._PRINT_ARRAY_MAX).
    _PRINT_ARRAY_MAX = 8

    #: Intrinsic hệ điều hành hạ thẳng sang hàm/macro của runtime C.
    _OS_INTRINSICS = {
        "popcount", "clz", "ctz", "bswap", "rotl", "rotr",
        "halt", "cli", "sti", "pause", "breakpoint", "io_wait", "rdtsc",
        "inb", "outb", "inw", "outw", "inl", "outl",
        "read_cr0", "read_cr2", "read_cr3", "read_cr4",
        "write_cr0", "write_cr3", "write_cr4",
        "invlpg", "wbinvd", "rdmsr", "wrmsr",
    }

    _CMP_BUILTINS = {
        "assert_eq", "assert_ne", "assert_lt", "assert_le", "assert_gt",
        "assert_ge", "check_eq", "check_ne", "check_lt", "check_le",
        "check_gt", "check_ge",
    }
    _CMP_OPS = {"eq": "eq", "ne": "ne", "lt": "lt", "le": "le",
                "gt": "gt", "ge": "ge"}

    def _gen_cmp_builtin(self, e, fname, ty):
        """assert_*/check_* -> so sánh + rẽ nhánh + báo lỗi qua hàm runtime.

        Phần ĐỊNH DẠNG giá trị hai vế dùng chính bộ bung của print (đệ quy cho
        struct/enum/mảng), nên không cần hàm hỗ trợ riêng nào cho từng kiểu."""
        suffix = fname.rsplit("_", 1)[1]
        is_check = fname.startswith("check")
        a, b = e.args[0], e.args[1]
        gt = self.gtype(a)
        if gt.kind == "slice":
            raise IRGenError("so sánh slice trong assert_* chưa hạ được")
        va = self.gen_expr(a)
        vb = self.gen_expr(b)
        # điều kiện ĐẠT
        if gt.kind == "str" and suffix in ("eq", "ne"):
            same = self.emit_val("call", [va, vb], ty=T.BOOL, node=e,
                                 hint="se", callee="g_str_eq")
            ok = (same if suffix == "eq"
                  else self.emit_val("lnot", [same], ty=T.BOOL, node=e, hint="nn"))
        elif gt.kind == "struct":
            same = self.emit_val("call", [va, vb], ty=T.BOOL, node=e,
                                 hint="se", callee=f"_g_eq_{gt.name}")
            ok = (same if suffix == "eq"
                  else self.emit_val("lnot", [same], ty=T.BOOL, node=e, hint="nn"))
        else:
            ok = self.emit_val(self._CMP_OPS[suffix], [va, vb], ty=T.BOOL,
                               node=e, hint="ac")
        # chuỗi mô tả hai vế (dựng bằng chính bộ bung của print)
        lout, largs = [], []
        rout, rargs = [], []
        self._expand_value(gt, a, lout, largs, 0)
        self._expand_value(gt, b, rout, rargs, 0)
        name = (self.gen_expr(e.args[2]) if len(e.args) > 2
                else I.const_str(fname))
        fmt = ("".join(lout), "".join(rout))
        vals = [ok, name, I.const_str(fmt[0]), I.const_str(fmt[1])]
        vals += [self._fmt_arg_value(x, e) for x in largs]
        vals += [self._fmt_arg_value(x, e) for x in rargs]
        return self.emit_val(
            "intrinsic", vals, ty=T.BOOL if is_check else T.VOID, node=e,
            hint="cb", name=fname, is_check=is_check, line=e.line,
            nleft=len(largs), nright=len(rargs))

    def _fmt_arg_value(self, x, e):
        """Vật hoá một đối số của chuỗi định dạng (kể cả _BoolStr/_EnumName)."""
        if isinstance(x, _SlicePrint):
            v = self.gen_expr(x.node)
            return self.emit_val("intrinsic", [v], ty=T.STR, node=e,
                                 hint="sp", name="print_slice")
        if isinstance(x, _BinStr):
            v = self.gen_expr(x.node)
            # bits <= 0 = "bề rộng tối thiểu, bỏ số 0 dẫn đầu" ('{:b}');
            # '{:0Nb}' cố định N bit. SỐ ÂM in bù hai theo ĐÚNG bề rộng kiểu —
            # nếu không '-1 as i8' sẽ ra 64 bit thay vì 8.
            import re as _re
            m = _re.match(r"^[<>^]?0(\d+)$", x.flags or "")
            if m:
                bits = I.const_int(int(m.group(1)), T.I32)
            else:
                gt = x.gt
                signed = gt.signed if gt.kind == "int" else True
                if signed and gt.kind in ("int", "char", "enum"):
                    w = gt.bits if gt.kind == "int" else (
                        8 if gt.kind == "char" else 32)
                    neg = self.emit_val("lt", [v, I.const_int(0, gt)],
                                        ty=T.BOOL, node=e, hint="bg")
                    bits = self.emit_val(
                        "select", [neg, I.const_int(w, T.I32),
                                   I.const_int(0, T.I32)],
                        ty=T.I32, node=e, hint="bw")
                else:
                    bits = I.const_int(0, T.I32)
            return self.emit_val("call", [v, bits], ty=T.STR, node=e,
                                 hint="bn", callee="g_bin_str")
        if isinstance(x, _Center):
            import re as _re
            v = self.gen_expr(x.node)
            mw = _re.match(r"^[+ ]?#?0?(\d+)(\.\d+)?$", x.flags or "")
            width = int(mw.group(1)) if mw else 0
            spec, is_bool = T.printf_spec(x.gt)
            if is_bool:
                v = self.emit_val("select",
                                  [v, I.const_str("true"), I.const_str("false")],
                                  ty=T.STR, node=e, hint="bs")
                spec = "%s"
            inner = _apply_flags(spec, x.flags.replace(str(width), "", 1)) \
                if mw else spec
            one = self.emit_val("call", [I.const_str(inner), v], ty=T.STR,
                                node=e, hint="f1", callee="g_fmt1", variadic=True)
            return self.emit_val("call", [one, I.const_int(width, T.I32)],
                                 ty=T.STR, node=e, hint="ct", callee="g_center")
        if isinstance(x, _EnumName):
            return self.emit_val("call", [self.gen_expr(x.node)], ty=T.STR,
                                 node=e, hint="en",
                                 callee=f"_g_enum_{x.enum}_name")
        if isinstance(x, _BoolStr):
            c = self.gen_expr(x.node)
            return self.emit_val("select",
                                 [c, I.const_str("true"), I.const_str("false")],
                                 ty=T.STR, node=e, hint="bs")
        if isinstance(x, _Cast):
            v = self.gen_expr(x.node)
            return self.emit_val("cast", [v], ty=self.gtype(x.node), node=e,
                                 hint="fc", to_c=x.ctype)
        return self.gen_expr(x)

    def _expand_struct(self, gt, arg, out, args, depth=0):
        """Bung 'Tên { f: v, ... }' vào chuỗi định dạng (đệ quy)."""
        if depth > 4:
            raise IRGenError("struct lồng quá sâu để in")
        fields = self._struct_fields(gt.name)
        if fields is None:
            raise IRGenError(f"struct chưa biết: '{gt.name}'")
        if not fields:
            out.append(f"{gt.name} {{}}")
            return
        out.append(gt.name + " { ")
        for i, (fname, fty) in enumerate(fields):
            if i:
                out.append(", ")
            out.append(f"{fname}: ")
            fld = A.FieldAccess(arg, fname, getattr(arg, "line", 0),
                                getattr(arg, "col", 0))
            fld.gtype = fty
            self._expand_value(fty, fld, out, args, depth + 1)
        out.append(" }")

    def _expand_array(self, gt, arg, out, args, depth=0):
        """Bung '[v0, v1, ...]' (cắt bớt sau _PRINT_ARRAY_MAX phần tử)."""
        if depth > 4:
            raise IRGenError("mảng lồng quá sâu để in")
        n = gt.n
        shown = min(n, self._PRINT_ARRAY_MAX)
        out.append("[")
        for i in range(shown):
            if i:
                out.append(", ")
            idx = A.IntLit(str(i), getattr(arg, "line", 0),
                           getattr(arg, "col", 0))
            idx.gtype = T.I32
            el = A.Index(arg, idx, getattr(arg, "line", 0),
                         getattr(arg, "col", 0))
            el.gtype = gt.elem
            self._expand_value(gt.elem, el, out, args, depth + 1)
        if shown < n:
            out.append(f", ... ({n} phần tử)")
        out.append("]")

    def _expand_value(self, ty, node, out, args, depth):
        """Một giá trị bên trong struct/mảng đang được bung."""
        if ty.kind == "struct":
            self._expand_struct(ty, node, out, args, depth)
            return
        if ty.kind == "array" and isinstance(ty.n, int):
            self._expand_array(ty, node, out, args, depth)
            return
        if ty.kind == "enum":
            out.append("%s")
            args.append(_EnumName(node, ty.name))
            return
        if ty.kind == "slice":
            raise IRGenError("in slice lồng trong struct chưa hạ được")
        spec, is_bool = T.printf_spec(ty)
        if is_bool:
            out.append("%s")
            args.append(_BoolStr(node))
            return
        out.append(spec)
        args.append(node)

    def _struct_field_type(self, sname, fname):
        for st in self.mod.structs:
            if st.name == sname:
                for fn, ft in st.fields:
                    if fn == fname:
                        return ft
        return None

    def _struct_fields(self, name):
        for st in self.mod.structs:
            if st.name == name:
                return st.fields
        return None

    @staticmethod
    def _spec_for(key, gt, default):
        """Specifier printf cho placeholder có chữ kiểu, tôn trọng BỀ RỘNG thật
        của đối số (in i64 bằng '%d' sẽ đọc sai trên nhiều ABI)."""
        if key in ("d", "u", "x", "X", "o") and gt.kind in ("int", "char"):
            if gt.bits >= 64:
                return {"d": "%lld", "u": "%llu", "x": "%llx",
                        "X": "%llX", "o": "%llo"}[key]
            if key == "d" and not gt.signed:
                return "%u"
        return default

    def _resolve_format(self, template, value_args, newline):
        """(chuỗi_printf, [node_đối_số]) — phân tích placeholder của G.

        Chỉ xử lý tập placeholder mà IR biểu diễn được trực tiếp. Những dạng cần
        hàm hỗ trợ của backend C (căn giữa '^', '{b}' nhị phân, bung struct/mảng/
        slice) chưa hạ được ở đây -> báo IRGenError để backend c-ir nói RÕ là
        chưa hỗ trợ, thay vì sinh mã sai."""
        out = []
        args = []
        i = 0
        ai = 0
        n = len(template)
        while i < n:
            ch = template[i]
            if ch == "{" and i + 1 < n and template[i + 1] == "{":
                out.append("{"); i += 2; continue
            if ch == "}" and i + 1 < n and template[i + 1] == "}":
                out.append("}"); i += 2; continue
            if ch == "%":
                out.append("%%"); i += 1; continue
            if ch != "{":
                out.append(ch); i += 1; continue
            j = template.find("}", i)
            if j == -1:
                out.append("{"); i += 1; continue
            key = template[i + 1:j]
            if ai >= len(value_args):
                raise IRGenError("thiếu đối số cho placeholder")
            arg = value_args[ai]
            ai += 1
            i = j + 1
            gt = self.gtype(arg)
            # Placeholder có CHỮ KIỂU tường minh ('{d}', '{s}', '{f}', '{x}'...)
            # ánh xạ thẳng sang specifier printf. Chỉ nhận các dạng KHÔNG cần
            # hàm hỗ trợ của backend C.
            # Bảng specifier LẤY TỪ backend C (nguồn chân lý duy nhất) — nó đã
            # xử lý đúng các biến thể 'll' cho 64-bit và kiểu ép kèm theo.
            simple = _spec_map()
            # '{key:flags}' — tách cờ, rồi áp vào specifier bằng CHÍNH bộ của
            # backend C (_apply_fmt_flags) để hai đường không trôi lệch.
            kbase, sep, flags = key.partition(":")
            if sep and kbase in ("", "v") and flags and flags[-1] in simple:
                kbase, flags = flags[-1], flags[:-1]
            # '{b}' phụ thuộc KIỂU: bool -> "true"/"false"; số nguyên -> nhị
            # phân (giống backend C). '{:08b}' luôn là nhị phân.
            if kbase == "b" and gt.kind == "bool":
                out.append(_apply_flags("%s", flags) if flags else "%s")
                args.append(_BoolStr(arg))
                continue
            # '{b}' / '{:08b}' — chuỗi NHỊ PHÂN qua hàm runtime g_bin_str.
            if kbase == "b" or (flags and flags.endswith("b")):
                bflags = flags[:-1] if flags.endswith("b") else flags
                out.append(_apply_flags("%s", bflags) if bflags else "%s")
                args.append(_BinStr(arg, gt, bflags))
                continue
            if flags and flags[0] == "^":
                # CĂN GIỮA: printf không có — kết xuất giá trị ra chuỗi rồi đệm
                # hai bên bằng g_center (giống backend C).
                out.append("%s")
                args.append(_Center(arg, gt, flags[1:], kbase))
                continue
            if kbase in simple:
                spec, cast = simple[kbase]
                if cast:
                    arg = _Cast(arg, cast)
            elif kbase in ("", "v"):
                if gt.kind == "enum":
                    # In TÊN biến thể ('Red'), không phải số. Hạ thành lời gọi
                    # hàm tra tên do backend phát cho mỗi enum.
                    out.append(_apply_flags("%s", flags) if flags else "%s")
                    args.append(_EnumName(arg, gt.name))
                    continue
                if gt.kind == "struct" and not flags:
                    # Bung struct thành 'Tên { f: v, ... }' NGAY TRONG chuỗi
                    # định dạng: mỗi trường thành một placeholder riêng. Nhờ vậy
                    # backend không cần biết gì về struct.
                    self._expand_struct(gt, arg, out, args)
                    continue
                if gt.kind == "array" and isinstance(gt.n, int) and not flags:
                    self._expand_array(gt, arg, out, args)
                    continue
                if gt.kind == "slice" and not flags:
                    # Độ dài chỉ biết LÚC CHẠY nên không bung thành chuỗi định
                    # dạng tĩnh được: gọi hàm in do backend phát cho mỗi kiểu
                    # phần tử (giống backend C).
                    out.append("%s")
                    args.append(_SlicePrint(arg, gt))
                    continue
                if gt.kind in ("struct", "array", "slice"):
                    raise IRGenError(
                        f"in giá trị kiểu '{gt}' chưa hạ được sang IR")
                spec, is_bool = T.printf_spec(gt)
                if is_bool:
                    out.append(_apply_flags("%s", flags) if flags else "%s")
                    args.append(_BoolStr(arg))
                    continue
            else:
                raise IRGenError(
                    f"placeholder '{{{key}}}' chưa hạ được sang IR")
            if flags:
                spec = _apply_flags(spec, flags)
            out.append(spec)
            args.append(arg)
            continue
            if key not in ("", "v"):
                raise IRGenError(
                    f"placeholder '{{{key}}}' chưa hạ được sang IR")
            if gt.kind in ("struct", "array", "slice", "enum"):
                raise IRGenError(
                    f"in giá trị kiểu '{gt}' chưa hạ được sang IR")
            spec, is_bool = T.printf_spec(gt)
            if is_bool:
                # bool -> in "true"/"false" bằng một biểu thức chọn, giống
                # backend C. Không cần hàm hỗ trợ nào.
                out.append("%s")
                args.append(_BoolStr(arg))
                continue
            out.append(spec)
            args.append(arg)
        if ai < len(value_args):
            raise IRGenError("thừa đối số so với placeholder")
        if newline:
            out.append("\n")
        return "".join(out), args

    def gen_call(self, e, want_value=True):
        ty = self.gtype(e)

        # method của str -> hàm runtime
        if getattr(e, "is_str_method", False):
            args = [self.gen_expr(e.recv)] + [self.gen_expr(a) for a in e.args]
            if e.str_c_fn == "g_str_at":
                # 's.at(i)' PHẢI kiểm biên (panic), không trả '\0' âm thầm.
                return self.emit_val("intrinsic", args, ty=ty, node=e,
                                     hint="sa", name="str_at_checked")
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

        if fname == "dbg" and e.args:
            # dbg(x): in '[dbg dòng N] <giá trị>' ra stderr rồi TRẢ LẠI x
            # (đánh giá x đúng một lần).
            mark = len(self.blk.instrs) if self.blk is not None else 0
            try:
                arg = e.args[0]
                gt = self.gtype(arg)
                out, fargs = [], []
                self._expand_value(gt, arg, out, fargs, 0)
                line = getattr(e, "line", 0)
                vals = [I.const_str(f"[dbg dòng {line}] " + "".join(out) + "\n")]
                for x in fargs:
                    vals.append(self._fmt_arg_value(x, e))
                self.emit("call", vals, node=e, callee="printf",
                          stream="stderr", is_print=True)
                return self.gen_expr(arg)
            except IRGenError:
                if self.blk is not None:
                    del self.blk.instrs[mark:]
        if fname == "format" and e.args:
            # format(...) -> chuỗi MỚI trên heap. Dùng chính bộ phân giải chuỗi
            # định dạng của print; backend chỉ cần snprintf hai lượt (đo rồi cấp).
            mark = len(self.blk.instrs) if self.blk is not None else 0
            try:
                tpl = e.args[0].value if isinstance(e.args[0], A.StrLit) else "{}"
                va = e.args[1:] if isinstance(e.args[0], A.StrLit) else e.args
                fmt, argexprs = self._resolve_format(tpl, va, False)
                vals = [I.const_str(fmt)]
                for x in argexprs:
                    vals.append(self._fmt_arg_value(x, e))
                return self.emit_val("intrinsic", vals, ty=T.STR, node=e,
                                     hint="fm", name="format")
            except IRGenError:
                if self.blk is not None:
                    del self.blk.instrs[mark:]
        if fname in ("print", "println", "eprint", "eprintln"):
            # Hạ thành printf khi phân tích được chuỗi định dạng; nếu gặp dạng
            # cần hàm hỗ trợ của backend C (căn giữa, '{b}', bung struct...) thì
            # QUAY VỀ intrinsic — IR vẫn hợp lệ, chỉ là backend c-ir chưa sinh
            # mã được cho ca đó. Ném lỗi ở đây sẽ làm hỏng CẢ '--verify-ir'.
            mark = len(self.blk.instrs) if self.blk is not None else 0
            try:
                return self._gen_print(e, fname, ty)
            except IRGenError:
                if self.blk is not None:
                    del self.blk.instrs[mark:]      # bỏ phần đã phát dở
        # 'typeof(x)' là HẰNG CHUỖI (tên kiểu suy luận) — gấp ngay, không đánh
        # giá đối số. 'static_assert' đã được checker kiểm; nó không sinh mã.
        if fname == "typeof":
            gt = self.gtype(e.args[0]) if e.args else T.UNKNOWN
            return I.const_str(str(gt))
        if fname == "static_assert":
            return I.undef(T.VOID)
        if fname == "assert":
            # 'assert(c[, msg])' -> rẽ nhánh + panic. Hạ tường minh để mọi
            # backend có sẵn, và IR nhìn thấy được luồng thoát.
            cond = self.gen_expr(e.args[0])
            msg = (self.gen_expr(e.args[1]) if len(e.args) > 1
                   else I.const_str("assertion failed"))
            Lok, Lbad = self.label("as_ok"), self.label("as_bad")
            self.term(I.Term("branch", [cond], [Lok, Lbad],
                             line=e.line, col=e.col))
            self.start(self.block(Lbad))
            self.emit("panic", [msg], node=e)
            self.term(I.Term("unreach"))
            self.start(self.block(Lok))
            return I.undef(T.VOID)
        if fname in self._CMP_BUILTINS and len(e.args) >= 2:
            return self._gen_cmp_builtin(e, fname, ty)
        if fname == "swap" and len(e.args) == 2:
            # 'swap(a, b)' -> ba lệnh load/store qua địa chỉ.
            aa, ta = self.gen_addr(e.args[0])
            ab, _ = self.gen_addr(e.args[1])
            va = self.emit_val("load", [aa], ty=ta, node=e, hint="sw")
            vb = self.emit_val("load", [ab], ty=ta, node=e, hint="sw")
            self.emit("store", [aa, vb], node=e)
            self.emit("store", [ab, va], node=e)
            return I.undef(T.VOID)
        if fname in self._PRINT_BUILTINS:
            args = []
            for a in e.args:
                try:
                    args.append(self.gen_expr(a))
                except IRGenError:
                    args.append(I.undef(self.gtype(a)))
            return self.emit_val("intrinsic", args, ty=ty, node=e, hint="bi",
                                 name=fname, argc=len(args))

        # ---- built-in số học: hạ thành LỆNH IR THẬT, không phải macro C ----
        # 'abs/min/max/clamp' là macro trong runtime C. Hạ chúng ở đây thành
        # select/cmp nghĩa là MỌI backend (LLVM/WASM) có sẵn, và tối ưu hoá trên
        # IR nhìn thấy được phép toán thay vì một lời gọi mờ đục.
        if fname in ("abs", "min", "max", "clamp") and e.args:
            return self._gen_arith_builtin(e, fname, ty)
        # ---- allocator (0.20.0) ----
        if fname in ("alloc", "alloc_in", "realloc", "realloc_in"):
            in_form = fname.endswith("_in")
            b = 1 if in_form else 0
            is_re = fname.startswith("realloc")
            vals = []
            if in_form:
                vals.append(self.gen_expr(e.args[0]))
            if is_re:
                vals.append(self.gen_expr(e.args[b]))
                b += 1
            elem = self._type_arg_gtype(e.args[b])
            vals.append(self.gen_expr(e.args[b + 1]))
            esz = self._layout_of(elem) if elem is not None else None
            return self.emit_val("intrinsic", vals, ty=ty, node=e, hint="al",
                                 name="realloc" if is_re else "alloc",
                                 with_alloc=in_form, elem_size=esz or 1)
        if fname in ("free", "free_in"):
            in_form = fname == "free_in"
            vals = [self.gen_expr(a) for a in e.args]
            return self.emit_val("intrinsic", vals, ty=T.VOID, node=e,
                                 hint="fr", name="free", with_alloc=in_form)
        if fname == "heap_allocator":
            return self.emit_val("intrinsic", [], ty=ty, node=e, hint="ha",
                                 name="heap_allocator")
        if fname == "arena_allocator":
            return self.emit_val("intrinsic", [self.gen_expr(e.args[0])],
                                 ty=ty, node=e, hint="aa",
                                 name="arena_allocator")
        if fname in ("g_alloc", "g_realloc"):
            # Đối số KIỂU (g_alloc(T, n)) không phải giá trị: mang sang IR dưới
            # dạng cỡ byte đã tính, để backend không phải hiểu cú pháp kiểu của G.
            idx = 0 if fname == "g_alloc" else 1
            vals, elem = [], None
            for i, a in enumerate(e.args):
                if i == idx:
                    elem = self._type_arg_gtype(a)
                    continue
                vals.append(self.gen_expr(a))
            esz = self._layout_of(elem) if elem is not None else None
            if esz is None:
                esz = 1
            return self.emit_val("intrinsic", vals, ty=ty, node=e, hint="al",
                                 name=fname, elem_size=esz,
                                 elem_c=str(elem) if elem is not None else "void")
        if fname == "len" and e.args:
            # 'len' gấp thành HẰNG cho mảng tĩnh / chuỗi literal; chỉ slice mới
            # cần đọc trường '.len' lúc chạy. Trước đây mọi trường hợp đều hạ
            # thành intrinsic 'len' và backend giả định là slice.
            at = self.gtype(e.args[0])
            if at.kind == "array" and isinstance(at.n, int):
                return I.const_int(at.n, T.USIZE)
            if isinstance(e.args[0], A.ArrayLit):
                return I.const_int(len(e.args[0].elements), T.USIZE)
            if at.kind == "str":
                v = self.gen_expr(e.args[0])
                return self.emit_val("call", [v], ty=T.USIZE, node=e,
                                     hint="sl", callee="g_str_len_i")
            v = self.gen_expr(e.args[0])
            return self.emit_val("intrinsic", [v], ty=T.USIZE, node=e,
                                 hint="ln", name="len")
        # Intrinsic HỆ ĐIỀU HÀNH (bit, CPU, cổng I/O, MSR...): hạ thành một
        # intrinsic IR mang theo BỀ RỘNG của đối số, để backend chọn đúng biến
        # thể C ('__builtin_clzll' vs '__builtin_clz'...). Checker đã gác năng
        # lực target trước đó.
        if fname in self._OS_INTRINSICS:
            vals = [self.gen_expr(a) for a in e.args]
            at = self.gtype(e.args[0]) if e.args else T.U64
            return self.emit_val("intrinsic", vals, ty=ty, node=e, hint="os",
                                 name=fname,
                                 bits=(at.bits or 32) if at.kind in
                                 ("int", "char") else 64,
                                 signed=bool(getattr(at, "signed", True)))
        if fname in ("g_free", "memcpy", "memset",
                     "memmove", "memcmp", "vol_read", "vol_write"):
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
