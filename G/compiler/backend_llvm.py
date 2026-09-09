"""
Backend LLVM cho G (`--backend=llvm`).

VÌ SAO KHẢ THI Ở ĐÂY
====================
Toàn bộ công sức Giai đoạn A/B đổ vào việc biến hợp đồng checker↔codegen thành
**G-IR tường minh**. Nhờ đó backend này chỉ phải dịch ~30 lệnh IR sang LLVM IR —
nó KHÔNG cần biết gì về cú pháp G, generic, trait, hay `try`. Đó chính là lợi
tức của việc xây IR trước.

CÁCH LÀM
========
Sinh **LLVM IR dạng văn bản** rồi giao cho `llvmlite` phân tích + xuất object,
thay vì dựng qua API builder. Lý do: văn bản đọc/kiểm bằng mắt được, `--emit-llvm`
cho ra thứ dán thẳng vào `llc` được, và nó không ràng buộc dự án vào một phiên
bản API cụ thể của llvmlite.

Ánh xạ kiểu (khớp bố cục mà `compiler/layout.py` tính):
    int/char/bool -> iN            f32/f64 -> float/double
    *T            -> T*            [N]T   -> [N x T]
    struct        -> %Name (type)  slice<T> -> { T*, i64 }
    str           -> i8*

GIỚI HẠN ĐÃ BIẾT (báo lỗi rõ, không sinh mã sai)
================================================
`asm`, intrinsic hệ điều hành, và vài hàm định dạng của runtime chưa hạ. Những
ca đó bị TỪ CHỐI tường minh — giống nguyên tắc đã theo suốt: thà không dịch còn
hơn dịch sai.
"""

from . import ir as I
from . import types as T
from .backend import IRBackend, BackendError, register


def _fp(x, bits=64) -> str:
    """Hằng số thực của LLVM dạng hex — tránh mất chính xác khi qua văn bản.

    Với 'float' (32-bit), LLVM vẫn dùng hằng hex 64-bit nhưng giá trị PHẢI biểu
    diễn được chính xác ở 32-bit; làm tròn qua struct trước rồi mới in."""
    import struct
    try:
        f = float(x)
    except (TypeError, ValueError):
        f = 0.0
    if bits < 64:
        f = struct.unpack(">f", struct.pack(">f", f))[0]
    return "0x" + struct.pack(">d", f).hex().upper()


def _esc(s: str) -> str:
    """Chuỗi hằng LLVM: escape mọi byte không in được thành \\XX."""
    out = []
    for b in s.encode("utf-8"):
        if b in (34, 92) or b < 32 or b > 126:
            out.append(f"\\{b:02X}")
        else:
            out.append(chr(b))
    return "".join(out)


