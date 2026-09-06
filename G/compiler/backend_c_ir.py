"""
Backend C đọc từ G-IR (`--backend=c-ir`).

VỊ TRÍ TRONG CHIẾN LƯỢC
=======================
Đây là **Giai đoạn B** của ARCHITECTURE.md §3: viết backend C thứ hai đọc từ IR,
chạy SONG SONG với backend cũ (đọc thẳng AST), rồi so khớp đầu ra trên toàn bộ
bộ test. Chỉ khi khớp 100% mới đổi mặc định.

Vì sao không sửa tại chỗ backend cũ: nó đang chạy đúng 225 ca test. Thay thế
từng phần sẽ tạo ra trạng thái nửa vời không kiểm chứng được. Hai backend song
song thì mọi khác biệt đều lộ ra ngay dưới dạng test đỏ.

CÁCH SINH MÃ
============
IR là CFG phẳng gồm basic block; C không có `goto` vào giữa biểu thức nhưng CÓ
`goto` giữa các nhãn — nên ánh xạ gần như một-một:

    block L:  ...lệnh...          ->   L: { ...lệnh...  }
    jump M                        ->   goto M;
    branch c ? T : F              ->   if (c) goto T; else goto F;
    switch v [c=>L...] default D  ->   switch (v) { case c: goto L; ... }
    ret v                         ->   return v;

Mỗi temp `%tN` thành một biến C khai báo TRƯỚC ở đầu hàm (C89-style), vì temp có
thể được định nghĩa trong một block và dùng ở block khác — khai báo tại chỗ sẽ
ra ngoài phạm vi sau `goto`.

GIỚI HẠN ĐÃ BIẾT
================
`intrinsic` mang ngữ nghĩa cấp cao (print/format/dbg/assert_*) chưa được hạ chi
tiết trong `irgen.py` — chúng giữ nguyên đối số đã tính. Backend này xử lý được
tập thường dùng; những gì chưa hỗ trợ sẽ báo lỗi RÕ RÀNG thay vì sinh C sai.
Đó là lý do nó chưa phải mặc định.
"""

from . import ir as I
from . import types as T
from .backend import IRBackend, BackendError, register


