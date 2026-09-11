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

_OS_SIMPLE = {
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
        self.slice_print_fns = {}
        self.slice_print_decls = []
        self.fnptr_typedefs = {}
        self.fnptr_decls = []
        self._param_names = set()
        self._cur_src = None
        self._tmp_types = {}

    # ------------------------------------------------------------------
    def w(self, line=""):
        self.out.append("    " * self.indent + line if line else "")

    def emit(self, mod: I.Module) -> str:
        self.mod = mod
        self.out = []
        # Hàm do NGƯỜI DÙNG định nghĩa (có thân, không phải main/extern) là
        # những hàm duy nhất được đổi tên; mọi callee khác là ký hiệu runtime
        # hoặc extern và phải giữ nguyên.
        self._user_fns = {f.name for f in mod.funcs
                          if not f.is_extern and f.blocks and f.name != "main"}
        self.w("// === Sinh tự động bởi trình biên dịch G (backend c-ir) ===")
        self.w('#include "g_runtime.h"')
        self.w("")

        # 1) enum
        for en in mod.enums:
            vs = ", ".join(f"{self.cn(n)} = {v}" for n, v in en.variants)
            self.w(f"typedef enum {{ {vs} }} {self.cn(en.name)};")
        if mod.enums:
            self.w("")

        # 1b) hàm tra TÊN biến thể cho mỗi enum (để in '{}' ra 'Red', không phải 0)
        for en in mod.enums:
            self.w(f"static const char* _g_enum_{self.cn(en.name)}_name"
                   f"({self.cn(en.name)} v) {{")
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
            self.w(f"typedef struct {self.cn(st.name)} {self.cn(st.name)};")
        slice_at = len(self.out)
        if mod.structs:
            self.w("")

        # 3) định nghĩa struct
        for st in mod.structs:
            bits = []
            if st.packed:
                bits.append("packed")
            if st.align:
                bits.append(f"aligned({st.align})")
            # Thuộc tính đặt SAU dấu '}' đóng struct. Đặt sau tên tag thì GCC
            # báo "expected identifier or '(' before '{'".
            attr = f" __attribute__(({', '.join(bits)}))" if bits else ""
            self.w(f"struct {self.cn(st.name)} {{")
            self.indent += 1
            for fname, fty in st.fields:
                self.w(self.c_decl(fty, self.cn(fname)) + ";")
            self.indent -= 1
            self.w("}" + attr + ";")
        if mod.structs:
            self.w("")

        # 3b) So sánh BẰNG theo từng trường cho mỗi struct (assert_eq/check_eq).
        #     Sinh theo đúng thứ tự khai báo trong module: struct lồng đã được
        #     irgen đặt trước struct chứa nó.
        for st in mod.structs:
            self.w(f"static bool _g_eq_{self.cn(st.name)}"
                   f"({self.cn(st.name)} _a, {self.cn(st.name)} _b) {{")
            self.indent += 1
            if not st.fields:
                self.w("(void)_a; (void)_b; return true;")
            else:
                conds = [self._field_eq(fty, f"_a.{self.cn(fn)}",
                                        f"_b.{self.cn(fn)}")
                         for fn, fty in st.fields]
                self.w("return " + " && ".join(conds) + ";")
            self.indent -= 1
            self.w("}")
        if mod.structs:
            self.w("")

        slice_print_at = len(self.out)

        # 4) global
        for g in mod.globals:
            self.gen_global(g)
        if mod.globals:
            self.w("")

        # 5) nguyên mẫu hàm. BỎ QUA 'extern fn' trùng tên hàm mà runtime/libc đã
        #    khai báo (strlen/memcpy/...): phát lại nguyên mẫu với chữ ký "gần
        #    đúng" của G gây 'conflicting types' ở C.
        for f in mod.funcs:
            if f.is_extern and self._runtime_provides(f.name):
                continue
            if f.name == "_g_init_globals":
                self.w("__attribute__((constructor)) " + self.signature(f) + ";")
                continue
            self.w(self.signature(f) + ";")
        self.w("")

        # 6) thân hàm
        for f in mod.funcs:
            if f.is_extern or not f.blocks:
                continue
            if f.name == "_g_init_globals":
                # Chạy TRƯỚC main để global có initializer động mang đúng giá trị.
                self.w("__attribute__((constructor))")
            self.gen_func(f)
            self.w("")

        if self.slice_print_decls:
            block = ["// In slice — độ dài biết lúc chạy nên cần hàm riêng."]
            block += self.slice_print_decls + [""]
            self.out[slice_print_at:slice_print_at] = block
        if self.slice_decls:
            block = ["// Slice: con trỏ béo { T* ptr; size_t len; }."]
            block += self.slice_decls + [""]
            self.out[slice_at:slice_at] = block
        if self.fnptr_decls:
            block = ["// Con trỏ hàm (typedef sinh tự động)."]
            block += self.fnptr_decls + [""]
            self.out[slice_at:slice_at] = block
        return "\n".join(self.out)

    # ------------------------------------------------------------------
    # kiểu
    # ------------------------------------------------------------------
    def slice_typedef(self, elem) -> str:
        elem_c = self.c_type(elem)
        nm = self.slice_typedefs.get(elem_c)
        if nm is None:
            nm = T.slice_c_name(elem)      # nguồn chân lý dùng chung
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
            return self._fnptr_typedef(ty)
        if ty.kind in ("struct", "enum"):
            if ty.name in T.BUILTIN_STRUCT_C:
                return T.BUILTIN_STRUCT_C[ty.name]
            return self.cn(ty.name)
        if ty.kind == "ptr":
            # Đệ quy để tên struct/enum bên trong CŨNG được đổi tên; T.c_type
            # không biết quy tắc đổi tên nên '*Default' ra 'default*' (từ khoá C).
            return self.c_type(ty.elem) + "*"
        return T.c_type(ty)

    def _fnptr_typedef(self, ty) -> str:
        """typedef con trỏ hàm cho kiểu 'fn(P...)->R'.

        Không dùng 'void*': C không gọi được qua void*, và ép kiểu tại mỗi lời
        gọi thì mất kiểm tra kiểu. Một typedef cho mỗi chữ ký."""
        params = [self.c_type(p) for p in (ty.params or ())]
        ret = self.c_type(ty.ret) if ty.ret is not None else "void"
        key = f"{ret}({','.join(params)})"
        nm = self.fnptr_typedefs.get(key)
        if nm is None:
            nm = f"_gfn{len(self.fnptr_typedefs)}"
            self.fnptr_typedefs[key] = nm
            plist = ", ".join(params) if params else "void"
            self.fnptr_decls.append(f"typedef {ret} (*{nm})({plist});")
        return nm

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
        ps = ", ".join(self.c_decl(p.type, self.cn(p.name))
                       for p in f.params) or "void"
        q = "extern " if f.is_extern else ""
        return f"{q}{self.c_type(f.ret)} {self.fn_name(f)}({ps})"

    # ------------------------------------------------------------------
    _PRINT_ARRAY_MAX = 8

    def _slice_print_fn(self, gt) -> str:
        """Hàm in cho 'slice<T>' — một hàm cho mỗi kiểu phần tử (độ dài chỉ biết
        lúc chạy nên không dựng được chuỗi định dạng tĩnh)."""
        sn = self.slice_typedef(gt.elem)
        fn = self.slice_print_fns.get(sn)
        if fn is not None:
            return fn
        fn = f"_gslprint_{sn}"
        self.slice_print_fns[sn] = fn
        el = gt.elem
        if el is not None and el.kind == "enum":
            frag, arg = "%s", f"_g_enum_{self.cn(el.name)}_name(s.ptr[i])"
        elif el is not None and el.kind == "bool":
            frag, arg = "%s", '(s.ptr[i] ? "true" : "false")'
        elif el is not None and el.kind == "struct":
            raise BackendError("in slice<struct> chưa hỗ trợ")
        else:
            spec, _ = T.printf_spec(el) if el is not None else ("%d", False)
            frag, arg = spec, "s.ptr[i]"
        cap = self._PRINT_ARRAY_MAX
        self.slice_print_decls += [
            f"static const char* {fn}({sn} s) {{",
            "    static char bufs[4][512]; static unsigned bi = 0;",
            "    char* b = bufs[bi++ & 3]; size_t off = 0;",
            '    off += (size_t)snprintf(b + off, sizeof(bufs[0]) - off, "[");',
            f"    size_t shown = s.len < {cap} ? s.len : {cap};",
            "    for (size_t i = 0; i < shown; i++) {",
            '        if (i) off += (size_t)snprintf(b + off, sizeof(bufs[0]) - off, ", ");',
            f'        off += (size_t)snprintf(b + off, sizeof(bufs[0]) - off, "{frag}", {arg});',
            "    }",
            "    if (shown < s.len)",
            "        off += (size_t)snprintf(b + off, sizeof(bufs[0]) - off,",
            '                                ", ... (%zu phần tử)", s.len);',
            '    snprintf(b + off, sizeof(bufs[0]) - off, "]");',
            "    return b;",
            "}",
        ]
        return fn

    def _field_eq(self, ty, l, r) -> str:
        """So sánh bằng MỘT trường (theo GType)."""
        if ty is None:
            return f"(({l}) == ({r}))"
        if ty.kind == "array":
            return f"(memcmp(&({l}), &({r}), sizeof({l})) == 0)"
        if ty.kind == "slice":
            return f"(({l}).ptr == ({r}).ptr && ({l}).len == ({r}).len)"
        if ty.kind == "struct":
            return f"_g_eq_{self.cn(ty.name)}({l}, {r})"
        if ty.kind == "str" or (ty.kind == "ptr" and ty.elem is not None
                                and ty.elem.kind == "char"):
            return f"g_str_eq({l}, {r})"
        return f"(({l}) == ({r}))"

    def gen_global(self, g: I.Global):
        if g.is_extern:
            self.w(f"extern {self.c_decl(g.type, self.cn(g.name))};")
            return
        init = ""
        if isinstance(g.init, list):
            init = " = { " + ", ".join(self.val(v) for v in g.init) + " }"
        elif g.init is not None:
            init = f" = {self.val(g.init)}"
        self.w(f"static {self.c_decl(g.type, self.cn(g.name))}{init};")

    # ------------------------------------------------------------------
    # giá trị
    # ------------------------------------------------------------------
    _tmp_n = 0

    def tmp(self, base="_gt"):
        CIRBackend._tmp_n += 1
        return f"{base}{CIRBackend._tmp_n}"

    _runtime_syms = None

    @classmethod
    def _runtime_provides(cls, name: str) -> bool:
        """Runtime C ('g_runtime.h') hay libc đã khai báo ký hiệu này chưa?

        Nếu rồi thì KHÔNG phát lại nguyên mẫu: chữ ký 'extern fn' của G chỉ gần
        đúng ('str' vs 'const char*', 'usize' vs 'size_t') nên phát lại sẽ gây
        'conflicting types'. Quét trực tiếp header runtime để danh sách không
        bao giờ lệch khỏi thực tế."""
        if cls._runtime_syms is None:
            import os
            import re as _re
            from .codegen import _RUNTIME_DEFINED
            syms = set(_RUNTIME_DEFINED)
            hdr = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "runtime", "g_runtime.h")
            try:
                with open(hdr, encoding="utf-8") as fh:
                    src = fh.read()
                syms |= set(_re.findall(
                    r"^\s*(?:_Noreturn\s+)?static\s+inline\s+[^\n(]*?"
                    r"\b([A-Za-z_][A-Za-z_0-9]*)\s*\(", src, _re.M))
                syms |= set(_re.findall(r"^#define\s+([A-Za-z_][A-Za-z_0-9]*)\s*\(",
                                        src, _re.M))
            except OSError:
                pass
            cls._runtime_syms = syms
        return name in cls._runtime_syms

    def fn_name(self, f: I.Func) -> str:
        """Tên C của một hàm. 'main' và ký hiệu 'extern' GIỮ NGUYÊN tên (điểm
        vào của chương trình / ký hiệu do nơi khác định nghĩa) — đổi tên chúng
        sẽ làm hỏng liên kết."""
        if f.name == "main" or f.is_extern:
            return f.name
        return self.cn(f.name)

    @staticmethod
    def cn(name: str) -> str:
        """Tên C an toàn: từ khoá C / ký hiệu libc-libm được đổi tên.

        Dùng CHÍNH hàm của checker để hai backend đặt tên giống hệt nhau —
        nếu không, 'fn strlen()' của người dùng sẽ va vào <string.h>."""
        from .checker import Checker
        return Checker.safe_c_name(name)

    def val(self, v: I.Value) -> str:
        if not isinstance(v, I.Value):
            raise BackendError(f"toán hạng không phải Value: {v!r}")
        if v.kind == "temp":
            # Tham số xuất hiện trong IR dưới dạng temp cùng tên; khai báo của
            # chúng đã được đổi tên (cn) nên chỗ dùng phải khớp — nếu không,
            # 'round' sẽ trỏ vào round() của <math.h> thay vì tham số.
            if v.name in self._param_names:
                return self.cn(v.name)
            return v.name
        if v.kind == "global":
            # IR coi global là một CON TRỎ tới ô nhớ ('@x : *T'), còn trong C tên
            # global CHÍNH LÀ ô nhớ. Lấy địa chỉ để hai mô hình khớp nhau: khi đó
            # 'load @x' thành '*(&x)' — hợp lệ và trình biên dịch C rút gọn ngay.
            # Với mảng, '&arr' đúng kiểu 'T(*)[N]' như IR mô tả.
            return f"(&{self.cn(v.name)})"
        if v.kind == "func":
            return self.cn(v.name) if v.name in self._user_fns else v.name
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
        self._param_names = {p.name for p in f.params}
        # Vị trí trong thông điệp panic phải là 'file:dòng:cột' — GIỐNG backend
        # cũ, nếu không hai backend cho thông điệp khác nhau.
        src = f.src_file or getattr(self, "_cur_src", None)
        if src:
            self._cur_src = src
        self._arena_decls = []
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
        arena_at = len(self.out)
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
        if self._arena_decls:
            self.out[arena_at:arena_at] = [f"    GArena {v};"
                                           for v in self._arena_decls]
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

        if op == "mod" and ins.type is not None and ins.type.kind == "float":
            # C cấm '%' trên double -> fmod (giống backend cũ).
            self.w(f"{d} = fmod({a[0]}, {a[1]});")
            return
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
            pt = ins.args[0].type
            if (pt is not None and pt.kind == "ptr" and pt.elem is not None
                    and pt.elem.kind == "array"
                    and isinstance(pt.elem.n, int)):
                # C không cho gán CẢ MẢNG bằng '=' -> sao chép byte. Chỉ áp dụng
                # cho mảng CỠ TĨNH; '[]T' là con trỏ trần (sizeof sai, memcpy
                # vào nó = ghi qua con trỏ chưa khởi tạo).
                self.w(f"memcpy(*({a[0]}), {a[1]}, sizeof(*({a[0]})));")
            else:
                self.w(f"*({a[0]}) = {a[1]};")
        elif op == "memcpy":
            self.w(f"memcpy({a[0]}, {a[1]}, sizeof(*({a[0]})));")
        elif op == "elemaddr":
            if ins.extra.get("on") == "slice":
                self.w(f"{d} = &(({a[0]}).ptr[{a[1]}]);")
            else:
                bt = ins.args[0].type
                # Cơ sở là CON TRỎ TỚI MẢNG ('*[N]T') -> phải deref trước rồi
                # mới index. Cơ sở là con trỏ THƯỜNG ('*T', mảng động từ
                # g_alloc) -> index thẳng; deref sẽ cho ra T (không index được).
                if (bt is not None and bt.kind == "ptr" and bt.elem is not None
                        and bt.elem.kind == "array"):
                    self.w(f"{d} = &((*({a[0]}))[{a[1]}]);")
                else:
                    self.w(f"{d} = &(({a[0]})[{a[1]}]);")
        elif op == "fieldaddr":
            fld = self.cn(ins.extra.get("field") or ins.args[1].const)
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
            if callee and callee in self._user_fns:
                callee = self.cn(callee)
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
            lines = [l.strip() for l in (ins.extra.get("template") or "").split("\n")
                     if l.strip()]
            tpl = "\\n\\t".join(lines)
            if not ins.extra.get("extended"):
                self.w(f'__asm__ __volatile__("{tpl}");')
                return
            cons = ins.extra.get("constraints") or []
            n_out = ins.extra.get("n_out", 0)
            # Output là ĐỊA CHỈ trong IR -> deref để asm ghi vào ô nhớ.
            outs = ", ".join(f'"{cons[i]}" (*({a[i]}))' for i in range(n_out))
            ins_s = ", ".join(f'"{cons[i]}" ({a[i]})'
                              for i in range(n_out, len(a)))
            clob = ", ".join(f'"{c}"' for c in (ins.extra.get("clobbers") or []))
            self.w(f'__asm__ __volatile__("{tpl}" : {outs} : {ins_s} : {clob});')
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

    def gen_cmp_builtin(self, ins: I.Instr, a, d, name):
        """assert_*/check_* — irgen đã tính sẵn: [ok, tên, fmt_trái, fmt_phải,
        <đối số trái...>, <đối số phải...>]."""
        is_check = bool(ins.extra.get("is_check"))
        line = ins.extra.get("line", 0)
        nl = ins.extra.get("nleft", 0)
        ok, nm = a[0], a[1]
        lfmt_v, rfmt_v = ins.args[2].const, ins.args[3].const
        largs = a[4:4 + nl]
        rargs = a[4 + nl:]
        lt = (", " + ", ".join(largs)) if largs else ""
        rt = (", " + ", ".join(rargs)) if rargs else ""
        red = 'g_tcolor("\033[1;31m")'
        grn = 'g_tcolor("\033[32m")'
        rst = 'g_tcolor("\033[0m")'
        # Thụt lề 4 dấu cách — KHỚP CHÍNH XÁC backend cũ (xem Codegen.gen_assert_cmp);
        # so khớp đầu ra hai backend là theo từng byte.
        fail_fmt = self.c_string(
            "%s\u2717 %s (dòng " + str(line) + ")%s\n    trái:  "
            + lfmt_v + "\n    phải:  " + rfmt_v + "\n")
        if is_check:
            ok_fmt = self.c_string("%s\u2713 %s%s\n")
            self.w(f"{d} = {ok};")
            self.w(f"g_test_record({d});")
            self.w(f"if ({d}) fprintf(stderr, {ok_fmt}, {grn}, {nm}, {rst});")
            self.w(f"else fprintf(stderr, {fail_fmt}, {red}, {nm}, {rst}"
                   f"{lt}{rt});")
        else:
            self.w(f"if (!({ok})) {{")
            self.indent += 1
            self.w(f"fprintf(stderr, {fail_fmt}, {red}, {nm}, {rst}{lt}{rt});")
            self.w("exit(101);")
            self.indent -= 1
            self.w("}")

    def _where(self, ins) -> str:
        f = getattr(self, "_cur_src", None) or "?"
        f = f.replace("\\", "/").split("/")[-1]
        return self.c_string(f"{f}:{ins.line}:{ins.col}")

    def gen_alloc_intrinsic(self, ins: I.Instr, a, d, name):
        """alloc/free/realloc qua bảng hàm allocator (xem GAllocator)."""
        if name == "heap_allocator":
            self.w(f"{d} = g_heap_allocator();")
            return
        if name == "arena_allocator":
            # Arena giữ TRẠNG THÁI (offset) nên cần một GArena sống trong hàm.
            av = self.tmp("_gar")
            self._arena_decls.append(av)
            self.w(f"{av} = (GArena){{ (unsigned char*)({a[0]}).ptr, "
                   f"({a[0]}).len, 0 }};")
            self.w(f"{d} = g_arena_allocator(&{av});")
            return
        with_alloc = bool(ins.extra.get("with_alloc"))
        al = a[0] if with_alloc else "g_heap_allocator()"
        rest = a[1:] if with_alloc else a
        if name == "free":
            self.w(f"g_a_free({al}, (void*)({rest[0]}));")
            return
        esz = ins.extra.get("elem_size", 1)
        ct = self.c_type(ins.type)
        if name == "alloc":
            self.w(f"{d} = ({ct})g_a_alloc({al}, (size_t)({rest[0]}), {esz});")
        else:
            self.w(f"{d} = ({ct})g_a_realloc({al}, (void*)({rest[0]}), "
                   f"(size_t)({rest[1]}), {esz});")

    def gen_check(self, ins: I.Instr, a):
        kind = ins.extra.get("kind")
        where = self._where(ins)
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
            bt = ins.args[0].type
            # Cơ sở là CON TRỎ TỚI MẢNG ('*[N]T'): '+ lo' trên nó nhảy theo CẢ
            # MẢNG, không phải theo phần tử. Phải phân rã về 'T*' trước, nếu
            # không slice trỏ ra ngoài vùng nhớ (đọc rác).
            cap = ins.extra.get("cap")
            if (bt is not None and bt.kind == "ptr" and bt.elem is not None
                    and bt.elem.kind == "array"):
                base = f"(*({base}))"
                if cap is None and isinstance(bt.elem.n, int):
                    cap = str(bt.elem.n)
            elif bt is not None and bt.kind == "slice":
                # Cắt lát của một SLICE: cộng vào con trỏ bên trong, không phải
                # vào cả struct (ptr+len).
                cap = f"({base}).len"
                base = f"({base}).ptr"
            # KẸP biên như g_sslice: chỉ số ngoài vùng cho slice RỖNG chứ không
            # trỏ ra ngoài bộ nhớ gốc.
            lo_v, hi_v = self.tmp("_gsl"), self.tmp("_gsh")
            self.w(f"long long {lo_v} = (long long)({lo});")
            self.w(f"long long {hi_v} = (long long)({hi});")
            self.w(f"if ({lo_v} < 0) {lo_v} = 0;")
            if cap is not None:
                self.w(f"if ({hi_v} > (long long)({cap})) "
                       f"{hi_v} = (long long)({cap});")
                self.w(f"if ({lo_v} > (long long)({cap})) "
                       f"{lo_v} = (long long)({cap});")
            self.w(f"if ({hi_v} < {lo_v}) {hi_v} = {lo_v};")
            self.w(f"{d} = ({sn}){{ ({base}) + {lo_v}, "
                   f"(size_t)({hi_v} - {lo_v}) }};")
            return
        if name in ("alloc", "realloc", "free", "heap_allocator",
                    "arena_allocator"):
            self.gen_alloc_intrinsic(ins, a, d, name)
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
        if name == "format":
            # Đo độ dài bằng snprintf(NULL,0,...) rồi cấp phát vừa khít — giống
            # backend cũ. Đối số đã được vật hoá trong IR nên chỉ đánh giá 1 lần.
            args = ", ".join(a)
            n = self.tmp("_gfn")
            self.w(f"int {n} = snprintf(NULL, 0, {args});")
            self.w(f"{d} = (const char*)malloc((size_t){n} + 1);")
            self.w(f"snprintf((char*){d}, (size_t){n} + 1, {args});")
            return
        if name in _OS_SIMPLE:
            args = list(a)
            if name in ("inb", "inw", "inl") and args:
                args[0] = f"(uint16_t)({args[0]})"
            elif name in ("outb", "outw", "outl") and len(args) == 2:
                w = {"outb": "uint8_t", "outw": "uint16_t",
                     "outl": "uint32_t"}[name]
                args = [f"(uint16_t)({args[0]})", f"({w})({args[1]})"]
            call = f"g_{name}({', '.join(args)})"
            self.w(f"{d} = {call};" if d else f"{call};")
            return
        if name in ("popcount", "clz", "ctz", "bswap", "rotl", "rotr"):
            bits = ins.extra.get("bits", 32)
            w64 = bits > 32
            if name == "popcount":
                fn = "__builtin_popcountll" if w64 else "__builtin_popcount"
                self.w(f"{d} = (int){fn}((unsigned long long)({a[0]}));")
            elif name in ("clz", "ctz"):
                # clz/ctz KHÔNG xác định với 0 trong C -> trả bề rộng kiểu.
                # CHỈ 'clz' cần trừ phần bù khi kiểu hẹp hơn ô mà builtin dùng
                # (đếm số 0 dẫn ĐẦU); 'ctz' đếm từ bit thấp nên không đổi.
                b = "ll" if w64 else ""
                fn = f"__builtin_{'clz' if name == 'clz' else 'ctz'}{b}"
                cast = "unsigned long long" if w64 else "unsigned"
                expr = f"(int){fn}(({cast})({a[0]}))"
                if name == "clz":
                    host = 64 if w64 else 32
                    if bits < host:
                        expr += f" - {host - bits}"
                self.w(f"{d} = (({a[0]}) == 0) ? {bits} : {expr};")
            elif name == "bswap":
                fn = {8: None, 16: "__builtin_bswap16",
                      32: "__builtin_bswap32"}.get(bits, "__builtin_bswap64")
                if fn is None:
                    self.w(f"{d} = {a[0]};")
                else:
                    self.w(f"{d} = ({self.c_type(ins.type)}){fn}({a[0]});")
            else:
                # Xoay bit theo ĐÚNG bề rộng kiểu (u8 xoay trong 8 bit) — nội
                # tuyến như backend cũ; runtime chỉ có bản 64-bit.
                ut = {8: "uint8_t", 16: "uint16_t",
                      32: "uint32_t"}.get(bits, "uint64_t")
                v, nn = self.tmp("_grv"), self.tmp("_grn")
                main = "<<" if name == "rotl" else ">>"
                back = ">>" if name == "rotl" else "<<"
                self.w(f"{ut} {v} = ({ut})({a[0]});")
                self.w(f"unsigned {nn} = (unsigned)({a[1]}) & {bits - 1}u;")
                self.w(f"{d} = ({self.c_type(ins.type)})({nn} ? "
                       f"(({v} {main} {nn}) | ({v} {back} ({bits} - {nn}))) "
                       f": {v});")
            return
        if name == "str_at_checked":
            self.w(f"{d} = g_str_at_c({a[0]}, {a[1]}, {self._where(ins)});")
            return
        if name in ("dl_open", "dl_sym", "dl_close", "dl_error"):
            call = f"g_{name}({', '.join(a)})"
            self.w(f"{d} = {call};" if d else f"{call};")
            return
        if name == "slice_ptr":
            self.w(f"{d} = ({a[0]}).ptr;")
            return
        if name == "print_slice":
            self.w(f"{d} = {self._slice_print_fn(ins.args[0].type)}({a[0]});")
            return
        if name == "test_summary":
            self.w(f"{d} = g_test_summary();")
            return
        if name in ("panic", "unreachable", "todo"):
            msg = a[0] if a else '"' + name + '"'
            self.w(f"g_{name}({msg});")
            return
        if name in _CMP_BUILTINS:
            self.gen_cmp_builtin(ins, a, d, name)
            return
        if name in ("sizeof", "alignof"):
            raise BackendError(
                f"{name} chưa gấp được thành hằng cho kiểu này")
        raise BackendError(
            f"intrinsic '{name}' chưa được hạ chi tiết trong IR nên backend "
            f"c-ir chưa sinh mã được (xem irgen.py: các built-in in ấn/format "
            f"vẫn giữ ở dạng intrinsic)")


register(CIRBackend)