class LLVMBackend(IRBackend):
    name = "llvm"
    output_ext = ".ll"
    needs_cc = True                # object do llvmlite xuất vẫn cần linker

    def __init__(self):
        self.out = []
        self.strs = {}
        self.decls = {}
        self.mod = None
        self._n = 0
        self._slice_types = {}

    # ------------------------------------------------------------------
    def tmp(self, p="t"):
        self._n += 1
        return f"%{p}{self._n}"

    def w(self, line=""):
        self.out.append(line)

    def emit(self, mod: I.Module) -> str:
        self.mod = mod
        self.out = []
        self.strs = {}
        self.decls = {}
        self._n = 0
        self.structs = {s.name: s for s in mod.structs}
        self.enums = {e.name: dict(e.variants) for e in mod.enums}
        self._user = {f.name for f in mod.funcs if f.blocks and not f.is_extern}

        body = []
        self.w("; === G-IR -> LLVM IR (sinh tự động) ===")
        self.w(f'source_filename = "{mod.name}"')
        self.w("")

        # kiểu struct (theo thứ tự topo do irgen sắp)
        for st in mod.structs:
            fs = ", ".join(self.ty(ft) for _, ft in st.fields) or "i8"
            self.w(f"%{st.name} = type {{ {fs} }}")
        if mod.structs:
            self.w("")

        # global
        for g in mod.globals:
            self.gen_global(g)
        if mod.globals:
            self.w("")

        # Hàm khởi tạo global phải chạy TRƯỚC main: LLVM dùng 'llvm.global_ctors'
        # (tương đương __attribute__((constructor)) của C).
        if any(f.name == "_g_init_globals" and f.blocks for f in mod.funcs):
            self.w("@llvm.global_ctors = appending global "
                   "[1 x { i32, void ()*, i8* }] "
                   "[{ i32, void ()*, i8* } "
                   "{ i32 65535, void ()* @_g_init_globals, i8* null }]")
            self.w("")

        head = len(self.out)          # chỗ chèn hằng chuỗi + khai báo ngoài

        for f in mod.funcs:
            if f.is_extern or not f.blocks:
                continue
            self.gen_func(f)
            self.w("")

        pre = []
        for s, nm in self.strs.items():
            n = len(s.encode("utf-8")) + 1
            pre.append(f'{nm} = private unnamed_addr constant '
                       f'[{n} x i8] c"{_esc(s)}\\00"')
        for d in sorted(self.decls.values()):
            pre.append(d)
        if pre:
            pre.append("")
        self.out[head:head] = pre
        return "\n".join(self.out)

    # ------------------------------------------------------------------
    def ty(self, t) -> str:
        if t is None or t.kind == "void":
            return "void"
        k = t.kind
        if k == "bool":
            return "i1"
        if k == "char":
            return "i8"
        if k == "str":
            return "i8*"
        if k == "int":
            return f"i{t.bits or 32}"
        if k == "float":
            return "double" if (t.bits or 64) >= 64 else "float"
        if k == "enum":
            return "i32"
        if k == "ptr":
            inner = self.ty(t.elem) if t.elem is not None else "i8"
            return ("i8*" if inner == "void" else inner + "*")
        if k == "array":
            if isinstance(t.n, int):
                return f"[{t.n} x {self.ty(t.elem)}]"
            return self.ty(t.elem) + "*"
        if k == "slice":
            return f"{{ {self.ty(t.elem)}*, i64 }}"
        if k == "struct":
            return f"%{t.name}"
        if k == "func":
            ps = ", ".join(self.ty(p) for p in (t.params or ())) or ""
            return f"{self.ty(t.ret)} ({ps})*"
        if k == "null":
            return "i8*"
        return "i32"

    def gen_global(self, g: I.Global):
        lt = self.ty(g.type)
        if g.is_extern:
            self.w(f"@{g.name} = external global {lt}")
            return
        if isinstance(g.init, list):
            vals = ", ".join(f"{self.ty(g.type.elem)} {self.cval(v)}"
                             for v in g.init)
            self.w(f"@{g.name} = global {lt} [{vals}]")
            return
        init = self.cval(g.init) if g.init is not None else self.zero(g.type)
        self.w(f"@{g.name} = global {lt} {init}")

    def zero(self, t) -> str:
        if t is None:
            return "0"
        if t.kind in ("ptr", "str", "null", "func"):
            return "null"
        if t.kind == "float":
            return "0.0"
        if t.kind in ("array", "struct", "slice"):
            return "zeroinitializer"
        return "0"

    def cval(self, v) -> str:
        if v is None:
            return "0"
        c = v.const if isinstance(v, I.Value) else v
        if isinstance(v, I.Value) and v.kind == "strlit":
            return self.strref(v.const)
        if c is None:
            return "null"
        if c is True:
            return "1"
        if c is False:
            return "0"
        if isinstance(c, str):
            ty = v.type if isinstance(v, I.Value) else None
            if ty is not None and ty.kind == "char":
                return str(ord(c) if len(c) == 1 else 0)
            # Hằng SỐ THỰC được lưu nguyên văn dạng chuỗi để giữ đúng chữ số.
            if ty is not None and ty.kind == "float":
                return _fp(c, ty.bits or 64)
            if ty is not None and ty.kind in ("int", "enum", "bool"):
                try:
                    return str(int(c, 0))
                except (TypeError, ValueError):
                    return "0"
            return self.strref(c)
        if isinstance(c, float):
            t = v.type if isinstance(v, I.Value) else None
            return _fp(c, (t.bits or 64) if t is not None else 64)
        return str(c)

    def strref(self, s):
        nm = self.strs.get(s)
        if nm is None:
            nm = f"@.str{len(self.strs)}"
            self.strs[s] = nm
        n = len(s.encode("utf-8")) + 1
        return f"getelementptr inbounds ([{n} x i8], [{n} x i8]* {nm}, i64 0, i64 0)"

    # ------------------------------------------------------------------
    def val(self, v: I.Value, env) -> str:
        if v.kind == "temp":
            return f"%{v.name}"
        if v.kind == "global":
            return f"@{v.name}"
        if v.kind == "func":
            return f"@{v.name}"
        if v.kind == "undef":
            return "zeroinitializer" if v.type is not None and v.type.kind in (
                "struct", "array", "slice") else "0"
        return self.cval(v)

    def tv(self, v: I.Value, env) -> str:
        """'<kiểu> <giá trị>' — dạng toán hạng của LLVM."""
        return f"{self.ty(v.type)} {self.val(v, env)}"

    # ------------------------------------------------------------------
    def gen_func(self, f: I.Func):
        ps = ", ".join(f"{self.ty(p.type)} %{p.name}" for p in f.params)
        self.w(f"define {self.ty(f.ret)} @{f.name}({ps}) {{")
        env = {}
        for b in f.blocks:
            self.w(f"{b.label}:")
            for ins in b.instrs:
                self.gen_instr(ins, env, f)
            self.gen_term(b.term, f, env)
        self.w("}")

    def gen_term(self, t, f, env):
        if t is None:
            raise BackendError("block thiếu terminator")
        if t.op == "ret":
            if t.args:
                self.w(f"  ret {self.tv(t.args[0], env)}")
            else:
                self.w("  ret void" if f.ret is None or f.ret.kind == "void"
                       else f"  ret {self.ty(f.ret)} {self.zero(f.ret)}")
        elif t.op == "jump":
            self.w(f"  br label %{t.labels[0]}")
        elif t.op == "branch":
            c = self.as_i1(t.args[0], env)
            self.w(f"  br i1 {c}, label %{t.labels[0]}, label %{t.labels[1]}")
        elif t.op == "switch":
            cases = t.extra.get("cases", [])
            dflt = t.labels[-1] if len(t.labels) > len(cases) else t.labels[0]
            arms = " ".join(f"{self.ty(t.args[0].type)} {c}, label %{l}"
                            for c, l in zip(cases, t.labels))
            self.w(f"  switch {self.tv(t.args[0], env)}, label %{dflt} "
                   f"[ {arms} ]")
        elif t.op == "unreach":
            self.w("  unreachable")
        else:
            raise BackendError(f"terminator chưa hỗ trợ: {t.op}")

    def as_i1(self, v, env):
        """Ép một giá trị về i1 để làm điều kiện rẽ nhánh."""
        t = v.type
        if t is not None and t.kind == "bool":
            return self.val(v, env)
        r = self.tmp("c")
        if t is not None and t.kind in ("ptr", "str", "null"):
            self.w(f"  {r} = icmp ne {self.tv(v, env)}, null")
        else:
            self.w(f"  {r} = icmp ne {self.tv(v, env)}, 0")
        return r

    # ------------------------------------------------------------------
    _IARITH = {"add": "add", "sub": "sub", "mul": "mul",
               "and": "and", "or": "or", "xor": "xor",
               "shl": "shl", "shr": "ashr"}
    _FARITH = {"add": "fadd", "sub": "fsub", "mul": "fmul", "div": "fdiv",
               "mod": "frem"}
    _ICMP = {"eq": "eq", "ne": "ne", "lt": "slt", "le": "sle",
             "gt": "sgt", "ge": "sge"}
    _UCMP = {"eq": "eq", "ne": "ne", "lt": "ult", "le": "ule",
             "gt": "ugt", "ge": "uge"}
    _FCMP = {"eq": "oeq", "ne": "one", "lt": "olt", "le": "ole",
             "gt": "ogt", "ge": "oge"}

    def gen_instr(self, ins: I.Instr, env, f):
        op = ins.op
        d = f"%{ins.dst.name}" if ins.dst is not None else None
        A = ins.args

        if op == "alloca":
            inner = ins.type.elem if ins.type is not None else None
            self.w(f"  {d} = alloca {self.ty(inner)}")
            return
        if op == "load":
            pt = self.ty(ins.type)
            self.w(f"  {d} = load {pt}, {self.tv(A[0], env)}")
            return
        if op == "store":
            pt = A[0].type
            # Hằng số thực phải mang ĐÚNG kiểu của ô: 'store double ..., float*'
            # là lệch kiểu (LLVM nhận nhưng giá trị hỏng -> in ra 0).
            if (pt is not None and pt.kind == "ptr" and pt.elem is not None
                    and pt.elem.kind == "float" and A[1].kind == "const"):
                self.w(f"  store {self.ty(pt.elem)} {self.cval(A[1])}, "
                       f"{self.tv(A[0], env)}")
                return
            # 'store <ô mảng>, <con trỏ mảng>': trong bố cục C mảng nằm TẠI CHỖ,
            # không có "ô chứa con trỏ mảng". Phải SAO CHÉP nội dung, nếu không
            # ô nhận giữ một con trỏ và mọi lần đọc sau lấy ra rác.
            if (pt is not None and pt.kind == "ptr" and pt.elem is not None
                    and pt.elem.kind == "array"
                    and A[1].type is not None
                    and A[1].type.kind in ("ptr", "array")):
                self._memcpy(A[0], A[1], pt.elem, env)
                return
            # Bề rộng lệch (vd 'store i64 <len>, i32*'): LLVM đòi khớp tuyệt
            # đối, còn IR cho phép nới. Chèn trunc/sext cho đúng.
            vt, st_ = A[1].type, (pt.elem if pt is not None
                                  and pt.kind == "ptr" else None)
            if (vt is not None and st_ is not None
                    and vt.kind in ("int", "char", "bool", "enum")
                    and st_.kind in ("int", "char", "bool", "enum")
                    and self._bits(vt) != self._bits(st_)):
                r = self.tmp("sc")
                op = ("trunc" if self._bits(vt) > self._bits(st_)
                      else ("zext" if not vt.signed else "sext"))
                self.w(f"  {r} = {op} {self.tv(A[1], env)} to {self.ty(st_)}")
                self.w(f"  store {self.ty(st_)} {r}, {self.tv(A[0], env)}")
                return
            self.w(f"  store {self.tv(A[1], env)}, {self.tv(A[0], env)}")
            return
        if op == "memcpy":
            dst, src = A[0], A[1]
            et = dst.type.elem if dst.type is not None else None
            self._memcpy(dst, src, et, env)
            return
        if op == "elemaddr":
            base, idx = A[0], A[1]
            bt = base.type
            if ins.extra.get("on") == "slice":
                p = self.tmp("sp")
                self.w(f"  {p} = extractvalue {self.tv(base, env)}, 0")
                et = self.ty(ins.type.elem)
                self.w(f"  {d} = getelementptr {et}, {et}* {p}, "
                       f"{self.tv(idx, env)}")
                return
            if (bt is not None and bt.kind == "ptr" and bt.elem is not None
                    and bt.elem.kind == "array"):
                at = self.ty(bt.elem)
                self.w(f"  {d} = getelementptr {at}, {at}* "
                       f"{self.val(base, env)}, i64 0, {self.tv(idx, env)}")
                return
            et = self.ty(ins.type.elem) if ins.type is not None else "i8"
            self.w(f"  {d} = getelementptr {et}, {et}* {self.val(base, env)}, "
                   f"{self.tv(idx, env)}")
            return
        if op == "fieldaddr":
            sname = ins.extra.get("struct")
            fname = ins.extra.get("field") or A[1].const
            st = self.structs.get(sname)
            if st is None:
                raise BackendError(f"struct chưa biết: '{sname}'")
            idx = [n for n, _ in st.fields].index(fname)
            self.w(f"  {d} = getelementptr %{sname}, %{sname}* "
                   f"{self.val(A[0], env)}, i64 0, i32 {idx}")
            return
        if op == "ptradd":
            et = self.ty(ins.type.elem) if ins.type is not None else "i8"
            self.w(f"  {d} = getelementptr {et}, {et}* {self.val(A[0], env)}, "
                   f"{self.tv(A[1], env)}")
            return
        if op in ("add", "sub", "mul", "and", "or", "xor", "shl", "shr",
                  "div", "mod"):
            self._arith(ins, d, A, env)
            return
        if op in self._ICMP:
            lt = A[0].type
            if lt is not None and lt.kind == "float":
                self.w(f"  {d} = fcmp {self._FCMP[op]} {self.tv(A[0], env)}, "
                       f"{self.val(A[1], env)}")
            else:
                tab = self._ICMP if (lt is None or lt.signed) else self._UCMP
                self.w(f"  {d} = icmp {tab[op]} {self.tv(A[0], env)}, "
                       f"{self.val(A[1], env)}")
            return
        if op == "neg":
            t = ins.type
            if t is not None and t.kind == "float":
                self.w(f"  {d} = fneg {self.tv(A[0], env)}")
            else:
                self.w(f"  {d} = sub {self.ty(t)} 0, {self.val(A[0], env)}")
            return
        if op == "not":
            self.w(f"  {d} = xor {self.tv(A[0], env)}, -1")
            return
        if op == "lnot":
            c = self.as_i1(A[0], env)
            self.w(f"  {d} = xor i1 {c}, true")
            return
        if op in ("land", "lor"):
            x = self.as_i1(A[0], env)
            y = self.as_i1(A[1], env)
            self.w(f"  {d} = {'and' if op == 'land' else 'or'} i1 {x}, {y}")
            return
        if op == "select":
            c = self.as_i1(A[0], env)
            self.w(f"  {d} = select i1 {c}, {self.tv(A[1], env)}, "
                   f"{self.tv(A[2], env)}")
            return
        if op in ("cast", "bitcast"):
            self._cast(ins, d, A, env)
            return
        if op == "call":
            self._call(ins, d, A, env)
            return
        if op == "callptr":
            ft = A[0].type
            rt = self.ty(ft.ret if ft is not None else None)
            args = ", ".join(self.tv(x, env) for x in A[1:])
            pre = f"  {d} = " if d else "  "
            self.w(f"{pre}call {rt} {self.val(A[0], env)}({args})")
            return
        if op == "check":
            self._check(ins, A, env)
            return
        if op == "panic":
            self._decl("g_panic", "declare void @g_panic_ext(i8*)")
            self.w(f"  call void @g_panic_ext({self.tv(A[0], env)})")
            self.w("  unreachable")
            return
        if op == "intrinsic":
            self._intrinsic(ins, d, A, env)
            return
        raise BackendError(f"lệnh IR chưa hỗ trợ trong backend llvm: '{op}'")

    # ------------------------------------------------------------------
    def _va_promote(self, v, env):
        """Ép đối số cho hàm biến-đối-số theo quy tắc thăng cấp mặc định của C."""
        t = v.type
        if t is None:
            return self.tv(v, env)
        if t.kind == "float" and (t.bits or 64) < 64:
            r = self.tmp("fp")
            self.w(f"  {r} = fpext {self.tv(v, env)} to double")
            return f"double {r}"
        if t.kind in ("int", "char", "bool", "enum") and self._bits(t) < 32:
            r = self.tmp("ip")
            op = "zext" if (t.kind == "bool" or not t.signed) else "sext"
            self.w(f"  {r} = {op} {self.tv(v, env)} to i32")
            return f"i32 {r}"
        return self.tv(v, env)

    def _memcpy(self, dst, src, elem_ty, env):
        n = self._sizeof(elem_ty)
        self.decls["memcpy"] = ("declare void @llvm.memcpy.p0i8.p0i8.i64"
                                "(i8*, i8*, i64, i1)")
        a, b = self.tmp("mc"), self.tmp("mc")
        self.w(f"  {a} = bitcast {self.tv(dst, env)} to i8*")
        self.w(f"  {b} = bitcast {self.tv(src, env)} to i8*")
        self.w(f"  call void @llvm.memcpy.p0i8.p0i8.i64"
               f"(i8* {a}, i8* {b}, i64 {n}, i1 false)")

    def _arith(self, ins, d, A, env):
        op = ins.op
        t = ins.type
        if t is not None and t.kind == "float":
            self.w(f"  {d} = {self._FARITH[op]} {self.tv(A[0], env)}, "
                   f"{self.val(A[1], env)}")
            return
        if op == "div":
            i = "sdiv" if (t is None or t.signed) else "udiv"
        elif op == "mod":
            i = "srem" if (t is None or t.signed) else "urem"
        elif op == "shr":
            i = "ashr" if (t is None or t.signed) else "lshr"
        else:
            i = self._IARITH[op]
        self.w(f"  {d} = {i} {self.tv(A[0], env)}, {self.val(A[1], env)}")

    def _cast(self, ins, d, A, env):
        src, dst = A[0].type, ins.type
        sv = self.tv(A[0], env)
        st = self.ty(src)
        dt = self.ty(dst)
        if st == dt:
            self.w(f"  {d} = bitcast {sv} to {dt}")
            return
        sk = src.kind if src is not None else "int"
        dk = dst.kind if dst is not None else "int"
        if sk in ("int", "char", "bool", "enum") and dk in ("int", "char",
                                                            "bool", "enum"):
            sb = self._bits(src)
            db = self._bits(dst)
            if db > sb:
                op = "zext" if (sk == "bool" or (src is not None
                                                 and not src.signed)) else "sext"
            elif db < sb:
                op = "trunc"
            else:
                op = "bitcast"
            self.w(f"  {d} = {op} {sv} to {dt}")
            return
        if sk == "float" and dk in ("int", "char", "enum"):
            op = "fptosi" if (dst is None or dst.signed) else "fptoui"
            self.w(f"  {d} = {op} {sv} to {dt}")
            return
        if sk in ("int", "char", "bool", "enum") and dk == "float":
            op = "sitofp" if (src is None or src.signed) else "uitofp"
            self.w(f"  {d} = {op} {sv} to {dt}")
            return
        if sk == "float" and dk == "float":
            sb, db = self._bits(src), self._bits(dst)
            self.w(f"  {d} = {'fpext' if db > sb else 'fptrunc'} {sv} to {dt}")
            return
        if sk in ("ptr", "str", "null", "array") and dk in ("ptr", "str",
                                                            "null", "array"):
            self.w(f"  {d} = bitcast {sv} to {dt}")
            return
        if sk in ("ptr", "str", "null") and dk in ("int", "char", "enum"):
            self.w(f"  {d} = ptrtoint {sv} to {dt}")
            return
        if sk in ("int", "char", "enum") and dk in ("ptr", "str", "null"):
            self.w(f"  {d} = inttoptr {sv} to {dt}")
            return
        self.w(f"  {d} = bitcast {sv} to {dt}")

    @staticmethod
    def _bits(t):
        if t is None:
            return 32
        if t.kind == "bool":
            return 1
        if t.kind == "char":
            return 8
        if t.kind == "enum":
            return 32
        return t.bits or 32

    def _sizeof(self, t):
        from . import layout as _lay
        from . import target as _tg
        lay = _lay.Layout(_tg.default_target(),
                          {s.name: list(s.fields) for s in self.mod.structs})
        try:
            return lay.size_of(t)
        except Exception:
            return 8

    def _decl(self, key, text):
        self.decls[key] = text

    def _call(self, ins, d, A, env):
        callee = ins.extra.get("callee")
        if ins.extra.get("is_print"):
            stream = ins.extra.get("stream", "stdout")
            self._decl("printf", "declare i32 @printf(i8*, ...)")
            self._decl("fprintf", "declare i32 @fprintf(i8*, i8*, ...)")
            self._decl("g_stream", "declare i8* @g_get_stream(i32)")
            # printf là hàm BIẾN ĐỐI SỐ: C tự thăng cấp float->double và số hẹp
            # -> int. LLVM KHÔNG tự làm, nên phải ép tường minh, nếu không '%g'
            # đọc 4 byte float như 8 byte double (in ra 0) và '%d' đọc rác.
            parts = [self.tv(A[0], env)]
            for x in A[1:]:
                parts.append(self._va_promote(x, env))
            args = ", ".join(parts)
            if stream == "stderr":
                sp = self.tmp("st")
                self.w(f"  {sp} = call i8* @g_get_stream(i32 1)")
                self.w(f"  call i32 (i8*, i8*, ...) @fprintf(i8* {sp}, {args})")
            else:
                self.w(f"  call i32 (i8*, ...) @printf({args})")
            return
        rt = self.ty(ins.type) if d else "void"
        sig = ", ".join(self.ty(x.type) for x in A)
        if callee not in self._user:
            self._decl(callee, f"declare {rt} @{callee}({sig})")
        args = ", ".join(self.tv(x, env) for x in A)
        pre = f"  {d} = " if d else "  "
        self.w(f"{pre}call {rt} @{callee}({args})")

    def _check(self, ins, A, env):
        kind = ins.extra.get("kind")
        if kind == "null":
            return
        self._decl("g_bounds_fail",
                   "declare void @g_bounds_fail_ext(i64, i64, i8*)")
        self._decl("g_div_zero_fail",
                   "declare void @g_div_zero_fail_ext(i8*)")
        where = self.strref(f"{ins.line}:{ins.col}")
        ok, bad = f"chk_ok{self._next()}", f"chk_bad{self._n}"
        if kind in ("bounds", "slice_bounds"):
            if kind == "bounds":
                i, n = A[0], A[1]
                iv, nv = self.tv(i, env), self.val(n, env)
                c = self.tmp("bc")
                self.w(f"  {c} = icmp ult {iv}, {nv}")
                i64i = self._to_i64(A[0], env)
                i64n = self._to_i64(A[1], env)
            else:
                i, s = A[0], A[1]
                ln = self.tmp("sl")
                self.w(f"  {ln} = extractvalue {self.tv(s, env)}, 1")
                iw = self._to_i64(A[0], env)
                c = self.tmp("bc")
                self.w(f"  {c} = icmp ult i64 {iw}, {ln}")
                i64i, i64n = iw, ln
            self.w(f"  br i1 {c}, label %{ok}, label %{bad}")
            self.w(f"{bad}:")
            self.w(f"  call void @g_bounds_fail_ext(i64 {i64i}, i64 {i64n}, "
                   f"i8* {where})")
            self.w("  unreachable")
            self.w(f"{ok}:")
            return
        if kind == "divzero":
            c = self.tmp("dz")
            self.w(f"  {c} = icmp ne {self.tv(A[0], env)}, 0")
            self.w(f"  br i1 {c}, label %{ok}, label %{bad}")
            self.w(f"{bad}:")
            self.w(f"  call void @g_div_zero_fail_ext(i8* {where})")
            self.w("  unreachable")
            self.w(f"{ok}:")
            return
        raise BackendError(f"check chưa hỗ trợ: '{kind}'")

    def _next(self):
        self._n += 1
        return self._n

    def _to_i64(self, v, env):
        t = v.type
        if t is not None and (t.bits or 32) >= 64:
            return self.val(v, env)
        r = self.tmp("z")
        self.w(f"  {r} = sext {self.tv(v, env)} to i64")
        return r

    def _intrinsic(self, ins, d, A, env):
        name = ins.extra.get("name")
        if name == "makeslice":
            et = self.ty(ins.type.elem)
            base, lo, hi = A[0], A[1], A[2]
            bt = base.type
            if bt is not None and bt.kind == "ptr" and bt.elem is not None \
                    and bt.elem.kind == "array":
                at = self.ty(bt.elem)
                p0 = self.tmp("sb")
                self.w(f"  {p0} = getelementptr {at}, {at}* "
                       f"{self.val(base, env)}, i64 0, i64 0")
            elif bt is not None and bt.kind == "slice":
                p0 = self.tmp("sb")
                self.w(f"  {p0} = extractvalue {self.tv(base, env)}, 0")
            else:
                p0 = self.val(base, env)
            lo64 = self._to_i64(lo, env)
            hi64 = self._to_i64(hi, env)
            p = self.tmp("sp")
            self.w(f"  {p} = getelementptr {et}, {et}* {p0}, i64 {lo64}")
            ln = self.tmp("sn")
            self.w(f"  {ln} = sub i64 {hi64}, {lo64}")
            s0 = self.tmp("s")
            st = self.ty(ins.type)
            self.w(f"  {s0} = insertvalue {st} undef, {et}* {p}, 0")
            self.w(f"  {d} = insertvalue {st} {s0}, i64 {ln}, 1")
            return
        if name == "len":
            self.w(f"  {d} = extractvalue {self.tv(A[0], env)}, 1")
            return
        if name == "slice_ptr":
            self.w(f"  {d} = extractvalue {self.tv(A[0], env)}, 0")
            return
        # ---- các intrinsic còn lại: gọi hàm runtime tương ứng ----
        # Runtime của G là header 'static inline' nên object LLVM không thấy;
        # shim C (xem driver._LLVM_SHIM) xuất chúng ra ngoài dòng.
        rt = _RUNTIME_INTRINSICS.get(name)
        if rt is not None:
            fn, ret_kind = rt
            rty = self.ty(ins.type) if (d and ret_kind != "void") else "void"
            sig = ", ".join(self.ty(x.type) for x in A)
            self._decl(fn, f"declare {rty} @{fn}({sig})")
            args = ", ".join(self.tv(x, env) for x in A)
            pre = f"  {d} = " if (d and rty != "void") else "  "
            self.w(f"{pre}call {rty} @{fn}({args})")
            return
        raise BackendError(
            f"intrinsic '{name}' chưa hạ trong backend llvm — ca này bị TỪ "
            f"CHỐI thay vì sinh mã sai")


#: intrinsic IR -> hàm runtime (do shim C xuất). Chỉ những thứ ánh xạ 1-1
#: được; phần định dạng phức tạp vẫn bị từ chối tường minh.
_RUNTIME_INTRINSICS = {
    "popcount": ("g_ll_popcount", "int"),
    "clz": ("g_ll_clz", "int"),
    "ctz": ("g_ll_ctz", "int"),
    "bswap": ("g_ll_bswap", "int"),
    "rotl": ("g_ll_rotl", "int"),
    "rotr": ("g_ll_rotr", "int"),
    "g_alloc": ("g_ll_calloc", "ptr"),
    "alloc": ("g_ll_calloc", "ptr"),
    "g_free": ("g_ll_free", "void"),
    "free": ("g_ll_free", "void"),
    "str_at_checked": ("g_str_at_c", "int"),
    "memcpy": ("memcpy", "ptr"),
    "memmove": ("memmove", "ptr"),
    "memset": ("memset", "ptr"),
    "memcmp": ("memcmp", "int"),
}

register(LLVMBackend)