class CIRBackend(IRBackend):
    name = "c-ir"
    output_ext = ".c"
    needs_cc = True

    def __init__(self):
        self.out = []
        self.indent = 0
        self.mod = None
        self.slice_typedefs = {}
        self.slice_decls = []
        self._tmp_types = {}

    # ------------------------------------------------------------------
    def w(self, line=""):
        self.out.append("    " * self.indent + line if line else "")

    def emit(self, mod: I.Module) -> str:
        self.mod = mod
        self.out = []
        self.w("// === Sinh tự động bởi trình biên dịch G (backend c-ir) ===")
        self.w('#include "g_runtime.h"')
        self.w("")

        # 1) enum
        for en in mod.enums:
            vs = ", ".join(f"{n} = {v}" for n, v in en.variants)
            self.w(f"typedef enum {{ {vs} }} {en.name};")
        if mod.enums:
            self.w("")

        # 1b) hàm tra TÊN biến thể cho mỗi enum (để in '{}' ra 'Red', không phải 0)
        for en in mod.enums:
            self.w(f"static const char* _g_enum_{en.name}_name({en.name} v) {{")
            self.indent += 1
            self.w("switch ((long long)v) {")
            self.indent += 1
            seen = set()
            for vn, vv in en.variants:
                if vv in seen:
                    continue           # trùng giá trị -> lấy tên đầu (C cấm case trùng)
                seen.add(vv)
                self.w(f'case {vv}: return "{vn}";')
            self.indent -= 1
            self.w("}")
            self.w('return "?";')
            self.indent -= 1
            self.w("}")
        if mod.enums:
            self.w("")

        # 2) forward-decl struct + typedef slice (chữ ký cần)
        for st in mod.structs:
            self.w(f"typedef struct {st.name} {st.name};")
        slice_at = len(self.out)
        if mod.structs:
            self.w("")

        # 3) định nghĩa struct
        for st in mod.structs:
            attr = ""
            bits = []
            if st.packed:
                bits.append("packed")
            if st.align:
                bits.append(f"aligned({st.align})")
            if bits:
                attr = f" __attribute__(({', '.join(bits)})) "
            self.w(f"struct {st.name}{attr} {{")
            self.indent += 1
            for fname, fty in st.fields:
                self.w(self.c_decl(fty, fname) + ";")
            self.indent -= 1
            self.w("};")
        if mod.structs:
            self.w("")

        # 4) global
        for g in mod.globals:
            self.gen_global(g)
        if mod.globals:
            self.w("")

        # 5) nguyên mẫu hàm
        for f in mod.funcs:
            self.w(self.signature(f) + ";")
        self.w("")

        # 6) thân hàm
        for f in mod.funcs:
            if f.is_extern or not f.blocks:
                continue
            self.gen_func(f)
            self.w("")

        if self.slice_decls:
            block = ["// Slice: con trỏ béo { T* ptr; size_t len; }."]
            block += self.slice_decls + [""]
            self.out[slice_at:slice_at] = block
        return "\n".join(self.out)

    # ------------------------------------------------------------------
    # kiểu
    # ------------------------------------------------------------------
    def slice_typedef(self, elem) -> str:
        elem_c = self.c_type(elem)
        nm = self.slice_typedefs.get(elem_c)
        if nm is None:
            ident = (elem_c.replace("*", "p").replace(" ", "_")
                     .replace("const_charp", "str"))
            nm = f"GSlice_{ident}"
            self.slice_typedefs[elem_c] = nm
            self.slice_decls.append(f"G_SLICE_DEF({elem_c}, {nm});")
        return nm

    def c_type(self, ty) -> str:
        """GType -> chuỗi kiểu C (dạng trừu tượng, mảng phân rã thành con trỏ)."""
        if ty is None:
            return "void"
        if ty.kind == "slice":
            return self.slice_typedef(ty.elem)
        if ty.kind == "array":
            return self.c_type(ty.elem) + "*"
        if ty.kind == "func":
            return "void*"
        return T.c_type(ty)

    def c_decl(self, ty, name: str) -> str:
        """Khai báo C 'kiểu tên', giữ đúng dạng mảng '[N]'."""
        if ty is not None and ty.kind == "array" and isinstance(ty.n, int):
            dims = []
            cur = ty
            while cur.kind == "array" and isinstance(cur.n, int):
                dims.append(cur.n)
                cur = cur.elem
            arr = "".join(f"[{d}]" for d in dims)
            return f"{self.c_type(cur)} {name}{arr}"
        return f"{self.c_type(ty)} {name}"

    def decl_of(self, ty, name: str) -> str:
        """Khai báo C cho một temp. Con trỏ TỚI MẢNG phải giữ dạng 'T (*p)[N]';
        c_type() làm mảng phân rã thành 'T*' nên dùng nó ở đây sẽ sinh 'T**' —
        sai kiểu và segfault khi giải tham chiếu."""
        if (ty is not None and ty.kind == "ptr" and ty.elem is not None
                and ty.elem.kind == "array" and isinstance(ty.elem.n, int)):
            return self._array_ptr_decl(ty.elem, name)
        return self.c_decl(ty, name)

    def _array_ptr_decl(self, arr_ty, name: str) -> str:
        """Khai báo 'con trỏ tới mảng': T (*name)[N][M]..."""
        dims = []
        cur = arr_ty
        while cur.kind == "array" and isinstance(cur.n, int):
            dims.append(cur.n)
            cur = cur.elem
        suffix = "".join(f"[{d}]" for d in dims)
        return f"{self.c_type(cur)} (*{name}){suffix}"

    def signature(self, f: I.Func) -> str:
        ps = ", ".join(self.c_decl(p.type, p.name) for p in f.params) or "void"
        q = "extern " if f.is_extern else ""
        return f"{q}{self.c_type(f.ret)} {f.name}({ps})"

    # ------------------------------------------------------------------
    def gen_global(self, g: I.Global):
        if g.is_extern:
            self.w(f"extern {self.c_decl(g.type, g.name)};")
            return
        init = ""
        if isinstance(g.init, list):
            init = " = { " + ", ".join(self.val(v) for v in g.init) + " }"
        elif g.init is not None:
            init = f" = {self.val(g.init)}"
        self.w(f"static {self.c_decl(g.type, g.name)}{init};")

    # ------------------------------------------------------------------
    # giá trị
    # ------------------------------------------------------------------
    def val(self, v: I.Value) -> str:
        if not isinstance(v, I.Value):
            raise BackendError(f"toán hạng không phải Value: {v!r}")
        if v.kind == "temp":
            return v.name
        if v.kind in ("global", "func"):
            return v.name
        if v.kind == "strlit":
            return self.c_string(v.const)
        if v.kind == "undef":
            return f"(({self.c_type(v.type)}){{0}})" if v.type else "0"
        c = v.const
        if c is None:
            return "NULL"
        if c is True:
            return "true"
        if c is False:
            return "false"
        if isinstance(c, str):
            # Hằng SỐ THỰC được lưu nguyên văn dạng chuỗi ('3.14') để giữ đúng
            # chữ số — phát thẳng, KHÔNG bọc thành chuỗi C.
            if v.type is not None and v.type.kind == "float":
                return c
            return self.c_char(c) if v.type is not None and \
                v.type.kind == "char" else self.c_string(c)
        if isinstance(c, int):
            if c > (1 << 63) - 1:
                return f"{c}ULL"
            if c > (1 << 31) - 1 or c < -(1 << 31):
                return f"{c}LL"
            return str(c)
        return str(c)

    @staticmethod
    def c_string(s: str) -> str:
        out = ['"']
        for ch in s:
            o = ord(ch)
            if ch == '"':
                out.append('\\"')
            elif ch == "\\":
                out.append("\\\\")
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\t":
                out.append("\\t")
            elif ch == "\r":
                out.append("\\r")
            elif o < 32 or o == 127:
                out.append(f"\\{o:03o}")
            elif o > 127:
                out += [f"\\{b:03o}" for b in ch.encode("utf-8")]
            else:
                out.append(ch)
        out.append('"')
        return "".join(out)

    @staticmethod
    def c_char(c: str) -> str:
        if c == "'":
            return "'\\''"
        if c == "\\":
            return "'\\\\'"
        if c == "\n":
            return "'\\n'"
        if c == "\t":
            return "'\\t'"
        o = ord(c) if c else 0
        if o < 32 or o > 126:
            return f"'\\{o:03o}'"
        return f"'{c}'"

    # ------------------------------------------------------------------
    # hàm
    # ------------------------------------------------------------------
    def gen_func(self, f: I.Func):
        self.w(self.signature(f) + " {")
        self.indent += 1

        # Khai báo TRƯỚC mọi temp: chúng vượt qua ranh giới block (goto), nên
        # khai báo tại chỗ sẽ ra ngoài phạm vi.
        decls = []
        for b in f.blocks:
            for ins in b.instrs:
                if ins.dst is None:
                    continue
                if ins.op == "alloca":
                    # alloca -> một BIẾN thật + con trỏ trỏ tới nó.
                    inner = ins.type.elem if ins.type is not None else T.I32
                    slot = ins.dst.name + "__s"
                    decls.append(self.c_decl(inner, slot) + " = {0};")
                    if inner.kind == "array":
                        # '*[N]T' trong C là 'T (*)[N]', KHÔNG phải 'T**'.
                        # c_type() làm mảng phân rã nên phải dựng tay, nếu không
                        # 'int v[4]' bị khai báo là 'int** v' -> segfault.
                        ptr_c = self._array_ptr_decl(inner, ins.dst.name)
                        decls.append(f"{ptr_c} = &{slot};")
                    else:
                        decls.append(f"{self.c_type(ins.type)} "
                                     f"{ins.dst.name} = &{slot};")
                else:
                    decls.append(self.decl_of(ins.type, ins.dst.name) + ";")
        for d in decls:
            self.w(d)
        if decls:
            self.w("")

        for i, b in enumerate(f.blocks):
            self.indent -= 1
            self.w(f"{b.label}:;")
            self.indent += 1
            for ins in b.instrs:
                if ins.op == "alloca":
                    continue                  # đã xử lý ở phần khai báo
                self.gen_instr(ins)
            self.gen_term(b.term, f)
        self.indent -= 1
        self.w("}")

    def gen_term(self, t: I.Term, f: I.Func):
        if t is None:
            raise BackendError("block thiếu terminator")
        if t.op == "ret":
            self.w(f"return {self.val(t.args[0])};" if t.args else "return;")
        elif t.op == "jump":
            self.w(f"goto {t.labels[0]};")
        elif t.op == "branch":
            self.w(f"if ({self.val(t.args[0])}) goto {t.labels[0]}; "
                   f"else goto {t.labels[1]};")
        elif t.op == "switch":
            cases = t.extra.get("cases", [])
            self.w(f"switch ({self.val(t.args[0])}) {{")
            self.indent += 1
            for c, lbl in zip(cases, t.labels):
                self.w(f"case {c}: goto {lbl};")
            if len(t.labels) > len(cases):
                self.w(f"default: goto {t.labels[-1]};")
            self.indent -= 1
            self.w("}")
        elif t.op == "unreach":
            self.w("__builtin_unreachable();")
        else:
            raise BackendError(f"terminator chưa hỗ trợ: '{t.op}'")

    # ------------------------------------------------------------------
    _BIN = {
        "add": "+", "sub": "-", "mul": "*", "div": "/", "mod": "%",
        "and": "&", "or": "|", "xor": "^", "shl": "<<", "shr": ">>",
        "eq": "==", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">=",
        "land": "&&", "lor": "||",
    }
    _UN = {"neg": "-", "not": "~", "lnot": "!"}

    def gen_instr(self, ins: I.Instr):
        op = ins.op
        a = [self.val(x) for x in ins.args]
        d = ins.dst.name if ins.dst is not None else None

        if op in self._BIN:
            # Phép toán số học/bit: ép toán hạng TRÁI sang kiểu KẾT QUẢ trước.
            # C tính '1 << 40' trong 'int' (32-bit) rồi mới gán -> UB/mất bit,
            # dù đích là i64. Checker đã suy ra kiểu rộng hơn nên tôn trọng nó.
            if (op not in ("land", "lor") and ins.type is not None
                    and ins.type.kind in ("int", "float")):
                cast = f"({self.c_type(ins.type)})"
                self.w(f"{d} = ({cast}({a[0]})) {self._BIN[op]} ({a[1]});")
            else:
                self.w(f"{d} = ({a[0]}) {self._BIN[op]} ({a[1]});")
        elif op in self._UN:
            # Ép sang kiểu KẾT QUẢ trước khi tính: '-w' với w:u32 phải ra i64
            # (-1), không phải wrap trong u32 (4294967295). Checker đã suy ra
            # kiểu rộng hơn — tôn trọng nó, giống nhánh nhị phân.
            if (op != "lnot" and ins.type is not None
                    and ins.type.kind in ("int", "float")):
                self.w(f"{d} = {self._UN[op]}"
                       f"(({self.c_type(ins.type)})({a[0]}));")
            else:
                self.w(f"{d} = {self._UN[op]}({a[0]});")
        elif op == "load":
            self.w(f"{d} = *({a[0]});")
        elif op == "store":
            self.w(f"*({a[0]}) = {a[1]};")
        elif op == "memcpy":
            self.w(f"memcpy({a[0]}, {a[1]}, sizeof(*({a[0]})));")
        elif op == "elemaddr":
            if ins.extra.get("on") == "slice":
                self.w(f"{d} = &(({a[0]}).ptr[{a[1]}]);")
            else:
                self.w(f"{d} = &((*({a[0]}))[{a[1]}]);")
        elif op == "fieldaddr":
            fld = ins.extra.get("field") or ins.args[1].const
            self.w(f"{d} = &((*({a[0]})).{fld});")
        elif op == "ptradd":
            self.w(f"{d} = ({a[0]}) + ({a[1]});")
        elif op == "cast":
            # 'to_c': kiểu C tường minh do irgen yêu cầu (ép đối số printf).
            ct = ins.extra.get("to_c") or self.c_type(ins.type)
            self.w(f"{d} = ({ct})({a[0]});")
        elif op == "bitcast":
            self.w(f"memcpy(&{d}, &({a[0]}), sizeof({d}));")
        elif op == "call":
            callee = ins.extra.get("callee")
            if ins.extra.get("is_print"):
                # print đã được hạ thành (chuỗi_định_dạng, đối số...) trong
                # irgen; ở đây chỉ chọn luồng ra và ÉP KIỂU cho đúng quy tắc
                # thăng cấp của hàm biến-đối-số: f32 -> double, số hẹp -> int.
                # Thiếu bước này, '%g' đọc 4 byte float như 8 byte double.
                stream = ins.extra.get("stream", "stdout")
                parts = [a[0]]
                for v, cv in zip(ins.args[1:], a[1:]):
                    parts.append(self._va_promote(v, cv))
                self.w(f"fprintf({stream}, {', '.join(parts)});")
                return
            if callee == "g_print_raw":
                stream = ins.extra.get("stream", "stdout")
                self.w(f"fputs({a[0]}, {stream});")
                return
            call = f"{callee}({', '.join(a)})"
            self.w(f"{d} = {call};" if d else f"{call};")
        elif op == "callptr":
            call = f"({a[0]})({', '.join(a[1:])})"
            self.w(f"{d} = {call};" if d else f"{call};")
        elif op == "select":
            self.w(f"{d} = ({a[0]}) ? ({a[1]}) : ({a[2]});")
        elif op == "check":
            self.gen_check(ins, a)
        elif op == "asm":
            tpl = (ins.extra.get("template") or "").replace("\n", "\\n\\t")
            self.w(f'__asm__ __volatile__("{tpl}");')
        elif op == "intrinsic":
            self.gen_intrinsic(ins, a, d)
        elif op == "panic":
            msg = a[0] if a else '"panic"'
            self.w(f"g_panic({msg});")
        else:
            raise BackendError(f"lệnh IR chưa hỗ trợ trong backend c-ir: '{op}'")

    @staticmethod
    def _va_promote(v: I.Value, c: str) -> str:
        """Ép kiểu đối số cho hàm biến-đối-số (printf). C tự thăng cấp float->
        double và các số hẹp->int khi có nguyên mẫu, nhưng ta ép TƯỜNG MINH để
        không phụ thuộc vào việc trình biên dịch có thấy nguyên mẫu hay không."""
        t = v.type
        if t is None:
            return c
        if t.kind == "float":
            return f"(double)({c})"
        if t.kind in ("int", "char", "bool", "enum") and (t.bits or 32) < 32:
            return f"(int)({c})"
        return c

    def gen_check(self, ins: I.Instr, a):
        kind = ins.extra.get("kind")
        where = self.c_string(f"{ins.line}:{ins.col}")
        if kind == "bounds":
            self.w(f"(void)g_idx({a[0]}, {a[1]}, {where});")
        elif kind == "slice_bounds":
            self.w(f"(void)g_sidx({a[1]}, {a[0]}, {where});")
        elif kind == "divzero":
            self.w(f"if (({a[0]}) == 0) g_div_zero_fail({where});")
        elif kind == "null":
            self.w(f"(void)({a[0]});")
        else:
            raise BackendError(f"check chưa hỗ trợ: '{kind}'")

    def gen_intrinsic(self, ins: I.Instr, a, d):
        name = ins.extra.get("name")
        if name == "makeslice":
            sn = self.slice_typedef(ins.type.elem)
            base, lo, hi = a[0], a[1], a[2]
            self.w(f"{d} = ({sn}){{ ({base}) + ({lo}), (size_t)(({hi}) - ({lo})) }};")
            return
        if name in ("g_alloc", "g_realloc"):
            # Cỡ phần tử đã được tính trong IR (theo target), nên ở đây chỉ cần
            # calloc/realloc thô — backend không phải hiểu kiểu của G.
            esz = ins.extra.get("elem_size", 1)
            cast = f"({self.c_type(ins.type)})"
            if name == "g_alloc":
                self.w(f"{d} = {cast}calloc((size_t)({a[0]}), {esz});")
            else:
                self.w(f"{d} = {cast}realloc({a[0]}, "
                       f"(size_t)({a[1]}) * {esz});")
            return
        if name == "g_free":
            self.w(f"free({a[0]});")
            return
        if name in ("memcpy", "memmove", "memset", "memcmp"):
            call = f"{name}({', '.join(a)})"
            self.w(f"{d} = {call};" if d else f"{call};")
            return
        if name == "vol_read":
            self.w(f"{d} = *(volatile {self.c_type(ins.type)}*)({a[0]});")
            return
        if name == "vol_write":
            inner = ins.args[1].type
            self.w(f"*(volatile {self.c_type(inner)}*)({a[0]}) = {a[1]};")
            return
        if name == "len":
            self.w(f"{d} = ({a[0]}).len;")
            return
        if name in ("sizeof", "alignof"):
            raise BackendError(
                f"{name} chưa gấp được thành hằng cho kiểu này")
        raise BackendError(
            f"intrinsic '{name}' chưa được hạ chi tiết trong IR nên backend "
            f"c-ir chưa sinh mã được (xem irgen.py: các built-in in ấn/format "
            f"vẫn giữ ở dạng intrinsic)")


register(CIRBackend)
