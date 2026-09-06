"""
G Language - Code Generator: dịch AST (đã gắn kiểu) sang mã C.

Nơi 5 ngôn ngữ hội tụ:
  - Frontend Rust/Zig (let/mut, match, defer, comptime, loop)
  - Backend C/C++ (mọi thứ -> C -> mã máy)
  - ASM (inline assembly)
Tận dụng thông tin kiểu để: print tự chọn định dạng, auto-deref con trỏ, gọi method.
"""

import dataclasses
import re
from . import ast_nodes as A
from .checker import Checker
from . import types as T

# Hàm mà runtime freestanding (g_runtime.h) TỰ định nghĩa — và libc hosted cũng
# có. 'extern fn' trùng tên chúng không được phát nguyên mẫu (xem generate()).
_RUNTIME_DEFINED = {"memcpy", "memmove", "memset", "memcmp", "strlen"}


# Ánh xạ tên kiểu G -> C (cho khai báo theo cú pháp)
TYPE_MAP = {
    "int": "int", "i8": "int8_t", "i16": "int16_t", "i32": "int32_t", "i64": "int64_t",
    "u8": "uint8_t", "u16": "uint16_t", "u32": "uint32_t", "u64": "uint64_t",
    "usize": "size_t", "isize": "ptrdiff_t",
    "f32": "float", "f64": "double", "float": "float", "double": "double",
    "bool": "bool", "char": "char", "void": "void", "str": "const char*",
}


class CodegenError(Exception):
    pass


class Codegen:
    def __init__(self, program: A.Program):
        self.prog = program
        self.out = []
        self.indent = 0
        self.struct_names = set()
        self.struct_defs = {}        # tên struct -> StructDef (cho print/dbg bung struct)
        self.enum_names = set()
        self.enum_variants = set()   # mọi tên variant (là hằng số C hợp lệ)
        self.global_inits = []       # (tên, biểu_thức) cho global khởi tạo lúc chạy
        self.scope_stack = []   # ngăn xếp scope cho defer (LIFO, theo block)
        self._tmp = 0
        self.slice_print_fns = {}    # tên typedef slice -> tên hàm in
        self.slice_print_decls = []  # thân các hàm in slice
        self.slice_typedefs = {}     # kiểu phần tử C -> tên typedef slice
        self.slice_decls = []        # các dòng 'G_SLICE_DEF(T, GSlice_T);'
        self.fnptr_typedefs = {}     # khoá chữ ký C -> tên typedef con trỏ hàm
        self.fnptr_decls = []        # các dòng 'typedef R (*_gfnN)(...);' theo thứ tự

    # ---------- tiện ích ----------
    @staticmethod
    def cn(name: str) -> str:
        """Tên C an toàn cho một định danh do người dùng đặt (struct/enum/biến
        thể/trường/hàm/tham số): từ khoá C và tên libc được thêm hậu tố '_g'."""
        return Checker.safe_c_name(name)

    def w(self, line=""):
        self.out.append("    " * self.indent + line)

    def tmp(self, base="_g"):
        self._tmp += 1
        return f"{base}{self._tmp}"

    def c_type(self, t: A.Type) -> str:
        """Kiểu cơ sở (gồm con trỏ ngoài + con trỏ phần tử), KHÔNG gồm phần chiều
        mảng. Kiểu hàm -> tên typedef con trỏ hàm (đã đăng ký).
        LƯU Ý: với kiểu có chiều mảng VÀ con trỏ ngoài ('*[N]T'), hãy dùng c_decl/
        _ctype_str — hàm này chỉ đúng cho kiểu không có chiều mảng."""
        return self._c_base(t) + "*" * t.ptr

    def _c_base(self, t: A.Type) -> str:
        """Kiểu C của PHẦN TỬ trong cùng: tên kiểu + con trỏ-phần-tử ([N]*T)."""
        if getattr(t, "slice_elem", None) is not None:
            base = self._slice_typedef_ast(t)
        elif getattr(t, "is_fn", False):
            base = self._fnptr_typedef(t)
        else:
            base = TYPE_MAP.get(t.name) or self.cn(t.name)
        return base + "*" * getattr(t, "elem_ptr", 0)

    def _slice_typedef_ast(self, t: A.Type) -> str:
        """Đăng ký typedef slice cho một A.Type 'slice<T>'."""
        elem_c = self._ctype_str(t.slice_elem)
        return self._slice_typedef(elem_c)

    def _slice_typedef(self, elem_c: str) -> str:
        """Đăng ký (nếu chưa có) 'typedef struct { T* ptr; size_t len; }' cho
        kiểu phần tử C này, trả về tên typedef. C không có generic nên mỗi kiểu
        phần tử cần một struct riêng."""
        name = self.slice_typedefs.get(elem_c)
        if name is None:
            ident = (elem_c.replace("*", "p").replace(" ", "_")
                     .replace("const_charp", "str"))
            name = f"GSlice_{ident}"
            self.slice_typedefs[elem_c] = name
            self.slice_decls.append(f"G_SLICE_DEF({elem_c}, {name});")
        return name

    def _slice_typedef_gt(self, gt) -> str:
        """Như trên nhưng nhận GType (dùng ở phía biểu thức)."""
        return self._slice_typedef(T.c_type(gt.elem))

    def _ctype_str(self, t) -> str:
        """Chuỗi kiểu C ĐẦY ĐỦ cho ngữ cảnh kiểu trừu tượng (tham số typedef, cast):
        mảng phân rã thành con trỏ; con trỏ tới mảng tĩnh giữ đúng dạng
        'T (*)[N]'; kiểu hàm -> tên typedef con trỏ hàm."""
        if t is None:
            return "void"
        return self._declarator(t, "", const=False, decay_first=True)

    def _declarator(self, t: A.Type, name: str, const: bool, decay_first: bool) -> str:
        """Dựng khai báo C 'kiểu + declarator' cho 'name' (name rỗng -> kiểu trừu
        tượng). Quy tắc:
          [N]T          -> T name[N]
          []T / tham số -> T* name           (chiều ngoài phân rã)
          *[N]T         -> T (*name)[N]      (con trỏ tới mảng — KHÔNG phải T**)
          [N]*T         -> T* name[N]        (mảng các con trỏ)
        'const' đặt east-const (ngay trước tên) để bất biến áp lên CHÍNH biến:
        'int* const p' (con trỏ bất biến, '*p' vẫn ghi được)."""
        base = self._c_base(t)
        cq = "const " if const else ""
        dims = self._dims(t)
        outer = t.ptr
        # Tham số/kiểu trừu tượng: chiều ngoài cùng của MẢNG (không phải con trỏ
        # tới mảng) phân rã thành con trỏ theo quy tắc C.
        if decay_first and dims and outer == 0:
            dims = ["dyn"] + dims[1:]
        nptr = 0
        while dims and dims[0] == "dyn":
            nptr += 1
            dims = dims[1:]
        if any(d == "dyn" for d in dims):
            # Chiều động xen giữa: phân rã toàn bộ thành con trỏ (mất kích thước tĩnh).
            stars = "*" * (outer + nptr + len(dims))
            return f"{base}{stars} {cq}{name}".rstrip()
        arr = "".join(f"[{d}]" for d in dims)
        stars = "*" * (outer + nptr)
        if stars and arr:
            return f"{base} ({stars}{cq}{name}){arr}"
        if stars:
            return f"{base}{stars} {cq}{name}".rstrip()
        if arr:
            return f"{base} {cq}{name}{arr}"
        return f"{base} {cq}{name}".rstrip()

    def _fnptr_typedef(self, t) -> str:
        """Đăng ký (nếu chưa có) một typedef con trỏ hàm cho kiểu hàm 't', trả về
        tên typedef. Dùng typedef giúp mọi nơi (biến/tham số/trường/trả về/mảng)
        chỉ cần một tên kiểu C đơn giản — tránh cú pháp khai báo con trỏ hàm rối."""
        params = [self._ctype_str(p) for p in (t.fn_params or [])]
        ret = self._ctype_str(t.fn_ret)
        key = f"{ret}({','.join(params)})"
        name = self.fnptr_typedefs.get(key)
        if name is None:
            name = f"_gfn{len(self.fnptr_typedefs)}"
            self.fnptr_typedefs[key] = name
            plist = ", ".join(params) if params else "void"
            self.fnptr_decls.append(f"typedef {ret} (*{name})({plist});")
        return name

    def _dims(self, t: A.Type) -> list:
        """Chuẩn hóa danh sách chiều mảng từ A.Type (gộp dims/array)."""
        if t.dims is not None:
            return list(t.dims)
        if t.array is not None:
            return [t.array]
        return []

    def c_decl(self, name, t: A.Type, init_c=None, const=False, decay_first=False):
        """Sinh khai báo C đầy đủ cho biến/trường/tham số, xử lý mảng nhiều chiều
        và con trỏ tới mảng. decay_first=True: chiều ngoài cùng phân rã thành con
        trỏ (quy tắc tham số C). Xem _declarator."""
        decl = self._declarator(t, name, const=const, decay_first=decay_first)
        if init_c is not None:
            decl += f" = {init_c}"
        return decl

    def c_param_type(self, t: A.Type) -> str:
        # (giữ cho tương thích) — kiểu tham số đơn giản, mảng phân rã thành con trỏ.
        base = self.c_type(t)
        dims = self._dims(t)
        if dims:
            base += "*" * len(dims)
        return base

    def _has_call(self, e) -> bool:
        """Biểu thức có chứa lời gọi hàm/method (tác dụng phụ)? — quyết định
        có cần dùng statement-expression để tránh đánh giá hai lần hay không."""
        if isinstance(e, A.Call):
            return True
        if isinstance(e, A.Binary):
            return self._has_call(e.left) or self._has_call(e.right)
        if isinstance(e, A.Unary):
            return self._has_call(e.operand)
        if isinstance(e, A.Ternary):
            return any(self._has_call(x) for x in (e.cond, e.then, e.els))
        if isinstance(e, A.Index):
            return self._has_call(e.base) or self._has_call(e.index)
        if isinstance(e, A.FieldAccess):
            return self._has_call(e.base)
        if isinstance(e, A.Cast):
            return self._has_call(e.expr)
        if isinstance(e, A.SizeOfExpr):
            return self._has_call(e.expr)
        if isinstance(e, A.ArrayLit):
            return any(self._has_call(x) for x in e.elements)
        if isinstance(e, A.StructLit):
            return any(self._has_call(v) for _, v in e.fields)
        return False

    def _args_need_ordering(self, nodes) -> bool:
        """Có cần ép thứ tự đánh giá TRÁI-SANG-PHẢI cho danh sách biểu thức này
        không? C KHÔNG quy định thứ tự đánh giá đối số hàm (thường phải-sang-trái),
        nên 'f(next(), next())' có thể chạy ngược trực giác. Cần ép thứ tự khi có
        >=2 mục và ÍT NHẤT một mục có tác dụng phụ (lời gọi) — lúc đó một mục có
        thể quan sát tác dụng của mục khác."""
        return len(nodes) >= 2 and any(self._has_call(n) for n in nodes)

    def _is_const_expr(self, e) -> bool:
        """Biểu thức là hằng số nguyên đã biết (checker có thể đã gấp)? Dùng để
        bỏ kiểm tra lúc chạy cho chỉ số/mẫu số hằng (checker đã kiểm tĩnh)."""
        if getattr(e, "const_value", None) is not None:
            return True
        if isinstance(e, (A.IntLit, A.CharLit, A.BoolLit, A.SizeOf)):
            return True
        if isinstance(e, A.Ident):
            return e.name in self.enum_variants or getattr(e, "is_enum_variant", False) \
                or e.name in getattr(self, "const_names", set())
        if isinstance(e, A.Unary) and e.op in ("-", "~"):
            return self._is_const_expr(e.operand)
        if isinstance(e, A.Binary):
            return self._is_const_expr(e.left) and self._is_const_expr(e.right)
        if isinstance(e, A.Cast):
            return self._is_const_expr(e.expr)
        return False

    def _is_const_init(self, e) -> bool:
        """Biểu thức có dùng được làm initializer tĩnh trong C không (hằng số
        biên dịch)? Literal, enum variant, sizeof, ép kiểu/toán tử trên hằng,
        '&' của biến toàn cục... là hằng. Tham chiếu biến/global khác hoặc lời
        gọi hàm thì KHÔNG (C cấm 'initializer element is not constant')."""
        if isinstance(e, (A.IntLit, A.FloatLit, A.StrLit, A.CharLit, A.BoolLit,
                          A.NullLit, A.SizeOf)):
            return True
        if isinstance(e, A.Ident):
            # chỉ enum variant là hằng; biến/global khác thì không
            return e.name in self.enum_variants
        if isinstance(e, A.Unary):
            return self._is_const_init(e.operand)
        if isinstance(e, A.Binary):
            return self._is_const_init(e.left) and self._is_const_init(e.right)
        if isinstance(e, A.Ternary):
            return all(self._is_const_init(x) for x in (e.cond, e.then, e.els))
        if isinstance(e, A.Cast):
            return self._is_const_init(e.expr)
        if isinstance(e, A.ArrayLit):
            return all(self._is_const_init(x) for x in e.elements)
        if isinstance(e, A.StructLit):
            return all(self._is_const_init(v) for _, v in e.fields)
        if isinstance(e, A.SizeOfExpr):
            return True
        return False

    def gtype_of(self, e) -> T.GType:
        return getattr(e, "gtype", T.UNKNOWN)

    # ---------- thuộc tính @ -> __attribute__ của GCC/Clang ----------
    def _gnu_attrs(self, attrs):
        """Trả về (quals, attr_str): 'quals' là từ khoá đứng trước khai báo (vd
        'inline'); 'attr_str' là '__attribute__((...))' (hoặc rỗng). Checker đã
        kiểm hợp lệ nên ở đây chỉ dịch."""
        if not attrs:
            return "", ""
        parts = []
        quals = []
        for a in attrs:
            n = a.name
            if n == "packed":
                parts.append("packed")
            elif n in ("align", "aligned"):
                parts.append(f"aligned({self.gen_expr(a.args[0])})")
            elif n == "naked":
                parts.append("naked")
            elif n == "noreturn":
                parts.append("noreturn")
            elif n == "interrupt":
                parts.append("interrupt")
            elif n == "used":
                parts.append("used")
            elif n == "section":
                parts.append(f"section({self.gen_expr(a.args[0])})")
            elif n == "inline":
                quals.append("inline")
                parts.append("always_inline")
        attr = f"__attribute__(({', '.join(parts)}))" if parts else ""
        return " ".join(quals), attr

    # ---------- intrinsics phát triển hệ điều hành ----------
    # Ánh xạ intrinsic CPU/thời gian không-toán-hạng -> hàm runtime.
    _OS_CALL_MAP = {
        "halt": "g_hlt", "cli": "g_cli", "sti": "g_sti", "pause": "g_pause",
        "breakpoint": "g_breakpoint", "io_wait": "g_io_wait", "rdtsc": "g_rdtsc",
        # nullary: đọc control register & quản lý cache (không toán hạng)
        "read_cr0": "g_read_cr0", "read_cr2": "g_read_cr2",
        "read_cr3": "g_read_cr3", "read_cr4": "g_read_cr4", "wbinvd": "g_wbinvd",
    }
    _OS_BUILTINS = ({"memcpy", "memset", "memmove", "memcmp", "vol_read",
                     "vol_write", "popcount", "clz", "ctz", "bswap", "rotl",
                     "rotr", "inb", "outb", "inw", "outw", "inl", "outl",
                     "static_assert", "write_cr0", "write_cr3", "write_cr4",
                     "invlpg", "rdmsr", "wrmsr"} | set(_OS_CALL_MAP))

    @staticmethod
    def _int_width(gt) -> int:
        """Bề rộng (bit) của một kiểu nguyên đã suy luận; 64 nếu không rõ."""
        return gt.bits if (gt is not None and gt.kind == "int" and gt.bits) else 64

    @staticmethod
    def _uctype(w) -> str:
        return {8: "uint8_t", 16: "uint16_t", 32: "uint32_t",
                64: "uint64_t"}.get(w, "uint64_t")

    @staticmethod
    def _wmask(w) -> str:
        return "~0ULL" if w >= 64 else f"((1ULL << {w}) - 1)"

    def _gen_os_call(self, e: A.Call, name) -> str:
        """Sinh C cho một intrinsic phát triển hệ điều hành (xem BUILTINS trong
        checker). Các phép theo-bề-rộng (clz/ctz/bswap/rotl/rotr) tôn trọng đúng
        bề rộng kiểu của đối số (giống Rust u8/u32/...); đối số được vật hoá nên
        đánh giá đúng MỘT lần."""
        if name in self._OS_CALL_MAP:                       # halt/cli/sti/.../rdtsc
            return f"{self._OS_CALL_MAP[name]}()"
        if name in ("memcpy", "memmove", "memset", "memcmp"):
            return f"{name}({', '.join(self.gen_expr(a) for a in e.args)})"
        if name in ("vol_read", "vol_write"):
            pt = self.gtype_of(e.args[0])
            elem = pt.elem if pt.kind == "ptr" and pt.elem is not None else None
            ct = T.c_type(elem) if elem is not None and elem.kind != "unknown" else "uint64_t"
            ptr_c = self.gen_expr(e.args[0])
            if name == "vol_read":
                return f"(*(volatile {ct}*)({ptr_c}))"
            return f"(*(volatile {ct}*)({ptr_c}) = ({self.gen_expr(e.args[1])}))"
        if name == "popcount":
            return f"g_popcount((uint64_t)({self.gen_expr(e.args[0])}))"
        if name in ("clz", "ctz"):
            w = self._int_width(self.gtype_of(e.args[0]))
            v = self.tmp("_gbit")
            body = f"uint64_t {v} = (uint64_t)({self.gen_expr(e.args[0])}) & {self._wmask(w)};"
            if name == "clz":
                return f"({{ {body} {v} ? (__builtin_clzll({v}) - {64 - w}) : {w}; }})"
            return f"({{ {body} {v} ? __builtin_ctzll({v}) : {w}; }})"
        if name == "bswap":
            gt = self.gtype_of(e.args[0])
            w = self._int_width(gt)
            ct = T.c_type(gt) if gt.kind == "int" else "uint64_t"
            xc = self.gen_expr(e.args[0])
            if w <= 8:
                return f"({ct})({xc})"
            fn = "g_bswap16" if w <= 16 else ("g_bswap32" if w <= 32 else "g_bswap64")
            ut = "uint16_t" if w <= 16 else ("uint32_t" if w <= 32 else "uint64_t")
            return f"({ct})({fn}(({ut})({xc})))"
        if name in ("rotl", "rotr"):
            gt = self.gtype_of(e.args[0])
            w = self._int_width(gt)
            ct = T.c_type(gt) if gt.kind == "int" else "uint64_t"
            ut = self._uctype(w)
            v, nn = self.tmp("_grv"), self.tmp("_grn")
            main = "<<" if name == "rotl" else ">>"
            back = ">>" if name == "rotl" else "<<"
            return (f"({{ {ut} {v} = ({ut})({self.gen_expr(e.args[0])}); "
                    f"unsigned {nn} = (unsigned)({self.gen_expr(e.args[1])}) & {w - 1}u; "
                    f"({ct})({nn} ? (({v} {main} {nn}) | "
                    f"({v} {back} ({w} - {nn}))) : {v}); }})")
        if name in ("inb", "inw", "inl"):
            return f"g_{name}((uint16_t)({self.gen_expr(e.args[0])}))"
        if name in ("outb", "outw", "outl"):
            vt = {"outb": "uint8_t", "outw": "uint16_t", "outl": "uint32_t"}[name]
            return (f"g_{name}((uint16_t)({self.gen_expr(e.args[0])}), "
                    f"({vt})({self.gen_expr(e.args[1])}))")
        if name == "static_assert":
            # Checker đã gấp điều kiện (và báo lỗi nếu sai/không hằng); C không coi
            # 'const int' là hằng nên phát thẳng giá trị đã gấp.
            cv = getattr(e, "const_value", None)
            cond = self.gen_expr(e.args[0]) if cv is None else ("1" if cv else "0")
            msg = self.gen_expr(e.args[1]) if len(e.args) == 2 else '"static_assert"'
            return f"_Static_assert(({cond}), {msg})"
        if name in ("write_cr0", "write_cr3", "write_cr4"):
            return f"g_{name}((uint64_t)({self.gen_expr(e.args[0])}))"
        if name == "invlpg":
            return f"g_invlpg((void*)(uintptr_t)({self.gen_expr(e.args[0])}))"
        if name == "rdmsr":
            return f"g_rdmsr((uint32_t)({self.gen_expr(e.args[0])}))"
        if name == "wrmsr":
            return (f"g_wrmsr((uint32_t)({self.gen_expr(e.args[0])}), "
                    f"(uint64_t)({self.gen_expr(e.args[1])}))")
        raise CodegenError(f"intrinsic OS chưa hỗ trợ: {name}")

    def _is_array_decl(self, st) -> bool:
        """Khai báo 'let' này có kiểu MẢNG (theo chú thích hoặc theo giá trị)?"""
        if getattr(st, "type", None) is not None and self._dims(st.type):
            return True
        if isinstance(getattr(st, "value", None), A.ArrayLit):
            return True
        gt = getattr(getattr(st, "value", None), "gtype", None)
        return gt is not None and gt.kind == "array"

    def emit_var_decl(self, name, t: A.Type, init_c=None, const=False):
        return self.c_decl(name, t, init_c, const=const) + ";"

    # ---------- điểm vào ----------
    def generate(self) -> str:
        self.w("// === Sinh tự động bởi trình biên dịch G ===")
        self.w('#include "g_runtime.h"')
        self.w("")

        struct_defs = {}
        self.const_names = {it.name for it in self.prog.items
                            if isinstance(it, A.GlobalVar) and it.is_const}
        for it in self.prog.items:
            if isinstance(it, A.StructDef):
                self.struct_names.add(it.name)
                struct_defs[it.name] = it
            elif isinstance(it, A.EnumDef):
                self.enum_names.add(it.name)
                for vname, _ in it.variants:
                    self.enum_variants.add(vname)
        self.struct_defs = struct_defs   # cho phép print/dbg tự bung struct

        # 1a) enum trước (struct có thể nhúng enum theo giá trị)
        for it in self.prog.items:
            if isinstance(it, A.EnumDef):
                self.gen_enum(it)
        # Hàm tên-biến-thể cho mỗi enum: dùng khi in '{}' (Red thay vì 0).
        self.emit_enum_name_fns()

        # 1b) Khai báo tiến (forward decl) MỌI struct: cho phép tự/đệ-quy tham
        #     chiếu qua con trỏ (linked list) và tham chiếu lẫn nhau.
        if struct_defs:
            for it in self.prog.items:
                if isinstance(it, A.StructDef):
                    self.w(f"typedef struct {self.cn(it.name)} {self.cn(it.name)};")
            self.w("")

        # Điểm chèn typedef con trỏ hàm: SAU enum + forward-decl struct (để typedef
        # tham chiếu được tên struct/enum), TRƯỚC định nghĩa struct/global/hàm dùng
        # chúng. Các typedef được gom dần khi sinh mã rồi splice vào đây ở cuối.
        fnptr_at = len(self.out)

        # 1c) Định nghĩa struct theo thứ tự topo: struct nhúng struct khác THEO
        #     GIÁ TRỊ phải đứng sau struct đó (trường con trỏ không tạo ràng buộc).
        topo = self._topo_sort_structs(struct_defs)
        for name in topo:
            self.gen_struct(struct_defs[name])
        # Hàm so sánh bằng theo trường cho mỗi struct (cho assert_eq/check_eq) —
        # sinh theo cùng thứ tự topo để eq của struct lồng có trước eq của struct cha.
        self.emit_struct_eq_fns(topo)

        # Điểm chèn HÀM IN SLICE: phải SAU định nghĩa struct (chúng truy cập
        # trường của struct), khác với typedef slice vốn chỉ cần khai báo tiến.
        slice_print_at = len(self.out)

        # 2) biến toàn cục
        for it in self.prog.items:
            if isinstance(it, A.GlobalVar):
                self.gen_global(it)
        self.w("")

        # 3) nguyên mẫu hàm + method
        for it in self.prog.items:
            if isinstance(it, A.Function):
                if it.is_extern and it.name in _RUNTIME_DEFINED:
                    # Runtime (hosted: libc header; freestanding: g_runtime.h)
                    # đã định nghĩa các hàm này -> KHÔNG phát lại nguyên mẫu,
                    # tránh 'conflicting types' khi chữ ký G khác chút ít
                    # ('*u8' thay vì 'void*', 'usize' thay vì 'size_t'...).
                    continue
                self.w(self.fn_signature(it) + ";")
            elif isinstance(it, A.Impl):
                for m in it.methods:
                    self.w(self.fn_signature(m) + ";")
        self.w("")

        # 4) định nghĩa hàm + method
        for it in self.prog.items:
            if isinstance(it, A.Function):
                if it.body is not None:
                    self.gen_fn(it)
                    self.w("")
            elif isinstance(it, A.Impl):
                for m in it.methods:
                    if m.body is not None:
                        self.gen_fn(m)
                        self.w("")

        # 5) Khởi tạo các global không-hằng lúc chạy (C cấm initializer động).
        #    Dùng __attribute__((constructor)) -> chạy TRƯỚC main, đúng thứ tự
        #    khai báo (cho phép global tham chiếu global khai báo trước nó).
        self.emit_global_init_ctor()

        # Splice các typedef con trỏ hàm vào vị trí đã dành sẵn (sau forward-decl).
        if self.fnptr_decls:
            block = ["// Con trỏ hàm (typedef sinh tự động cho kiểu fn(...)->R)."]
            block += self.fnptr_decls + [""]
            self.out[fnptr_at:fnptr_at] = block
        # Typedef slice (ptr+len) — chèn TRƯỚC typedef con trỏ hàm để một slice
        # chứa con trỏ hàm vẫn hợp lệ.
        # Hàm in slice trước (chỉ số lớn hơn), rồi typedef — chèn từ dưới lên để
        # các chỉ số đã tính không bị dịch.
        if self.slice_print_decls:
            block = ["// In slice ('{}' trên slice<T>) — độ dài biết lúc chạy."]
            block += self.slice_print_decls + [""]
            self.out[slice_print_at:slice_print_at] = block
        if self.slice_decls:
            block = ["// Slice: con trỏ béo { T* ptr; size_t len; }."]
            block += self.slice_decls + [""]
            self.out[fnptr_at:fnptr_at] = block

        return "\n".join(self.out)

    def emit_global_init_ctor(self):
        if not self.global_inits:
            return
        self.w("// Khởi tạo global không-hằng trước khi vào main (thứ tự khai báo).")
        self.w("__attribute__((constructor)) static void _g_init_globals(void) {")
        self.indent += 1
        for name, value in self.global_inits:
            self.w(f"{name} = {self.gen_expr(value)};")
        self.indent -= 1
        self.w("}")
        self.w("")

    # ---------- struct / enum / global ----------
    def _topo_sort_structs(self, struct_defs: dict) -> list:
        """Sắp xếp topo theo phụ thuộc 'nhúng theo giá trị'. Trường con trỏ (*T)
        KHÔNG tạo ràng buộc (forward decl là đủ). Chu trình theo-giá-trị là không
        hợp lệ trong C; ta vẫn xuất phần còn lại để báo lỗi rõ ràng nếu có."""
        deps = {name: set() for name in struct_defs}
        for name, s in struct_defs.items():
            for f in s.fields:
                # Phụ thuộc chỉ khi nhúng trực tiếp THEO GIÁ TRỊ: không con trỏ
                # ngoài (*T), không con trỏ phần tử ([N]*T), không con trỏ hàm.
                # (Mảng-theo-giá-trị '[N]T' vẫn cần kiểu đầy đủ -> vẫn là phụ thuộc.)
                if (f.type.ptr == 0 and getattr(f.type, "elem_ptr", 0) == 0
                        and not getattr(f.type, "is_fn", False)
                        and f.type.name in struct_defs):
                    deps[name].add(f.type.name)
        order = []
        done = set()
        temp = set()

        def visit(n):
            if n in done:
                return
            if n in temp:        # chu trình theo giá trị — bỏ qua để C báo lỗi sau
                return
            temp.add(n)
            for d in sorted(deps[n]):
                visit(d)
            temp.discard(n)
            done.add(n)
            order.append(n)

        for name in struct_defs:           # giữ thứ tự khai báo ổn định
            visit(name)
        return order

    def gen_struct(self, s: A.StructDef):
        # Struct rỗng không hợp lệ trong C chuẩn -> chèn trường đệm.
        self.w(f"struct {self.cn(s.name)} {{")
        self.indent += 1
        if not s.fields:
            self.w("char _g_empty;")
        for f in s.fields:
            self.w(self.emit_var_decl(self.cn(f.name), f.type))
        self.indent -= 1
        # Thuộc tính bố cục (@packed/@align) đặt sau '}' của định nghĩa struct.
        _, attr = self._gnu_attrs(getattr(s, "attrs", []))
        self.w("}" + (f" {attr}" if attr else "") + ";")
        self.w("")

    @staticmethod
    def _enum_name_fn(name) -> str:
        return f"_g_enum_{name}_name"

    def emit_enum_name_fns(self):
        """Sinh 'const char* _g_enum_E_name(E v)' trả về TÊN biến thể (chuỗi) cho
        mỗi enum — để in '{}' ra 'Red' thay vì '0'. Nhãn 'case' khử trùng theo GIÁ
        TRỊ (hai biến thể cùng giá trị -> chỉ lấy tên đầu) để C không lỗi trùng case.
        Giá trị không khớp -> '?'. ('{d}' tường minh vẫn in số nguyên.)"""
        tables = getattr(self.prog, "enum_tables", {})
        emitted = False
        for it in self.prog.items:
            if not isinstance(it, A.EnumDef):
                continue
            emitted = True
            self.w(f"static inline const char* {self._enum_name_fn(it.name)}"
                   f"({self.cn(it.name)} _v) {{")
            self.indent += 1
            self.w("switch ((long long)_v) {")
            self.indent += 1
            seen = set()
            table = tables.get(it.name, {})
            for vname, _ in it.variants:
                val = table.get(vname)
                if val is not None:
                    if val in seen:
                        continue
                    seen.add(val)
                self.w(f'case {self.cn(vname)}: return "{vname}";')
            self.indent -= 1
            self.w("}")
            self.w('return "?";')
            self.indent -= 1
            self.w("}")
        if emitted:
            self.w("")

    # ---------- so sánh bằng generic (cho assert_eq / check_eq) ----------
    @staticmethod
    def _struct_eq_fn(name) -> str:
        return f"_g_eq_{name}"

    def emit_struct_eq_fns(self, order):
        """Sinh 'bool _g_eq_T(T a, T b)' so sánh bằng theo TỪNG TRƯỜNG cho mỗi
        struct — nền tảng generic của assert_eq/check_eq. Đệ quy cho trường struct
        lồng; chuỗi so theo nội dung (g_str_eq); mảng so theo byte (memcmp); con
        trỏ/con trỏ hàm so theo địa chỉ. Thêm một struct mới -> tự có so sánh."""
        if not order:
            return
        self.w("// So sánh bằng theo trường — dùng cho assert_eq/check_eq trên struct.")
        for name in order:
            sdef = self.struct_defs[name]
            self.w(f"static inline bool {self._struct_eq_fn(name)}"
                   f"({self.cn(name)} _a, {self.cn(name)} _b) {{")
            self.indent += 1
            if not sdef.fields:
                self.w("(void)_a; (void)_b; return true;")
            else:
                conds = [self._field_eq(f.type, f"_a.{self.cn(f.name)}", f"_b.{self.cn(f.name)}")
                         for f in sdef.fields]
                self.w("return " + " && ".join(conds) + ";")
            self.indent -= 1
            self.w("}")
        self.w("")

    def _field_eq(self, t: A.Type, l, r) -> str:
        """Biểu thức C so sánh bằng MỘT trường (theo A.Type của trường)."""
        if self._dims(t):                              # mảng -> so byte
            return f"(memcmp(&({l}), &({r}), sizeof({l})) == 0)"
        if getattr(t, "is_fn", False):
            return f"(({l}) == ({r}))"
        if t.ptr > 0 or getattr(t, "elem_ptr", 0) > 0:
            if t.name == "char" and t.ptr == 1:        # *char -> so nội dung
                return f"g_str_eq({l}, {r})"
            return f"(({l}) == ({r}))"                  # con trỏ khác -> địa chỉ
        if getattr(t, "slice_elem", None) is not None:
            # slice = { ptr, len }: so sánh BẰNG là cùng vùng nhớ + cùng độ dài
            # (so danh tính, không so nội dung — nội dung dùng vòng lặp). C không
            # cho '==' trên struct nên phải so từng thành phần.
            return f"(({l}).ptr == ({r}).ptr && ({l}).len == ({r}).len)"
        if t.name in self.struct_defs:                 # struct lồng -> đệ quy
            return f"{self._struct_eq_fn(t.name)}({l}, {r})"
        if t.name == "str":
            return f"g_str_eq({l}, {r})"
        return f"(({l}) == ({r}))"                      # vô hướng / enum

    def _gen_eq(self, gt: T.GType, l, r) -> str:
        """Biểu thức C so sánh bằng hai giá trị kiểu gt (cho assert_eq/check_eq):
        struct -> hàm _g_eq_T; chuỗi/'*char' -> g_str_eq; còn lại -> '=='."""
        if gt.kind == "struct" and gt.name in self.struct_defs:
            return f"{self._struct_eq_fn(gt.name)}({l}, {r})"
        if gt.kind == "slice":
            return f"(({l}).ptr == ({r}).ptr && ({l}).len == ({r}).len)"
        if self._is_stringy(gt):
            return f"g_str_eq({l}, {r})"
        return f"(({l}) == ({r}))"

    def _gen_ord(self, gt: T.GType, l, r, op) -> str:
        """Biểu thức C so sánh THỨ TỰ hai giá trị (cho assert_lt/le/gt/ge):
        chuỗi/'*char' -> strcmp(l, r) op 0; vô hướng/char/enum -> 'l op r'."""
        if self._is_stringy(gt):
            return f"(strcmp({l}, {r}) {op} 0)"
        return f"(({l}) {op} ({r}))"

    def _gtype_print_frag(self, gt: T.GType, cexpr):
        """(đoạn_fmt, [c_args]) để in MỘT giá trị kiểu gt — generic cho mọi kiểu.
        struct -> bung trường; enum -> tên biến thể; chuỗi -> %s; con trỏ -> %p;
        vô hướng -> specifier theo kiểu. 'cexpr' phải ổn định (đã vật hoá)."""
        if gt.kind == "struct" and gt.name in self.struct_defs:
            return self._struct_print_fragment(gt.name, cexpr)
        if gt.kind == "array" and isinstance(gt.n, int):
            return self._gtype_array_frag(gt, cexpr)
        if gt.kind == "slice":
            # Độ dài slice chỉ biết LÚC CHẠY nên không thể dựng chuỗi định dạng
            # tĩnh như mảng: phát một hàm in riêng cho từng kiểu phần tử.
            return "%s", [f"{self._slice_print_fn(gt)}({cexpr})"]
        if gt.kind == "enum" and gt.name in self.enum_names:
            return "%s", [f"{self._enum_name_fn(gt.name)}({cexpr})"]
        if self._is_stringy(gt):
            return "%s", [cexpr]
        if gt.kind in ("ptr", "null", "func"):
            return "%p", [f"(void*)({cexpr})"]
        spec, is_bool = T.printf_spec(gt)
        if is_bool:
            return "%s", [f'(({cexpr}) ? "true" : "false")']
        cast = self._spec_cast(spec)
        return spec, [f"({cast})({cexpr})" if cast else cexpr]

    def gen_enum(self, e: A.EnumDef):
        parts = []
        for vname, vval in e.variants:
            if vval is not None:
                parts.append(f"{self.cn(vname)} = {self.gen_expr(vval)}")
            else:
                parts.append(self.cn(vname))
        self.w(f"typedef enum {{ {', '.join(parts)} }} {self.cn(e.name)};")
        self.w("")

    def gen_global(self, g: A.GlobalVar):
        _, attr = self._gnu_attrs(getattr(g, "attrs", []))
        attr_sp = (attr + " ") if attr else ""
        # Ký hiệu ngoài (extern): chỉ khai báo, KHÔNG cấp phát/static — địa chỉ/giá
        # trị do assembly hoặc linker script cung cấp (vd '_kernel_end', '_bss_start').
        if getattr(g, "is_extern", False):
            self.w("extern " + attr_sp
                   + self.c_decl(g.name, g.type, None, const=False) + ";")
            return   # extern: giữ NGUYÊN tên (ký hiệu linker/asm)
        # A.Type dùng cho khai báo: lấy từ annotation, hoặc suy ra từ kiểu đã infer
        # (không dùng __auto_type vì nó cấm khai báo không-initializer).
        if g.type is not None:
            decl_type = g.type
            if isinstance(g.value, A.ArrayLit):
                decl_type = self._array_type_with_inferred_dims(g.type, g.value)
        else:
            gt = getattr(g, "resolved_type", None) or self.gtype_of(g.value)
            decl_type = self._gtype_to_ctype_decl(gt)

        const_init = g.value is None or self._is_const_init(g.value)
        if const_init:
            if isinstance(g.value, A.ArrayLit):
                init = self.gen_array_init(g.value)
            else:
                init = self.gen_expr(g.value) if g.value is not None else None
            self.w("static " + attr_sp + self.c_decl(self.cn(g.name), decl_type, init,
                                                     const=g.is_const) + ";")
            return

        # Initializer KHÔNG phải hằng số biên dịch (tham chiếu global khác, lời gọi
        # hàm, g_alloc...): C cấm. -> khai báo storage zero-init, gán lúc chạy trong
        # constructor. Bỏ 'const' ở mức C để gán được (G-checker vẫn cấm gán lại).
        self.w("static " + attr_sp
               + self.c_decl(self.cn(g.name), decl_type, None, const=False) + ";")
        self._defer_global_init(self.cn(g.name), g.value)

    def _defer_global_init(self, lhs, value):
        """Lên lịch khởi tạo một global lúc chạy. Mảng được gán theo từng phần tử
        (C cấm gán cả mảng bằng '='); còn lại gán nguyên giá trị."""
        if isinstance(value, A.ArrayLit):
            for idx, el in enumerate(value.elements):
                self._defer_global_init(f"{lhs}[{idx}]", el)
        else:
            self.global_inits.append((lhs, value))

    # ---------- hàm / method ----------
    def mangle(self, fn: A.Function) -> str:
        if fn.recv:
            return f"{self.cn(fn.recv)}__{fn.name}"
        if fn.name == "main" or fn.is_extern:
            return fn.name          # điểm vào / ký hiệu ngoài: giữ nguyên tên
        return self.cn(fn.name)

    def fn_signature(self, fn: A.Function) -> str:
        parts = []
        for p in fn.params:
            pname = getattr(p, "c_name", "") or self.cn(p.name)
            # Tham số MẢNG 'mut' được sao chép ra bộ đệm cục bộ trong prologue (xem
            # gen_fn): tham số C thật đổi tên, còn tên gốc thuộc về bản sao.
            if getattr(p, "mutable", False) and fn.body is not None:
                dims = self._dims(p.type)
                if dims and all(isinstance(d, int) for d in dims):
                    p.arr_copy_from = pname + "__src"
                    pname = p.arr_copy_from
            parts.append(self.c_decl(pname, p.type, decay_first=True))
        params = ", ".join(parts) if parts else "void"
        ret = self.c_type(fn.ret)
        qual = ""
        if fn.is_comptime:
            qual = "static inline "
        elif fn.is_extern:
            qual = "extern "
        # Thuộc tính @ (naked/noreturn/section/align/inline/...) đặt trước khai báo.
        quals, attr = self._gnu_attrs(getattr(fn, "attrs", []))
        prefix = (attr + " " if attr else "") + qual + (quals + " " if quals else "")
        return f"{prefix}{ret} {self.mangle(fn)}({params})"

    def gen_fn(self, fn: A.Function):
        self.cur_src_file = getattr(fn, "src_file", None) or getattr(self, "cur_src_file", None)
        self._addr_taken = self._collect_addr_taken(fn.body or [])
        self.w(self.fn_signature(fn) + " {")
        self.scope_stack = []
        # Tham số MẢNG khai báo 'mut': C truyền mảng dưới dạng con trỏ, nên ghi
        # vào nó sẽ sửa mảng của NGƯỜI GỌI — trái ngữ nghĩa "tham số là bản sao"
        # mà 'mut' trên tham số vô hướng vẫn giữ. Sao chép ra bộ đệm cục bộ.
        prologue = []
        for prm in fn.params:
            src = getattr(prm, "arr_copy_from", None)
            if src is None:
                continue
            pname = getattr(prm, "c_name", "") or self.cn(prm.name)
            prologue.append(self.c_decl(pname, prm.type, None, const=False) + ";")
            prologue.append(f"memcpy({pname}, {src}, sizeof({pname}));")
        self.gen_scoped_body(fn.body, is_loop=False, prologue=prologue)
        # Hàm non-void mà checker đã chứng minh luôn-trả-về nhưng câu lệnh cuối
        # không phải 'return' tường minh (vd match enum vét cạn / if-else-diverge):
        # chèn __builtin_unreachable() để C không cảnh báo "control reaches end".
        if (fn.ret is not None and fn.ret.name != "void"
                and fn.body
                and not isinstance(fn.body[-1], A.Return)):
            self.indent += 1
            self.w("__builtin_unreachable();")
            self.indent -= 1
        self.w("}")

    # ---------- quản lý scope & defer (kiểu Zig, theo block, LIFO) ----------
    def _collect_addr_taken(self, node, out=None):
        """Tên các biến bị lấy địa chỉ ('&x') ở BẤT KỲ đâu trong thân hàm.

        Dùng để quyết định có gắn 'const' cho khai báo C hay không — xem gen_let."""
        if out is None:
            out = set()
        if isinstance(node, list):
            for x in node:
                self._collect_addr_taken(x, out)
            return out
        if isinstance(node, A.Unary) and node.op == "&":
            tgt = node.operand
            while isinstance(tgt, (A.FieldAccess, A.Index)):
                tgt = tgt.base
            if isinstance(tgt, A.Ident):
                out.add(tgt.name)
        for f in getattr(node, "__dataclass_fields__", {}):
            v = getattr(node, f, None)
            if isinstance(v, (list, tuple)):
                for x in v:
                    self._collect_addr_taken(x, out)
            elif hasattr(v, "__dataclass_fields__"):
                self._collect_addr_taken(v, out)
        return out

    def gen_scoped_body(self, body, is_loop=False, prologue=None):
        """Sinh thân một block: mở scope defer, (tuỳ chọn) prologue, các lệnh,
        rồi xả defer của scope này (nếu block không kết thúc bằng return/break/continue)."""
        frame = {"defers": [], "is_loop": is_loop}
        self.scope_stack.append(frame)
        self.indent += 1
        if prologue:
            for line in prologue:
                self.w(line)
        for s in body:
            self.gen_stmt(s)
        if not (body and isinstance(body[-1], (A.Return, A.Break, A.Continue))):
            self._flush_frame(frame)
        self.indent -= 1
        self.scope_stack.pop()

    def _flush_frame(self, frame):
        for d in reversed(frame["defers"]):
            self.gen_stmt(d)

    def _emit_exit_defers(self, kind):
        """Xả defer khi rời hàm/vòng lặp: return xả mọi scope; break/continue
        xả tới scope vòng lặp gần nhất (bao gồm chính nó)."""
        for frame in reversed(self.scope_stack):
            self._flush_frame(frame)
            if kind != "return" and frame["is_loop"]:
                break

    # ---------- câu lệnh ----------
    def gen_stmt(self, st):
        if isinstance(st, A.Let):
            self.gen_let(st)
        elif isinstance(st, A.Return):
            # Giá trị trả về phải được TÍNH TRƯỚC khi chạy defer (như Zig/Go):
            # 'defer n = 999; return n + 1' phải trả 1, không phải 1000. Vật hoá
            # vào biến tạm khi hàm có defer đang chờ.
            if st.value is not None:
                val_c = self.gen_expr(st.value)
                if any(f["defers"] for f in self.scope_stack):
                    rv = self.tmp("_gret")
                    self.w(f"__auto_type {rv} = ({val_c});")
                    self._emit_exit_defers("return")
                    self.w(f"return {rv};")
                else:
                    self._emit_exit_defers("return")
                    self.w(f"return {val_c};")
            else:
                self._emit_exit_defers("return")
                self.w("return;")
        elif isinstance(st, A.If):
            self.gen_if(st)
        elif isinstance(st, A.While):
            self.w(f"while ({self.gen_expr(st.cond)}) {{")
            self.gen_scoped_body(st.body, is_loop=True)
            self.w("}")
        elif isinstance(st, A.Loop):
            self.w("for (;;) {")
            self.gen_scoped_body(st.body, is_loop=True)
            self.w("}")
        elif isinstance(st, A.For):
            self.gen_for(st)
        elif isinstance(st, A.ForEach):
            self.gen_foreach(st)
        elif isinstance(st, A.Match):
            self.gen_match(st)
        elif isinstance(st, A.Block):
            self.w("{")
            self.gen_scoped_body(st.body, is_loop=False)
            self.w("}")
        elif isinstance(st, A.Defer):
            # ghi nhận vào scope hiện tại; sẽ xả khi rời block (LIFO)
            self.scope_stack[-1]["defers"].append(st.stmt)
        elif isinstance(st, A.Asm):
            self.gen_asm(st)
        elif isinstance(st, A.Break):
            self._emit_exit_defers("break")
            self.w("break;")
        elif isinstance(st, A.Continue):
            self._emit_exit_defers("continue")
            self.w("continue;")
        elif isinstance(st, A.Assign):
            self.gen_assign(st)
        elif isinstance(st, A.ExprStmt):
            self.w(f"{self.gen_expr(st.expr)};")
        else:
            raise CodegenError(f"câu lệnh chưa hỗ trợ: {st}")

    def gen_assign(self, st: A.Assign):
        tgt_c = self.gen_expr(st.target)
        val_c = self.gen_expr(st.value)
        # '%=' trên số thực: C cấm '%' cho double -> viết lại bằng fmod(). Lượng
        # giá đích đúng MỘT lần qua con trỏ để an toàn khi đích có tác dụng phụ
        # (vd a[f()] %= x). Đích không lấy địa chỉ được thì lặp lại biểu thức.
        if st.op == "%=":
            lt = self.gtype_of(st.target)
            rt = self.gtype_of(st.value)
            if lt.kind == "float" or rt.kind == "float":
                if self._is_addressable(st.target):
                    p = self.tmp("_gp")
                    ct = T.c_type(lt) if lt.kind != "unknown" else "double"
                    self.w(f"{{ {ct}* {p} = &({tgt_c}); "
                           f"*{p} = fmod(*{p}, {val_c}); }}")
                else:
                    self.w(f"{tgt_c} = fmod({tgt_c}, {val_c});")
                return
        # '/=' và '%=' số nguyên với mẫu không hằng: kiểm chia 0 lúc chạy (như
        # toán tử '/'/'%' hai ngôi). Đích được lượng giá một lần qua con trỏ.
        if st.op in ("/=", "%="):
            lt = self.gtype_of(st.target)
            rt = self.gtype_of(st.value)
            if lt.is_integer() and rt.is_integer() and not self._is_const_expr(st.value):
                op = st.op[0]
                w = self._where(st)
                if self._is_addressable(st.target):
                    p = self.tmp("_gp")
                    ct = T.c_type(lt)
                    self.w(f"{{ {ct}* {p} = &({tgt_c}); "
                           f"*{p} = g_chk_div(*{p}, {op}, {val_c}, {w}); }}")
                else:
                    self.w(f"{tgt_c} = g_chk_div({tgt_c}, {op}, {val_c}, {w});")
                return
        self.w(f"{tgt_c} {st.op} {val_c};")

    def gen_let(self, st: A.Let):
        const = not st.mutable
        name = getattr(st, "c_name", st.name)
        # MẢNG bất biến: KHÔNG gắn 'const' ở C. Tính bất biến của G đã được checker
        # bảo đảm tĩnh; còn ở C mảng phân rã thành 'const T*' khi truyền cho tham số
        # 'T*' -> cảnh báo 'discards const qualifier' (và với '-Werror' là lỗi) dù mã
        # G hoàn toàn hợp lệ. Vô hướng/struct/con trỏ vẫn giữ 'const'.
        if const and self._is_array_decl(st):
            const = False
        # Biến 'let' bị LẤY ĐỊA CHỈ ở đâu đó trong hàm: KHÔNG gắn 'const' ở C.
        # G cho phép ghi qua con trỏ tới một 'let' (checker chấp nhận '*p = v'),
        # nhưng ở C ghi qua con trỏ đã bỏ 'const' của một đối tượng THẬT SỰ
        # const là hành vi KHÔNG XÁC ĐỊNH: chương trình in 6 với -O0 và 5 với
        # -O2. Bỏ 'const' làm cho ngữ nghĩa G thành hiện thực ở mọi mức tối ưu.
        if const and st.name in getattr(self, "_addr_taken", ()):
            const = False
        # ----- mảng literal (kể cả nhiều chiều): T name[..][..] = { ... } -----
        if isinstance(st.value, A.ArrayLit):
            init = self.gen_array_init(st.value)
            if st.type is not None:
                ty = self._array_type_with_inferred_dims(st.type, st.value)
                self.w(self.c_decl(name, ty, init, const=const) + ";")
            else:
                gt = self.gtype_of(st.value)
                ty = self._gtype_to_ctype_decl(gt)
                self.w(self.c_decl(name, ty, init, const=const) + ";")
            return

        # ----- 'let b = a' với a là MẢNG tĩnh: SAO CHÉP, không chia sẻ -----
        # '__auto_type b = a' cho ra một CON TRỎ vào chính bộ nhớ của a (mảng phân
        # rã), nên 'b[0] = 9' sửa luôn a — trái ngữ nghĩa giá trị của G. Khai báo
        # một mảng thật rồi memcpy.
        if st.value is not None and not isinstance(st.value, A.ArrayLit):
            vgt = self.gtype_of(st.value)
            if vgt is not None and vgt.kind == "array" and isinstance(vgt.n, int):
                src = self.gen_expr(st.value)
                ty = st.type if st.type is not None else self._gtype_to_ctype_decl(vgt)
                self.w(self.c_decl(name, ty, None, const=False) + ";")
                self.w(f"memcpy({name}, {src}, sizeof({name}));")
                return

        init_c = self.gen_expr(st.value) if st.value is not None else None
        if st.type is not None:
            if init_c is None:
                # Không có initializer: zero-init '= {0}' (an toàn, tất định kiểu Go)
                # thay vì để bộ nhớ rác (UB). '{0}' hợp lệ cho vô hướng/mảng/struct.
                self.w(self.c_decl(name, st.type, "{0}", const=const) + ";")
            else:
                self.w(self.c_decl(name, st.type, init_c, const=const) + ";")
        else:
            if init_c is None:
                self.w(f"int {name} = 0;")
            else:
                gt = self.gtype_of(st.value)
                # Kiểu VÔ HƯỚNG cụ thể (int/char/bool/float đã suy luận) -> khai báo
                # bằng đúng kiểu C đó thay vì '__auto_type'. '__auto_type' lấy kiểu
                # đã THĂNG CẤP của C ('u8 + u8' -> int) nên 'let c = a + b' (u8) sẽ
                # giữ 300 thay vì wrap về 44 — lệch với 'let c: u8 = ...', với global
                # cùng biểu thức, và với 'typeof(c)' (báo u8). Khai báo hẹp lại cho
                # nhất quán. Mảng/con trỏ/struct/enum/hàm/unknown giữ '__auto_type'
                # (phân rã mảng-> con trỏ & suy kiểu phức là hành vi mong muốn ở đó).
                if gt is not None and gt.kind in ("int", "char", "bool", "float"):
                    ty = self._gtype_to_ctype_decl(gt)
                    self.w(self.c_decl(name, ty, init_c, const=const) + ";")
                elif gt is not None and gt.kind == "ptr" and self._ptr_decl_ok(gt):
                    # Con trỏ suy luận: khai báo TƯỜNG MINH 'T* const p' (east-const)
                    # thay vì 'const __auto_type' — cái sau suy ra 'const T*' khi
                    # init là '&x' với x bất biến, làm '*p = v' bị C từ chối dù G
                    # cho phép ghi qua con trỏ.
                    ty = self._gtype_to_ctype_decl(gt)
                    self.w(self.c_decl(name, ty, init_c, const=const) + ";")
                else:
                    q = "const " if const else ""
                    self.w(f"{q}__auto_type {name} = {init_c};")

    @staticmethod
    def _ptr_decl_ok(gt: T.GType) -> bool:
        """Kiểu con trỏ có thể khai báo tường minh bằng _gtype_to_ctype_decl không?
        (Loại 'unknown'/'null'/'void' và con trỏ tới chuỗi 'str' vốn đã là
        'const char*' — để __auto_type xử lý cho an toàn.)"""
        cur = gt
        while cur is not None and cur.kind in ("ptr", "array"):
            cur = cur.elem
        return cur is not None and cur.kind in ("int", "float", "char", "bool",
                                                 "struct", "enum", "func")

    @staticmethod
    def _int_literal_c(e: A.IntLit) -> str:
        """Render một literal nguyên thành hằng C có HẬU TỐ bề rộng đúng, để C
        không tính trong 'int' 32-bit rồi cắt cụt (vd '1 << 40', '5000000000',
        '0x8000000000000000'). Quy tắc:
          vừa i32           -> không hậu tố (int)
          vượt i32, vừa i64 -> 'LL'
          vượt i63, vừa u64 -> 'ULL' (literal không âm; số âm là Unary('-', lit))
        Lexer đã chuẩn hoá 0x/0b/0o về thập phân nên ở đây luôn là chuỗi số 10."""
        try:
            v = int(e.value, 0)
        except ValueError:
            return e.value
        if v <= (1 << 31) - 1:
            return e.value
        if v <= (1 << 63) - 1:
            return e.value + "LL"
        return e.value + "ULL"

    def gen_array_init(self, lit: A.ArrayLit) -> str:
        """Sinh initializer { ... } (đệ quy cho mảng lồng nhau)."""
        parts = []
        for x in lit.elements:
            if isinstance(x, A.ArrayLit):
                parts.append(self.gen_array_init(x))
            else:
                parts.append(self.gen_expr(x))
        return "{ " + ", ".join(parts) + " }"

    def _array_type_with_inferred_dims(self, decl_t: A.Type, lit: A.ArrayLit) -> A.Type:
        """Điền các chiều mảng còn để trống bằng độ dài literal tương ứng.
        Dùng dataclasses.replace để GIỮ mọi trường khác (elem_ptr, is_fn,
        fn_params, fn_ret...) — tránh đánh mất kiểu con trỏ hàm của phần tử."""
        import dataclasses
        dims = self._dims(decl_t)
        if not dims:
            return decl_t
        filled = []
        node = lit
        for d in dims:
            if d in (None, "dyn"):
                n = len(node.elements) if isinstance(node, A.ArrayLit) else 0
                filled.append(n)
            else:
                filled.append(d)
            node = node.elements[0] if (isinstance(node, A.ArrayLit) and node.elements) else None
        return dataclasses.replace(decl_t, dims=filled, array=filled[0])

    def _gtype_to_ctype_decl(self, gt: T.GType) -> A.Type:
        """Suy ra A.Type (cho c_decl) từ GType đã suy luận (khi không có annotation).
        Phân biệt con trỏ NGOÀI ('*[N]T': ptr) với con trỏ PHẦN TỬ ('[N]*T':
        elem_ptr) — hai thứ này sinh khai báo C khác hẳn nhau."""
        outer = 0
        cur = gt
        while cur is not None and cur.kind == "ptr" and cur.elem is not None \
                and cur.elem.kind == "array":
            outer += 1
            cur = cur.elem
        dims = []
        while cur is not None and cur.kind == "array":
            dims.append(cur.n if cur.n is not None else "dyn")
            cur = cur.elem
        base = cur if cur is not None else T.INT
        ptr = 0
        while base.kind == "ptr":
            ptr += 1
            base = base.elem
        if dims:
            elem_ptr, ptr = ptr, outer
        else:
            elem_ptr, ptr = 0, ptr + outer
        if base.kind == "func":
            return A.Type(
                "fn", ptr=ptr, elem_ptr=elem_ptr, dims=dims or None,
                array=(dims[0] if dims else None), is_fn=True,
                fn_params=[self._gtype_to_ctype_decl(p) for p in base.params],
                fn_ret=self._gtype_to_ctype_decl(base.ret))
        name = base.name if base.name else base.kind
        return A.Type(name, ptr=ptr, elem_ptr=elem_ptr, dims=dims or None,
                      array=(dims[0] if dims else None))

    def gen_if(self, st: A.If):
        self.w(f"if ({self.gen_expr(st.cond)}) {{")
        self.gen_scoped_body(st.then, is_loop=False)
        if st.els is not None:
            self.w("} else {")
            self.gen_scoped_body(st.els, is_loop=False)
        self.w("}")

    @staticmethod
    def _static_sign(e):
        """Dấu tĩnh của một biểu thức bước nếu biết lúc biên dịch: +1 / -1 / None.
        Nhận diện literal âm (-N) và literal dương."""
        if isinstance(e, A.Unary) and e.op == "-":
            inner = Codegen._static_sign(e.operand)
            return -inner if inner is not None else None
        if isinstance(e, A.IntLit):
            try:
                v = int(e.value, 0)
            except ValueError:
                return None
            return -1 if v < 0 else 1
        if isinstance(e, A.FloatLit):
            try:
                return -1 if float(e.value) < 0 else 1
            except ValueError:
                return None
        return None

    def gen_for(self, st: A.For):
        # Cận trên (và bước) được tính MỘT lần trước vòng lặp — đúng ngữ nghĩa
        # Rust ('a..b' lượng giá b một lần) và tránh gọi lại hàm/đọc lại biến mỗi
        # vòng. Bọc trong block C để các biến tạm chỉ sống trong phạm vi vòng lặp.
        v = getattr(st, "c_name", "") or st.var
        vt = getattr(st, "var_type", None)
        ctype = T.c_type(vt) if vt is not None else "long"
        self.w("{")
        self.indent += 1
        end = self.tmp("_gend")
        start = self.gen_expr(st.start)
        # Cận trên mang ĐÚNG kiểu của biến đếm: '__auto_type' giữ kiểu gốc của
        # biểu thức ('int' khi biến đếm là 'size_t' -> gcc -Wsign-compare, và
        # so sánh có dấu/không dấu có thể sai với giá trị lớn).
        self.w(f"{ctype} {end} = ({ctype})({self.gen_expr(st.end)});")
        if st.step is None:
            cmp = "<=" if st.inclusive else "<"
            self.w(f"for ({ctype} {v} = {start}; {v} {cmp} {end}; {v}++) {{")
        else:
            s = self.tmp("_gstep")
            self.w(f"__auto_type {s} = ({self.gen_expr(st.step)});")
            sign = self._static_sign(st.step)
            if sign == -1:
                cmp = ">=" if st.inclusive else ">"
                self.w(f"for ({ctype} {v} = {start}; {v} {cmp} {end}; "
                       f"{v} += {s}) {{")
            elif sign == 1:
                cmp = "<=" if st.inclusive else "<"
                self.w(f"for ({ctype} {v} = {start}; {v} {cmp} {end}; "
                       f"{v} += {s}) {{")
            else:
                # Bước không rõ dấu lúc biên dịch: chọn chiều so sánh lúc chạy để
                # vòng lặp đúng cho cả bước âm lẫn dương.
                eq = "=" if st.inclusive else ""
                self.w(f"for ({ctype} {v} = {start}; "
                       f"{s} >= 0 ? {v} <{eq} {end} : {v} >{eq} {end}; "
                       f"{v} += {s}) {{")
        self.gen_scoped_body(st.body, is_loop=True)
        self.w("}")
        self.indent -= 1
        self.w("}")

    def _elem_decl(self, name, elem_type, init_c):
        """Khai báo C cho biến phần tử của foreach. Khi phần tử LẠI là mảng
        (duyệt hàng của mảng nhiều chiều), phải giữ chiều trong: 'int (*row)[3]'
        thay vì 'int* row' (sai bước nhảy). Dùng c_decl với A.Type suy ra."""
        if elem_type is not None and elem_type.kind == "array":
            ty = self._gtype_to_ctype_decl(elem_type)
            # Ép initializer về đúng kiểu con-trỏ-tới-mảng để không cảnh báo mất
            # 'const' khi duyệt mảng nhiều chiều bất biến (let). Lấy kiểu từ một
            # khai báo giả với tên rỗng: 'int (*)[3]'.
            cast = self.c_decl("", ty, None, decay_first=True).strip()
            return self.c_decl(name, ty, f"({cast})({init_c})",
                               decay_first=True) + ";"
        if elem_type is not None and elem_type.kind == "func":
            # Phần tử là con trỏ hàm: dùng typedef (qua c_decl) để vẫn GỌI được.
            ty = self._gtype_to_ctype_decl(elem_type)
            return self.c_decl(name, ty, init_c) + ";"
        elem_c = T.c_type(elem_type if elem_type is not None else T.INT)
        return f"{elem_c} {name} = {init_c};"

    def gen_foreach(self, st: A.ForEach):
        var = getattr(st, "c_name", "") or st.var
        elem_type = getattr(st, "elem_type", T.INT)
        elem_c = T.c_type(elem_type)
        kind = getattr(st, "iter_kind", "array")
        if kind == "str":
            p = self.tmp("_gs")
            src = self.gen_expr(st.iterable)
            self.w(f"for (const char* {p} = ({src}); *{p}; ++{p}) {{")
            self.gen_scoped_body(st.body, is_loop=True,
                                 prologue=[f"{elem_c} {var} = *{p};"])
            self.w("}")
        else:  # mảng tĩnh: dùng sizeof để lấy độ dài
            i = self.tmp("_gi")
            if isinstance(st.iterable, A.ArrayLit):
                # literal: vật hoá vào mảng tạm để sizeof hợp lệ
                arr = self.tmp("_gar")
                init = self.gen_array_init(st.iterable)
                n = len(st.iterable.elements)
                self.w(f"{{ {elem_c} {arr}[{n}] = {init};")
                self.indent += 1
                self.w(f"for (size_t {i} = 0; {i} < {n}; ++{i}) {{")
                self.gen_scoped_body(st.body, is_loop=True,
                                     prologue=[self._elem_decl(var, elem_type,
                                                               f"{arr}[{i}]")])
                self.w("}")
                self.indent -= 1
                self.w("}")
            else:
                arr = self.gen_expr(st.iterable)
                gt = self.gtype_of(st.iterable)
                # Ưu tiên độ dài tĩnh từ kiểu suy luận: 'sizeof(x)/sizeof(x[0])'
                # sai khi x đã phân rã thành con trỏ (tham số hàm, hàng của mảng
                # nhiều chiều) — lúc đó sizeof là kích cỡ con trỏ, không phải mảng.
                if gt.kind == "array" and gt.n not in (None, "dyn"):
                    bound = str(gt.n)
                else:
                    bound = f"sizeof({arr}) / sizeof(({arr})[0])"
                self.w(f"for (size_t {i} = 0; {i} < {bound}; ++{i}) {{")
                if getattr(st, "by_ref", False) and elem_type.kind == "array":
                    # Phần tử LẠI là mảng (duyệt hàng của mảng nhiều chiều): hàng
                    # đã tự phân rã thành con trỏ tới phần tử đầu, nên ghi
                    # 'row[i] = v' vốn đã xuyên vào mảng gốc — dùng khai báo
                    # thường (con trỏ tới mảng), KHÔNG bọc thêm một tầng '*'.
                    self.gen_scoped_body(st.body, is_loop=True,
                                         prologue=[self._elem_decl(var, elem_type,
                                                                   f"({arr})[{i}]")])
                elif getattr(st, "by_ref", False):
                    # 'for mut x in arr': x là THAM CHIẾU tới phần tử (như
                    # 'iter_mut' của Rust) — sửa x phải ghi ngược vào mảng. Hạ
                    # thành con trỏ + macro '#define x (*_p)' sẽ rối; thay vào đó
                    # dùng biến con trỏ và cho checker đánh dấu mọi truy cập là
                    # deref (xem 'by_ref' trong gen_expr/Ident).
                    self.gen_scoped_body(
                        st.body, is_loop=True,
                        prologue=[f"{T.c_type(elem_type)}* {var} = &({arr})[{i}];"])
                else:
                    self.gen_scoped_body(st.body, is_loop=True,
                                         prologue=[self._elem_decl(var, elem_type,
                                                                   f"({arr})[{i}]")])
                self.w("}")

    def gen_match(self, st: A.Match):
        # Hạ 'match' về một chuỗi 'if' ĐỘC LẬP, mỗi nhánh khớp thì NHẢY tới nhãn
        # cuối (goto). Cách này bảo đảm "nhánh đầu khớp thắng" mà vẫn cho nhánh có
        # guard *rớt xuống* nhánh kế khi guard sai — điều chuỗi else-if không làm
        # được (đã vào nhánh là khoá luôn). Nhờ đó binding + guard chạy đúng.
        subj_t = self.gtype_of(st.subject)
        subj_c = self.gen_expr(st.subject)
        if getattr(st, "deref_subject", False):       # match self (self: *Enum)
            subj_t = subj_t.elem
            subj_c = f"(*({subj_c}))"
        is_str = subj_t.kind == "str" or (
            subj_t.kind == "ptr" and subj_t.elem and subj_t.elem.kind == "char")
        tmp = self.tmp("_gm")
        end = self.tmp("_gmend")
        ctype = T.c_type(subj_t) if subj_t.kind != "unknown" else "__auto_type"
        self.w(f"{{ {ctype} {tmp} = {subj_c};")
        self.indent += 1

        def cond_for(pats):
            tests = []
            for p in pats:
                if isinstance(p, A.RangePat):
                    lo = self.gen_expr(p.lo)
                    hi = self.gen_expr(p.hi)
                    up = "<=" if p.inclusive else "<"
                    tests.append(f"({tmp} >= {lo} && {tmp} {up} {hi})")
                    continue
                pc = self.gen_expr(p)
                if is_str:
                    tests.append(f"strcmp({tmp}, {pc}) == 0")
                else:
                    tests.append(f"{tmp} == {pc}")
            return " || ".join(tests) if tests else "1"

        bindings = getattr(st, "bindings", [None] * len(st.arms))
        label_used = False
        for (pats, guard, body), bcname in zip(st.arms, bindings):
            is_bind = bcname is not None
            pat_cond = "1" if (is_bind or pats is None) else cond_for(pats)
            if is_bind:
                # Đưa biến binding (kiểu Rust 'x =>' / 'x if x>0 =>') vào phạm vi —
                # cho cả guard lẫn thân nhánh — rồi mới kiểm guard.
                self.w("{")
                self.indent += 1
                self.w(f"{ctype} {bcname} = {tmp}; (void){bcname};")
                cond = "1" if guard is None else f"({self.gen_expr(guard)})"
                self.w(f"if ({cond}) {{")
                label_used |= self._gen_arm_body(body, end)
                self.w("}")
                self.indent -= 1
                self.w("}")
            else:
                if guard is None:
                    cond = pat_cond
                elif pat_cond == "1":
                    cond = f"({self.gen_expr(guard)})"            # '_ if g'
                else:
                    cond = f"({pat_cond}) && ({self.gen_expr(guard)})"
                self.w(f"if ({cond}) {{")
                label_used |= self._gen_arm_body(body, end)
                self.w("}")
        # Chỉ phát nhãn cuối khi THỰC SỰ có 'goto' nhảy tới — nếu mọi nhánh đều tự
        # thoát (return/break/continue) thì không có goto nào, nhãn sẽ thừa
        # (C cảnh báo 'unused label'). Bỏ nhãn cho mã C sạch.
        if label_used:
            self.w(f"{end}: ;")
        self.indent -= 1
        self.w("}")

    def gen_match_expr(self, e: A.MatchExpr) -> str:
        """'match' ở vị trí BIỂU THỨC -> statement-expression GNU:
            ({ T _r; S _s = subj; if (p1) _r = v1; else if ... ; _r; })
        Nhánh đầu khớp thắng (else-if nối tiếp); binding + guard được đặt trong
        khối riêng. Checker đã bảo đảm vét cạn nên _r luôn được gán."""
        subj_t = self.gtype_of(e.subject)
        subj_c = self.gen_expr(e.subject)
        if getattr(e, "deref_subject", False):
            subj_t = subj_t.elem
            subj_c = f"(*({subj_c}))"
        is_str = subj_t.kind == "str" or (
            subj_t.kind == "ptr" and subj_t.elem and subj_t.elem.kind == "char")
        tmp = self.tmp("_gmx")
        res = self.tmp("_gmr")
        sub_ct = T.c_type(subj_t) if subj_t.kind != "unknown" else "__auto_type"
        res_t = getattr(e, "result_type", None)
        res_ct = T.c_type(res_t) if res_t is not None and res_t.kind != "unknown" \
            else "__auto_type"

        def cond_for(pats):
            tests = []
            for p in pats:
                if isinstance(p, A.RangePat):
                    lo, hi = self.gen_expr(p.lo), self.gen_expr(p.hi)
                    up = "<=" if p.inclusive else "<"
                    tests.append(f"({tmp} >= {lo} && {tmp} {up} {hi})")
                elif is_str:
                    tests.append(f"strcmp({tmp}, {self.gen_expr(p)}) == 0")
                else:
                    tests.append(f"{tmp} == {self.gen_expr(p)}")
            return " || ".join(tests) if tests else "1"

        bindings = getattr(e, "bindings", [None] * len(e.arms))
        parts = [f"{{ {sub_ct} {tmp} = {subj_c}; {res_ct} {res};"]
        for (pats, guard, value), bcname in zip(e.arms, bindings):
            if bcname is not None:
                # binding: cần một khối để đưa tên vào phạm vi cho guard + giá trị
                g = "1" if guard is None else f"({self.gen_expr(guard)})"
                parts.append(f" {{ {sub_ct} {bcname} = {tmp}; (void){bcname};"
                             f" if ({g}) {{ {res} = {self.gen_expr(value)};"
                             f" goto {res}_done; }} }}")
                continue
            pat_cond = "1" if pats is None else cond_for(pats)
            if guard is None:
                cond = pat_cond
            elif pat_cond == "1":
                cond = f"({self.gen_expr(guard)})"
            else:
                cond = f"({pat_cond}) && ({self.gen_expr(guard)})"
            parts.append(f" if ({cond}) {{ {res} = {self.gen_expr(value)};"
                         f" goto {res}_done; }}")
        # Vét cạn đã được checker bảo đảm; nhánh này chỉ để C không cảnh báo
        # 'may be used uninitialized' khi mọi test đều là runtime.
        parts.append(f" {res} = ({res_ct}){{0}};")
        parts.append(f" {res}_done: ; {res}; }}")
        return "(" + "".join(parts) + ")"

    def _gen_arm_body(self, body, end_label) -> bool:
        """Sinh thân một nhánh match rồi nhảy tới nhãn cuối (nếu thân chưa tự
        thoát bằng return/break/continue) — bảo đảm chỉ nhánh khớp đầu tiên chạy.
        Trả về True nếu có phát 'goto' (để caller biết nhãn cuối có được dùng)."""
        self.gen_scoped_body(body, is_loop=False)
        if not (body and isinstance(body[-1], (A.Return, A.Break, A.Continue))):
            self.indent += 1
            self.w(f"goto {end_label};")
            self.indent -= 1
            return True
        return False

    def gen_asm(self, st: A.Asm):
        lines = [l.strip() for l in st.code.split("\n") if l.strip()]
        joined = "\\n\\t".join(lines)
        vol = " __volatile__" if st.volatile else ""
        if not getattr(st, "extended", False):
            self.w(f'__asm__{vol}("{joined}");')
            return
        # asm mở rộng (GCC): "template" : outputs : inputs : clobbers
        def render_ops(ops):
            return ", ".join(f'"{c}" ({self.gen_expr(e)})' for c, e in ops)
        outs = render_ops(st.outputs)
        ins = render_ops(st.inputs)
        clob = ", ".join(f'"{c}"' for c in st.clobbers)
        self.w(f'__asm__{vol}("{joined}" : {outs} : {ins} : {clob});')

    # ---------- biểu thức ----------
    def gen_expr(self, e) -> str:
        c = self._gen_expr_raw(e)
        # Chuyển ngầm mảng tĩnh -> slice, do checker đánh dấu (xem Checker.coerce).
        # Đặt ở MỘT chỗ duy nhất nên mọi ngữ cảnh (đối số, gán, return, phần tử
        # mảng...) đều được xử lý giống nhau.
        ts = getattr(e, "to_slice", None)
        if ts is not None:
            n, _mut = ts
            gt = self.gtype_of(e)
            elem_c = T.c_type(gt.elem) if gt.elem is not None else "void"
            sname = self._slice_typedef(elem_c)
            return f"(({sname}){{ {c}, (size_t){n} }})"
        return c

    def _gen_expr_raw(self, e) -> str:
        if isinstance(e, A.IntLit):
            return self._int_literal_c(e)
        if isinstance(e, A.FloatLit):
            return e.value
        if isinstance(e, A.StrLit):
            return self.c_string(e.value)
        if isinstance(e, A.CharLit):
            return self.c_char(e.value)
        if isinstance(e, A.BoolLit):
            return "true" if e.value else "false"
        if isinstance(e, A.NullLit):
            return "NULL"
        if isinstance(e, A.Ident):
            nm = getattr(e, "c_name", "") or self.cn(e.name)
            # Biến phần tử của 'for mut x in arr' được hạ thành CON TRỎ tới phần
            # tử (để ghi xuyên vào mảng) — mọi lần dùng 'x' phải là '(*x)'.
            if getattr(e, "by_ref_elem", False):
                return f"(*{nm})"
            return nm
        if isinstance(e, A.Binary):
            lc = self.gen_expr(e.left)
            rc = self.gen_expr(e.right)
            # Checker đã xác định cần tự deref (vd 'self == Red' với self: *Color).
            if getattr(e, "deref_left", False):
                lc = f"(*({lc}))"
            if getattr(e, "deref_right", False):
                rc = f"(*({rc}))"
            if getattr(e, "widen_i64", False):
                # Checker xác định hằng này vượt 32-bit: ép toán hạng trái sang
                # 64-bit để C tính trong 64-bit.
                ct = T.c_type(self.gtype_of(e))
                return f"((({ct})({lc})) {e.op} ({rc}))"
            # Modulo số thực: C cấm '%' trên double -> dùng fmod().
            if e.op in ("%", "/"):
                lt = self.gtype_of(e.left)
                rt = self.gtype_of(e.right)
                if lt.kind == "float" or rt.kind == "float":
                    if e.op == "%":
                        return f"fmod({lc}, {rc})"
                # Chia/lấy dư số NGUYÊN cho mẫu không hằng: kiểm 0 lúc chạy (C là
                # UB — thường SIGFPE không lời giải thích). Hằng 0 checker đã bắt.
                elif (lt.is_integer() and rt.is_integer()
                        and not self._is_const_expr(e.right)):
                    return f"g_chk_div({lc}, {e.op}, {rc}, {self._where(e)})"
            # So sánh BẰNG NỘI DUNG cho chuỗi: 'a == b' / 'a != b' trên str dùng
            # g_str_eq (an toàn null) thay vì so con trỏ — nhất quán với 'match'
            # chuỗi (strcmp) và tránh bẫy so địa chỉ literal.
            if e.op in ("==", "!="):
                lt = self.gtype_of(e.left)
                rt = self.gtype_of(e.right)
                if self._is_stringy(lt) and self._is_stringy(rt):
                    eq = f"g_str_eq({lc}, {rc})"
                    return eq if e.op == "==" else f"(!{eq})"
                # Struct so bằng theo TỪNG TRƯỜNG (đệ quy) qua hàm _g_eq_T đã sinh.
                if (lt.kind == "struct" and rt.kind == "struct" and lt.name == rt.name
                        and lt.name in self.struct_defs):
                    eq = f"{self._struct_eq_fn(lt.name)}({lc}, {rc})"
                    return eq if e.op == "==" else f"(!{eq})"
            # Dịch trái mà kết quả suy luận là 64-bit: ép TOÁN HẠNG TRÁI sang kiểu
            # 64-bit để C tính trong 64-bit (không phải 'int' 32-bit rồi cắt cụt).
            # vd '1 << 40' -> '((int64_t)(1) << 40)'.
            if e.op == "<<":
                rgt = self.gtype_of(e)
                lt0 = self.gtype_of(e.left)
                if (rgt.kind == "int" and rgt.bits >= 64
                        and not (lt0.kind == "int" and lt0.bits >= 64)):
                    return f"(({T.c_type(rgt)})({lc}) << {rc})"
            return f"({lc} {e.op} {rc})"
        if isinstance(e, A.Unary):
            if getattr(e, "widen_signed", False):
                # '-w' với w: u32 -> C tính trong unsigned (4294967295); ép sang
                # int64 TRƯỚC khi phủ định để ra -1 đúng như kiểu suy luận (i64).
                return f"(-(int64_t)({self.gen_expr(e.operand)}))"
            if e.op == "&":
                # '&x' với x là biến 'let' (sinh 'T const x') cho 'const T*' ở C,
                # nhưng G CHO PHÉP ghi qua con trỏ ('*p = v'). Ép bỏ 'const' để C
                # không cảnh báo 'discards const qualifier'; tính bất biến của G
                # đã được checker bảo đảm tĩnh.
                # (chỉ con trỏ ĐƠN tới vô hướng/struct: '*[N]T' có kiểu C phức tạp
                # 'T (*)[N]' mà T.c_type không diễn đạt được -> để nguyên)
                gt = getattr(e, "gtype", None)
                if (gt is not None and gt.kind == "ptr" and self._ptr_decl_ok(gt)
                        and gt.elem is not None and gt.elem.kind != "array"):
                    return f"(({T.c_type(gt)})&({self.gen_expr(e.operand)}))"
            return f"({e.op}{self.gen_expr(e.operand)})"
        if isinstance(e, A.Ternary):
            return f"({self.gen_expr(e.cond)} ? {self.gen_expr(e.then)} : {self.gen_expr(e.els)})"
        if isinstance(e, A.MatchExpr):
            return self.gen_match_expr(e)
        if isinstance(e, A.Call):
            return self.gen_call(e)
        if isinstance(e, A.Slice):
            bt = self.gtype_of(e.base)
            rt = self.gtype_of(e)
            if rt.kind == "slice":
                # Mảng tĩnh / slice -> slice. Dựng { ptr+lo, hi-lo } qua macro có
                # kẹp biên; độ dài đi CÙNG con trỏ nên không thể tách rời.
                sname = self._slice_typedef_gt(rt)
                src = self.gen_expr(e.base)
                if bt.kind == "array":
                    n = bt.n if isinstance(bt.n, int) else 0
                    src = f"(({sname}){{ {src}, (size_t){n} }})"
                lo = self.gen_expr(e.lo) if e.lo is not None else "0"
                if e.hi is not None:
                    hi = f"(long long)({self.gen_expr(e.hi)})"
                    if e.inclusive:
                        hi = f"({hi} + 1)"
                else:
                    hi = "0x7fffffffffffffffLL"     # tới hết (macro sẽ kẹp)
                return (f"g_sslice({sname}, {src}, (long long)({lo}), {hi}, "
                        f"{self._where(e)})")
            # s[lo..hi] -> g_str_slice(s, lo, hi); cận khuyết = 0 / độ dài chuỗi.
            # Chuỗi nguồn vật hoá MỘT lần (có thể là lời gọi hàm).
            base = self.gen_expr(e.base)
            sv = self.tmp("_gsl")
            lo = self.gen_expr(e.lo) if e.lo is not None else "0"
            if e.hi is not None:
                hi = f"(long long)({self.gen_expr(e.hi)})"
                if e.inclusive:
                    hi = f"({hi} + 1)"
            else:
                hi = f"(long long)g_str_len_i({sv})"
            return (f"({{ const char* {sv} = ({base}); "
                    f"g_str_slice({sv}, (long long)({lo}), {hi}); }})")
        if isinstance(e, A.Index):
            base_c = self.gen_expr(e.base)
            idx_c = self.gen_expr(e.index)
            # Kiểm tra biên LÚC CHẠY cho mảng TĨNH (cỡ biết lúc biên dịch) khi chỉ
            # số không phải hằng (hằng đã được checker bắt). Con trỏ/[]T không có
            # độ dài -> không kiểm. Tắt bằng --no-checks.
            bt = self.gtype_of(e.base)
            if bt.kind == "slice":
                # Kiểm biên bằng ĐỘ DÀI MANG THEO — luôn có, kể cả khi slice đã
                # đi qua nhiều lời gọi hàm.
                return (f"({base_c}).ptr[g_sidx(({base_c}), {idx_c}, "
                        f"{self._where(e)})]")
            if (bt.kind == "array" and isinstance(bt.n, int)
                    and not self._is_const_expr(e.index)):
                return f"{base_c}[g_idx({idx_c}, {bt.n}, {self._where(e)})]"
            return f"{base_c}[{idx_c}]"
        if isinstance(e, A.FieldAccess):
            ev = getattr(e, "enum_variant", None)
            if ev is not None:                       # Enum.Variant
                return self.cn(ev[1])
            arrow = getattr(e, "auto_deref", False)
            sep = "->" if arrow else "."
            return f"{self.gen_expr(e.base)}{sep}{self.cn(e.field)}"
        if isinstance(e, A.Cast):
            return f"(({self._ctype_str(e.type)})({self.gen_expr(e.expr)}))"
        if isinstance(e, A.SizeOf):
            # Kích thước phải gồm CẢ các chiều mảng: sizeof([10]int) = 10*sizeof(int).
            # c_decl với tên rỗng sinh "int [10]" / "int (*)[3]" hợp lệ trong sizeof.
            op = "_Alignof" if getattr(e, "align", False) else "sizeof"
            return f"{op}({self.c_decl('', e.type)})"
        if isinstance(e, A.SizeOfExpr):
            return f"sizeof({self.gen_expr(e.expr)})"
        if isinstance(e, A.ArrayLit):
            # Mảng literal ở vị trí BIỂU THỨC (đối số hàm, 'return [..]', toán
            # hạng...): '{ ... }' trần chỉ hợp lệ trong khai báo -> phát compound
            # literal C99 '((T[N]){ ... })' theo kiểu checker đã suy luận.
            gt = getattr(e, "gtype", None)
            init = self.gen_array_init(e)
            if gt is not None and gt.kind == "array" and e.elements:
                ty = self._gtype_to_ctype_decl(gt)
                return f"(({self.c_decl('', ty)}){init})"
            return init
        if isinstance(e, A.StructLit):
            return self.gen_struct_lit(e)
        raise CodegenError(f"biểu thức chưa hỗ trợ: {e}")

    @staticmethod
    def _is_addressable(e) -> bool:
        """Biểu thức có phải ô nhớ lấy địa chỉ được (lvalue) trong C không?
        Biến/trường/phần tử/deref và compound literal là lvalue; còn lời gọi,
        ternary, ép kiểu... là rvalue (không thể '&')."""
        if isinstance(e, A.Ident):
            # Tên biến thể enum trần ('Red') là hằng — không phải ô nhớ.
            return not getattr(e, "is_enum_variant", False)
        if isinstance(e, A.FieldAccess):
            return getattr(e, "enum_variant", None) is None   # 'Color.Red' là hằng
        if isinstance(e, (A.Index, A.StructLit)):
            return True
        return isinstance(e, A.Unary) and e.op == "*"

    @staticmethod
    def _is_stringy(t) -> bool:
        """Kiểu có phải 'chuỗi C' không (str hoặc *char)? Dùng để so sánh '=='/
        '!=' theo NỘI DUNG (g_str_eq) thay vì so địa chỉ con trỏ. KHÔNG tính
        'null' để 's == null' vẫn là phép kiểm tra con trỏ NULL thông thường."""
        if t is None:
            return False
        return t.kind == "str" or (
            t.kind == "ptr" and t.elem is not None and t.elem.kind == "char")

    def _where(self, node) -> str:
        """Chuỗi C literal 'file:dòng:cột' cho thông điệp panic lúc chạy."""
        f = getattr(self, "cur_src_file", None) or "?"
        f = f.replace("\\", "/").split("/")[-1]
        return f'"{f}:{getattr(node, "line", 0)}:{getattr(node, "col", 0)}"'

    def gen_call(self, e: A.Call):
        # method TĨNH: Type.name(args) -> Type__name(args)
        if getattr(e, "is_static_method", False):
            arg_c = [self.gen_expr(a) for a in e.args]
            return f"{self.cn(e.struct)}__{e.method}({', '.join(arg_c)})"
        # method DỰNG SẴN của 'str': 's.upper()' -> g_str_upper(s) (receiver là
        # tham số đầu). Chỉ là đường cú pháp cho hàm runtime.
        if getattr(e, "is_str_method", False):
            args = [self.gen_expr(e.recv)] + [self.gen_expr(a) for a in e.args]
            # 's.at(i)' đi qua macro có kiểm biên (tắt cùng '--no-checks' như
            # 'a[i]'), thay vì trả '\0' âm thầm khi i ngoài chuỗi.
            if e.str_c_fn == "g_str_at":
                return f"g_str_at_c({', '.join(args)}, {self._where(e)})"
            return f"{e.str_c_fn}({', '.join(args)})"
        # method call (đã phân giải trong checker)
        if getattr(e, "is_method", False):
            recv_c = self.gen_expr(e.recv)
            arg_c = [self.gen_expr(a) for a in e.args]
            addressable = e.recv_is_ptr or self._is_addressable(e.recv)
            # Ép thứ tự TRÁI-SANG-PHẢI (recv rồi từng đối số) khi: recv là rvalue
            # (bắt buộc vật hoá để lấy '&'), HOẶC có tác dụng phụ giữa recv/đối số.
            ordered = (not addressable
                       or self._args_need_ordering(e.args)
                       or (self._has_call(e.recv) and e.args))
            if not ordered:
                # Ép '(Struct*)' để xoá 'const' khi recv là binding 'let' (bất
                # biến); checker đã cấm method GHI vào self trên recv bất biến.
                ptr = (f"({self.cn(e.struct)}*)({recv_c})" if e.recv_is_ptr
                       else f"({self.cn(e.struct)}*)&({recv_c})")
                return f"{self.cn(e.struct)}__{e.method}({', '.join([ptr] + arg_c)})"
            decls = []
            if e.recv_is_ptr:
                rp = self.tmp("_grp")
                decls.append(f"{self.cn(e.struct)}* {rp} = ({self.cn(e.struct)}*)({recv_c});")
            elif self._is_addressable(e.recv):
                rp = self.tmp("_grp")
                decls.append(f"{self.cn(e.struct)}* {rp} = ({self.cn(e.struct)}*)&({recv_c});")
            else:
                # recv là rvalue (vd b.add(1).add(2)): vật hoá vào biến tạm rồi
                # lấy địa chỉ — '&' trên rvalue là không hợp lệ trong C.
                rv = self.tmp("_grecv")
                decls.append(f"{self.cn(e.struct)} {rv} = ({recv_c});")
                rp = "&" + rv
            names = []
            for c in arg_c:
                n = self.tmp("_gca")
                decls.append(f"__auto_type {n} = ({c});")
                names.append(n)
            call = f"{self.cn(e.struct)}__{e.method}({', '.join([rp] + names)})"
            return f"({{ {' '.join(decls)} {call}; }})"
        # builtin
        if isinstance(e.func, A.Ident):
            name = e.func.name
            if name in ("print", "println", "eprint", "eprintln"):
                return self.gen_print(e, name)
            if name == "format":
                return self.gen_format(e)
            if name == "len":
                return self.gen_len(e)
            if name == "assert":
                return self.gen_assert(e)
            if name in self._CMP_BUILTINS:
                return self.gen_assert_cmp(e, name)
            if name == "test_summary":
                return "g_test_summary()"
            if name == "panic":
                msg = self.gen_expr(e.args[0]) if e.args else '"panic"'
                return f"g_panic({msg})"
            if name in ("unreachable", "todo"):
                loc = self.gen_expr(e.args[0]) if e.args else self.c_string(
                    f"{name}() tại {getattr(e, 'line', 0)}")
                return f"g_{name}({loc})"
            if name == "typeof":
                # Hằng chuỗi: tên kiểu suy luận của đối số (không đánh giá đối số).
                gt = self.gtype_of(e.args[0]) if e.args else T.UNKNOWN
                return self.c_string(str(gt))
            if name == "dbg":
                # Vật hoá x MỘT lần, in '[dbg dòng N] <giá trị>' ra stderr theo kiểu
                # suy luận, rồi trả lại x (xuyên suốt). Dùng _fmt_placeholder để có
                # đúng specifier + ép kiểu như print.
                arg = e.args[0]
                ce = self.gen_expr(arg)
                tv = self.tmp("_gdbg")
                line = getattr(e, "line", 0)
                gt = self.gtype_of(arg)
                if gt.kind == "array" and isinstance(gt.n, int):
                    # Mảng: không vật hoá (sẽ phân rã thành con trỏ) — dùng thẳng
                    # biểu thức, vốn là một lvalue ổn định.
                    frag, cargs = self._gtype_print_frag(gt, f"({ce})")
                    fmt = self.c_string(f"[dbg dòng {line}] {frag}\n")
                    tail = (", " + ", ".join(cargs)) if cargs else ""
                    return f"({{ fprintf(stderr, {fmt}{tail}); {ce}; }})"
                if (gt.kind == "struct" and gt.name in self.struct_defs
                        or gt.kind == "slice"):
                    frag, cargs = self._gtype_print_frag(gt, tv)
                    fmt = self.c_string(f"[dbg dòng {line}] {frag}\n")
                    tail = (", " + ", ".join(cargs)) if cargs else ""
                else:
                    spec, carg = self._fmt_placeholder("", arg, tv)
                    fmt = self.c_string(f"[dbg dòng {line}] {spec}\n")
                    tail = f", {carg}" if carg is not None else ""
                return (f"({{ __auto_type {tv} = ({ce}); "
                        f"fprintf(stderr, {fmt}{tail}); {tv}; }})")
            if name == "swap":
                # Lấy ĐỊA CHỈ hai ô nhớ một lần rồi tráo qua biến tạm — an toàn cả
                # khi đối số có tác dụng phụ (vd swap(a[i()], a[j()])).
                a = self.gen_expr(e.args[0])
                b = self.gen_expr(e.args[1])
                pa, pb, tv = self.tmp("_gpa"), self.tmp("_gpb"), self.tmp("_gtv")
                return (f"({{ __auto_type {pa} = &({a}); __auto_type {pb} = &({b}); "
                        f"__auto_type {tv} = *{pa}; *{pa} = *{pb}; *{pb} = {tv}; }})")
            if name in ("min", "max"):
                op = "<" if name == "min" else ">"
                a, b = e.args[0], e.args[1]
                ca, cb = self.gen_expr(a), self.gen_expr(b)
                if self._has_call(a) or self._has_call(b):
                    # có tác dụng phụ -> statement-expression, đánh giá đúng MỘT lần
                    ta, tb = self.tmp("_ga"), self.tmp("_gb")
                    return (f"({{ __auto_type {ta} = ({ca}); __auto_type {tb} = ({cb}); "
                            f"({ta} {op} {tb}) ? {ta} : {tb}; }})")
                return f"(({ca}) {op} ({cb}) ? ({ca}) : ({cb}))"
            if name == "abs":
                a = e.args[0]
                ca = self.gen_expr(a)
                if self._has_call(a):
                    ta = self.tmp("_ga")
                    return f"({{ __auto_type {ta} = ({ca}); {ta} < 0 ? -{ta} : {ta}; }})"
                return f"(({ca}) < 0 ? -({ca}) : ({ca}))"
            if name == "clamp":
                x, lo, hi = e.args[0], e.args[1], e.args[2]
                cx, cl, ch = self.gen_expr(x), self.gen_expr(lo), self.gen_expr(hi)
                if self._has_call(x) or self._has_call(lo) or self._has_call(hi):
                    tx, tl, th = self.tmp("_gx"), self.tmp("_gl"), self.tmp("_gh")
                    return (f"({{ __auto_type {tx} = ({cx}); __auto_type {tl} = ({cl}); "
                            f"__auto_type {th} = ({ch}); "
                            f"{tx} < {tl} ? {tl} : ({tx} > {th} ? {th} : {tx}); }})")
                return (f"(({cx}) < ({cl}) ? ({cl}) : "
                        f"(({cx}) > ({ch}) ? ({ch}) : ({cx})))")
            if name in ("g_alloc", "g_realloc"):
                # Vị trí đối-số-kiểu: g_alloc(T, n) -> 0; g_realloc(p, T, n) -> 1.
                type_idx = 0 if name == "g_alloc" else 1
                parts = []
                for i, a in enumerate(e.args):
                    if i == type_idx:
                        parts.append(self._type_expr_to_c(a))
                    else:
                        parts.append(self.gen_expr(a))
                return f"{name}({', '.join(parts)})"
            if name in self._OS_BUILTINS:
                return self._gen_os_call(e, name)
        fn = self.gen_expr(e.func)
        arg_cs = [self.gen_expr(a) for a in e.args]
        # Ép đánh giá TRÁI-SANG-PHẢI khi cần: vật hoá callee (nếu có tác dụng phụ)
        # rồi từng đối số vào biến tạm, theo đúng thứ tự nguồn.
        callee_side = self._has_call(e.func)
        if self._args_need_ordering(e.args) or (callee_side and e.args):
            decls = []
            callee = fn
            if callee_side:
                ct = self.tmp("_gfp")
                decls.append(f"__auto_type {ct} = ({fn});")
                callee = ct
            names = []
            for c in arg_cs:
                n = self.tmp("_gca")
                decls.append(f"__auto_type {n} = ({c});")
                names.append(n)
            return f"({{ {' '.join(decls)} {callee}({', '.join(names)}); }})"
        return f"{fn}({', '.join(arg_cs)})"

    def _type_expr_to_c(self, arg) -> str:
        """Render đối-số-là-kiểu (cho g_alloc/g_realloc) thành tên kiểu C.
        Tên trần -> ánh xạ C; '*T' (Unary '*') -> 'T*'. Fallback: gen_expr."""
        if isinstance(arg, A.Unary) and arg.op == "*":
            return self._type_expr_to_c(arg.operand) + "*"
        if isinstance(arg, A.Ident):
            return TYPE_MAP.get(arg.name) or self.cn(arg.name)
        return self.gen_expr(arg)

    def gen_len(self, e: A.Call):
        arg = e.args[0]
        gt = self.gtype_of(arg)
        # Mảng literal: độ dài biết lúc biên dịch (sizeof trên '{...}' không hợp lệ).
        if isinstance(arg, A.ArrayLit):
            return str(len(arg.elements))
        if gt.kind == "array" and gt.n not in (None, "dyn"):
            return str(gt.n)
        c = self.gen_expr(arg)
        if gt.kind == "slice":
            return f"({c}).len"          # độ dài mang theo trong chính slice
        if gt.kind == "str":
            return f"strlen({c})"
        return f"(sizeof({c}) / sizeof(({c})[0]))"

    def gen_assert(self, e: A.Call):
        cond = self.gen_expr(e.args[0])
        if len(e.args) > 1:
            msg = self.gen_expr(e.args[1])
        else:
            msg = self.c_string(f"assertion failed: {cond}")
        return f"(({cond}) ? (void)0 : g_panic({msg}))"

    # Họ builtin so sánh + ánh xạ hậu tố -> toán tử thứ tự (cho _gen_ord).
    _ASSERT_OPS = {"lt": "<", "le": "<=", "gt": ">", "ge": ">="}
    _CMP_BUILTINS = {
        "assert_eq", "assert_ne", "assert_lt", "assert_le", "assert_gt", "assert_ge",
        "check_eq", "check_ne", "check_lt", "check_le", "check_gt", "check_ge",
    }

    def gen_assert_cmp(self, e: A.Call, fname):
        """assert_* (dừng khi sai) và check_* (ghi nhận rồi tiếp tục, trả về bool)
        cho cả so sánh BẰNG/KHÁC (eq/ne) lẫn THỨ TỰ (lt/le/gt/ge). Hiển thị 'trái'/
        'phải' GENERIC cho mọi kiểu (vô hướng/chuỗi/enum/struct lồng) qua hạ tầng
        định dạng; đánh giá mỗi vế đúng MỘT lần (vật hoá vào biến tạm). Ra stderr để
        không lẫn output chương trình."""
        suffix = fname.rsplit("_", 1)[1]                # eq/ne/lt/le/gt/ge
        is_check = fname.startswith("check")
        a, b = e.args[0], e.args[1]
        gt = self.gtype_of(a)
        l, r = self.tmp("_gel"), self.tmp("_ger")
        line = getattr(e, "line", 0)
        if suffix == "eq":
            passed = self._gen_eq(gt, l, r)             # điều kiện ĐẠT
        elif suffix == "ne":
            passed = f"(!({self._gen_eq(gt, l, r)}))"
        else:                                            # lt/le/gt/ge: so thứ tự
            passed = self._gen_ord(gt, l, r, self._ASSERT_OPS[suffix])
        lfmt, largs = self._gtype_print_frag(gt, l)
        rfmt, rargs = self._gtype_print_frag(gt, r)
        decls = f"__auto_type {l} = ({self.gen_expr(a)}); " \
                f"__auto_type {r} = ({self.gen_expr(b)});"
        red = r'g_tcolor("\033[1;31m")'
        green = r'g_tcolor("\033[32m")'
        rst = r'g_tcolor("\033[0m")'
        if is_check:
            name_c = (self.gen_expr(e.args[2]) if len(e.args) > 2
                      else self.c_string(fname))
            ok = self.tmp("_gok")
            ok_fmt = self.c_string("%s✓ %s%s\n")           # màu, tên, reset
            fparts = [f"%s✗ %s (dòng {line})%s\n",
                      "    trái:  ", lfmt, "\n", "    phải:  ", rfmt, "\n"]
            fail_fmt = self.c_string("".join(fparts))
            fail_args = ", ".join([red, name_c, rst] + largs + rargs)
            return (f"({{ {decls} bool {ok} = {passed}; g_test_record({ok}); "
                    f"if ({ok}) fprintf(stderr, {ok_fmt}, {green}, {name_c}, {rst}); "
                    f"else fprintf(stderr, {fail_fmt}, {fail_args}); {ok}; }})")
        # assert_eq/assert_ne: in khối trái/phải rồi DỪNG chương trình (exit 101).
        parts = [f"%s✗ {fname} thất bại (dòng {line})%s\n",
                 "    trái:  ", lfmt, "\n", "    phải:  ", rfmt, "\n"]
        all_args = [red, rst] + list(largs) + list(rargs)
        if len(e.args) > 2:
            parts += ["    ", "%s", "\n"]
            all_args.append(self.gen_expr(e.args[2]))
        fail_fmt = self.c_string("".join(parts))
        tail = ", " + ", ".join(all_args)
        return (f"({{ {decls} if (!({passed})) {{ "
                f"fprintf(stderr, {fail_fmt}{tail}); exit(101); }} }})")

    def gen_print(self, e: A.Call, name):
        stream = "stderr" if name.startswith("e") else "stdout"
        newline = name.endswith("ln")
        if not e.args:
            return f"fprintf({stream}, {self.c_string(chr(10) if newline else '')})"
        first = e.args[0]
        if isinstance(first, A.StrLit):
            template = first.value
            value_args = e.args[1:]
        else:
            template = "{}"
            value_args = e.args
        # Đánh giá đối số TRÁI-SANG-PHẢI khi có tác dụng phụ (như format()): vật
        # hoá vào biến tạm theo thứ tự nguồn rồi mới truyền cho fprintf — tránh
        # thứ tự đối số không xác định của C ('print("{} {}", f(), g())'). Cũng vật
        # hoá khi có đối số STRUCT (để base ổn định khi bung từng trường một lần).
        has_struct = any(self.gtype_of(a).kind == "struct" for a in value_args)
        if self._args_need_ordering(value_args) or has_struct:
            decls = []
            temps = []
            for a in value_args:
                # Mảng KHÔNG vật hoá được: '__auto_type t = a' phân rã thành con
                # trỏ và mất cỡ. Mảng luôn là lvalue ổn định (không hàm nào trả
                # mảng theo giá trị) nên dùng thẳng biểu thức là an toàn.
                if self.gtype_of(a).kind == "array":
                    temps.append(self.gen_expr(a))
                    continue
                tv = self.tmp("_gpa")
                decls.append(f"__auto_type {tv} = ({self.gen_expr(a)});")
                temps.append(tv)
            fmt, c_args = self.build_format(template, value_args, newline,
                                           arg_cexprs=temps)
            tail = (", " + ", ".join(c_args)) if c_args else ""
            return (f"({{ {' '.join(decls)} "
                    f"fprintf({stream}, {fmt}{tail}); }})")
        fmt, c_args = self.build_format(template, value_args, newline)
        if c_args:
            return f"fprintf({stream}, {fmt}, {', '.join(c_args)})"
        return f"fprintf({stream}, {fmt})"

    def gen_format(self, e: A.Call):
        """format("...", a, b) -> chuỗi MỚI trên heap (kiểu Zig std.fmt; nhớ g_free).
        Vật hoá đối số vào biến tạm (đánh giá đúng MỘT lần dù dùng 2 lần trong
        snprintf), đo độ dài bằng snprintf(NULL,0,...) rồi cấp phát vừa khít."""
        template = e.args[0].value
        value_args = e.args[1:]
        decls = []
        temps = []
        for a in value_args:
            tv = self.tmp("_gfa")
            decls.append(f"__auto_type {tv} = ({self.gen_expr(a)});")
            temps.append(tv)
        fmt, c_args = self.build_format(template, value_args, newline=False,
                                        arg_cexprs=temps)
        n = self.tmp("_gfn")
        buf = self.tmp("_gfb")
        tail = (", " + ", ".join(c_args)) if c_args else ""
        body = (" ".join(decls) + " ") if decls else ""
        return ("({ " + body +
                f"int {n} = snprintf(NULL, 0, {fmt}{tail}); "
                f"char* {buf} = (char*)malloc((size_t){n} + 1); "
                f"if ({buf}) snprintf({buf}, (size_t){n} + 1, {fmt}{tail}); "
                f"(const char*){buf}; }})")

    # key tường minh -> (specifier, kiểu_ép). Ép kiểu để specifier luôn KHỚP
    # đối số trên mọi nền tảng (int64_t có thể là 'long' hoặc 'long long').
    # Dùng biến thể 'll' cho hex/oct để không cắt cụt giá trị 64-bit.
    SPEC_MAP = {
        "d":  ("%d",   "int"),
        "ld": ("%lld", "long long"),
        "u":  ("%u",   "unsigned"),
        "lu": ("%llu", "unsigned long long"),
        "f":  ("%g",   "double"),
        "lf": ("%f",   "double"),
        "g":  ("%g",   "double"),
        "e":  ("%e",   "double"),
        "s":  ("%s",   None),
        "c":  ("%c",   "int"),
        "x":  ("%llx", "unsigned long long"),
        "X":  ("%llX", "unsigned long long"),
        "o":  ("%llo", "unsigned long long"),
        "lx": ("%llx", "unsigned long long"),
        "lX": ("%llX", "unsigned long long"),
        "lo": ("%llo", "unsigned long long"),
        "lg": ("%g",   "double"),
        "le": ("%e",   "double"),
        "p":  ("%p",   "void*"),
    }

    @staticmethod
    def _apply_fmt_flags(spec, flags):
        """Chèn width/precision/căn lề/dấu (kiểu Zig/Rust) vào một printf specifier.
        flags: [<|>|^][+| ]?[#]?[0]?[width]?(.prec)?  ví dụ '5', '<8', '08', '.2',
        '8.3', '+', '+08', '#x', '+.2'.
          '<' = căn trái (-), '>'/'^' = mặc định;
          '+' = luôn in dấu, ' ' = chèn khoảng trắng cho số dương;
          '#' = dạng thay thế (tiền tố 0x/0o cho hex/oct);
          '0' = đệm số 0.
        Float có precision: %g -> %f (precision = số chữ số sau dấu phẩy)."""
        align = ""
        i = 0
        if i < len(flags) and flags[i] in "<>^":
            align = "-" if flags[i] == "<" else ""
            i += 1
        sign = ""           # '+' luôn in dấu; ' ' chèn khoảng trắng cho số dương
        if i < len(flags) and flags[i] in "+ ":
            sign = flags[i]; i += 1
        alt = ""            # '#' -> dạng thay thế (0x/0o)
        if i < len(flags) and flags[i] == "#":
            alt = "#"; i += 1
        zero = ""
        if i < len(flags) and flags[i] == "0":
            zero = "0"
            i += 1
        width = ""
        while i < len(flags) and flags[i].isdigit():
            width += flags[i]; i += 1
        prec = ""
        if i < len(flags) and flags[i] == ".":
            prec = "."
            i += 1
            while i < len(flags) and flags[i].isdigit():
                prec += flags[i]; i += 1
        rest = spec[1:]   # length-modifier + conversion (vd 'lld', 'g', 's')
        if prec and rest and rest[-1] == "g":
            rest = rest[:-1] + "f"
        return "%" + align + sign + alt + zero + width + prec + rest

    # Chữ kiểu đơn (cho phép đặt SAU dấu ':' kiểu Rust: '{:x}', '{:08x}', '{:.2f}').
    _FMT_TYPE_CHARS = set("duxXofgescb")

    def _fmt_placeholder(self, key, arg, ce=None):
        """Trả về (specifier, c_arg | None) cho một placeholder, kèm ép kiểu
        để printf luôn nhận đúng kiểu (an toàn đa nền tảng).
        Hỗ trợ '{key:flags}' với flags width/precision/căn lề/dấu.
        'ce' (tuỳ chọn): biểu thức C của đối số đã tính sẵn (vd biến tạm trong
        format()) — nếu None thì sinh trực tiếp từ 'arg'."""
        key, sep, flags = key.partition(":")
        if sep:
            # Hỗ trợ CẢ hai quy ước: '{x:08}' (chữ kiểu TRƯỚC ':') và '{:08x}'
            # (kiểu Rust — chữ kiểu ở CUỐI cờ). Khi key rỗng/'v' và cờ kết thúc
            # bằng một chữ kiểu, tách nó ra làm key. Nhờ vậy '{:x}'/'{:.2f}' hoạt
            # động như Rust thay vì âm thầm rơi về thập phân.
            if key in ("", "v") and flags and flags[-1] in self._FMT_TYPE_CHARS:
                key, flags = flags[-1], flags[:-1]
            spec, carg = self._fmt_placeholder(key, arg, ce)
            # '{:08b}' trên số: đệm số 0 bằng chính bề rộng nhị phân (printf
            # không đệm '0' cho %s). Các cờ khác (căn lề/width) vẫn qua %s.
            if key == "b" and carg is not None and carg.startswith("g_bin_str("):
                m = re.match(r"^[<>^]?0(\d+)$", flags)
                if m:
                    carg = carg[:carg.rfind(",")] + f", {m.group(1)})"
                    flags = ""
            # '^' = CĂN GIỮA (Rust): printf không có — kết xuất giá trị ra chuỗi
            # rồi đệm hai bên bằng g_center(). Trước đây '^' bị bỏ qua âm thầm và
            # in ra căn phải.
            m = re.match(r"^\^(.*)$", flags)
            if m and carg is not None:
                rest = m.group(1)
                mw = re.match(r"^[+ ]?#?0?(\d+)(\.\d+)?$", rest)
                if mw:
                    width = mw.group(1)
                    inner = self._apply_fmt_flags(spec, rest.replace(width, "", 1))
                    return "%s", f"g_center(g_fmt1({self.c_string(inner)}, {carg}), {width})"
            return self._apply_fmt_flags(spec, flags), carg
        if ce is None:
            ce = self.gen_expr(arg) if arg is not None else None
        # '{b}': bool -> true/false; SỐ NGUYÊN -> nhị phân (kiểu Rust '{:b}').
        # Trước đây '{:b}' trên 5 in ra 'true' — âm thầm sai nghĩa.
        if key == "b":
            gt = self.gtype_of(arg) if arg is not None else T.UNKNOWN
            if gt.kind in ("int", "char", "enum"):
                if ce is None:
                    return "%s", None
                # Số âm: in bù hai theo đúng bề rộng kiểu; không âm: tối giản.
                bits = gt.bits if gt.kind == "int" else (8 if gt.kind == "char" else 32)
                signed = gt.signed if gt.kind == "int" else True
                width = f"(({ce}) < 0 ? {bits} : 0)" if signed else "0"
                return "%s", f"g_bin_str((uint64_t)({ce}), {width})"
            if ce is not None:
                return "%s", f"(({ce}) ? \"true\" : \"false\")"
            return "%s", None
        # tự suy luận theo kiểu đối số
        if key in ("", "v"):
            gt = self.gtype_of(arg) if arg is not None else T.UNKNOWN
            # enum -> in TÊN biến thể (Red) thay vì số ('{d}' vẫn in số nguyên).
            if gt.kind == "enum" and gt.name in self.enum_names:
                if ce is None:
                    return "%s", None
                return "%s", f"{self._enum_name_fn(gt.name)}({ce})"
            spec, is_bool = T.printf_spec(gt)
            if ce is None:
                return spec, None
            if is_bool:
                return spec, f"(({ce}) ? \"true\" : \"false\")"
            cast = self._spec_cast(spec)
            return spec, (f"({cast})({ce})" if cast else ce)
        # specifier tường minh
        if key in self.SPEC_MAP:
            spec, cast = self.SPEC_MAP[key]
            if ce is None:
                return spec, None
            return spec, (f"({cast})({ce})" if cast else ce)
        # key lạ -> coi như tự suy luận
        gt = self.gtype_of(arg) if arg is not None else T.UNKNOWN
        spec, is_bool = T.printf_spec(gt)
        if ce is None:
            return spec, None
        if is_bool:
            return spec, f"(({ce}) ? \"true\" : \"false\")"
        cast = self._spec_cast(spec)
        return spec, (f"({cast})({ce})" if cast else ce)

    @staticmethod
    def _spec_cast(spec):
        """Kiểu C cần ép cho một specifier do printf_spec sinh ra."""
        return {
            "%d": "int", "%u": "unsigned",
            "%lld": "long long", "%llu": "unsigned long long",
            "%g": "double", "%c": "int", "%p": "void*",
        }.get(spec)   # %s -> None (không ép)

    def _slice_print_fn(self, gt: T.GType) -> str:
        """Đăng ký (nếu chưa có) hàm in cho 'slice<T>', trả về tên hàm.

        In ra '[a, b, c]' vào bộ đệm xoay vòng tĩnh (không cần g_free), cắt bớt
        sau _PRINT_ARRAY_MAX phần tử — giống cách in mảng tĩnh."""
        sname = self._slice_typedef_gt(gt)
        fn = self.slice_print_fns.get(sname)
        if fn is not None:
            return fn
        fn = f"_gslprint_{sname}"
        self.slice_print_fns[sname] = fn
        frag, cargs = self._gtype_print_frag(gt.elem, "s.ptr[i]")
        args = (", " + ", ".join(cargs)) if cargs else ""
        cap = self._PRINT_ARRAY_MAX
        self.slice_print_decls += [
            f"static const char* {fn}({sname} s) {{",
            "    static char bufs[4][512]; static unsigned bi = 0;",
            "    char* b = bufs[bi++ & 3]; size_t off = 0;",
            "    off += (size_t)snprintf(b + off, sizeof(bufs[0]) - off, \"[\");",
            f"    size_t shown = s.len < {cap} ? s.len : {cap};",
            "    for (size_t i = 0; i < shown; i++) {",
            "        if (i) off += (size_t)snprintf(b + off, sizeof(bufs[0]) - off, \", \");",
            f'        off += (size_t)snprintf(b + off, sizeof(bufs[0]) - off, "{frag}"{args});',
            "    }",
            "    if (shown < s.len)",
            "        off += (size_t)snprintf(b + off, sizeof(bufs[0]) - off,",
            '                                ", ... (%zu phần tử)", s.len);',
            "    snprintf(b + off, sizeof(bufs[0]) - off, \"]\");",
            "    return b;",
            "}",
        ]
        return fn

    def _gtype_array_frag(self, gt: T.GType, cexpr):
        """(đoạn_fmt, [c_args]) cho một MẢNG cỡ tĩnh: '[v0, v1, ...]'. Đệ quy cho
        mảng nhiều chiều và cho phần tử struct/enum. Cắt bớt sau _PRINT_ARRAY_MAX
        phần tử để chuỗi định dạng C không phình vô hạn."""
        n = gt.n
        parts = ["["]
        cargs = []
        shown = min(n, self._PRINT_ARRAY_MAX)
        for i in range(shown):
            if i:
                parts.append(", ")
            frag, fa = self._gtype_print_frag(gt.elem, f"({cexpr})[{i}]")
            parts.append(frag)
            cargs += fa
        if shown < n:
            parts.append(f", ... ({n} phần tử)")
        parts.append("]")
        return "".join(parts), cargs

    def _struct_print_fragment(self, sname, base):
        """(đoạn_fmt, [c_args]) để in một struct dạng 'Tên { f: v, ... }'. 'base'
        là biểu thức C của giá trị struct (ổn định, không tác dụng phụ — đã vật
        hoá vào biến tạm). Đệ quy cho trường struct lồng; con trỏ -> %p (hoặc %s
        nếu '*char'); mảng/con trỏ hàm -> nhãn rút gọn để không bao giờ sinh C sai."""
        sdef = self.struct_defs.get(sname)
        if sdef is None or not sdef.fields:
            return f"{sname} {{}}", []
        parts = [f"{sname} {{ "]
        cargs = []
        for i, f in enumerate(sdef.fields):
            if i:
                parts.append(", ")
            frag, fa = self._field_print_frag(f.type, f"({base}).{self.cn(f.name)}")
            parts.append(f"{f.name}: ")
            parts.append(frag)
            cargs += fa
        parts.append(" }")
        return "".join(parts), cargs

    # Số phần tử tối đa được BUNG khi in một trường mảng của struct; dài hơn thì
    # in phần đầu rồi '...' (giữ chuỗi định dạng C ở kích thước hợp lý).
    _PRINT_ARRAY_MAX = 8

    def _field_print_frag(self, t: A.Type, fexpr):
        """(đoạn_fmt, [c_args]) cho MỘT trường khi in struct, dựa trên A.Type."""
        dims = self._dims(t)
        if dims:
            # Mảng cỡ TĨNH: bung thành '[a, b, c]' (đệ quy cho mảng nhiều chiều)
            # thay vì nhãn '[…]' vô nghĩa. Cỡ động ('dyn') vẫn là nhãn rút gọn.
            if all(isinstance(d, int) for d in dims):
                return self._array_print_frag(t, dims, fexpr)
            return "[…]", []
        if getattr(t, "is_fn", False):
            return "<fn>", []
        return self._scalar_print_frag(t, fexpr)

    def _array_print_frag(self, t: A.Type, dims, fexpr):
        """Bung một trường mảng cỡ tĩnh thành '[v0, v1, ...]' (đệ quy nhiều chiều)."""
        n = dims[0]
        inner = dataclasses.replace(t, dims=(list(dims[1:]) or None),
                                    array=(dims[1] if len(dims) > 1 else None))
        parts = ["["]
        cargs = []
        shown = min(n, self._PRINT_ARRAY_MAX)
        for i in range(shown):
            if i:
                parts.append(", ")
            if len(dims) > 1:
                frag, fa = self._array_print_frag(inner, dims[1:], f"({fexpr})[{i}]")
            else:
                frag, fa = self._scalar_print_frag(t, f"({fexpr})[{i}]")
            parts.append(frag)
            cargs += fa
        if shown < n:
            parts.append(f", ... ({n} phần tử)")
        parts.append("]")
        return "".join(parts), cargs

    def _scalar_print_frag(self, t: A.Type, fexpr):
        """(đoạn_fmt, [c_args]) cho một giá trị KHÔNG phải mảng (phần tử/trường)."""
        if t.ptr > 0 or getattr(t, "elem_ptr", 0) > 0:
            if t.name == "char" and t.ptr == 1:    # *char -> chuỗi
                return "%s", [f"({fexpr})"]
            return "%p", [f"(void*)({fexpr})"]
        if t.name in self.struct_defs:             # struct lồng -> đệ quy
            return self._struct_print_fragment(t.name, fexpr)
        if t.name in self.enum_names:              # enum -> TÊN biến thể
            return "%s", [f"{self._enum_name_fn(t.name)}({fexpr})"]
        if t.name == "str":
            return "%s", [fexpr]
        gt = T.PRIMITIVES.get(t.name)
        if gt is None:                             # kiểu khác -> số nguyên
            return "%d", [f"(int)({fexpr})"]
        spec, is_bool = T.printf_spec(gt)
        if is_bool:
            return "%s", [f'(({fexpr}) ? "true" : "false")']
        cast = self._spec_cast(spec)
        return spec, [f"({cast})({fexpr})" if cast else fexpr]

    def build_format(self, raw, value_args, newline=False, arg_cexprs=None):
        """Sinh chuỗi định dạng C + danh sách biểu thức C tương ứng.
        Placeholder rỗng {} => tự suy ra theo kiểu của tham số.
        'arg_cexprs' (tuỳ chọn): biểu thức C đã tính sẵn cho từng đối số (vd biến
        tạm của format()), song song với value_args."""
        result = []
        c_args = []
        ai = 0
        i = 0
        n = len(raw)
        while i < n:
            ch = raw[i]
            if ch == "{" and i + 1 < n and raw[i + 1] == "{":
                result.append("{"); i += 2; continue
            if ch == "}" and i + 1 < n and raw[i + 1] == "}":
                result.append("}"); i += 2; continue
            if ch == "{":
                j = raw.find("}", i)
                if j == -1:
                    result.append("{"); i += 1; continue
                key = raw[i + 1:j]
                arg = value_args[ai] if ai < len(value_args) else None
                ce = (arg_cexprs[ai] if (arg_cexprs is not None
                                         and ai < len(arg_cexprs)) else None)
                ai += 1
                # struct với '{}'/'{v}' tự bung 'Tên { f: v, ... }'. 'base' phải
                # ổn định: dùng biến tạm (ce) nếu có, nếu không thì biểu thức trực
                # tiếp (gen_print đã vật hoá struct nên nhánh None chỉ gặp tên trần).
                gt = self.gtype_of(arg) if arg is not None else T.UNKNOWN
                if ((gt.kind == "struct" and gt.name in self.struct_defs
                     or gt.kind == "array" and isinstance(gt.n, int)
                     or gt.kind == "slice")
                        and key.partition(":")[0] in ("", "v")):
                    base = ce if ce is not None else self.gen_expr(arg)
                    frag, sargs = self._gtype_print_frag(gt, base)
                    result.append(frag)
                    c_args.extend(sargs)
                    i = j + 1
                    continue
                spec, carg = self._fmt_placeholder(key, arg, ce)
                result.append(spec)
                if carg is not None:
                    c_args.append(carg)
                i = j + 1
            elif ch == "%":
                result.append("%%"); i += 1
            else:
                result.append(ch); i += 1
        if newline:
            result.append("\n")
        return self.c_string("".join(result)), c_args

    def gen_struct_lit(self, e: A.StructLit):
        if not e.fields:
            return f"(({self.cn(e.name)}){{0}})"   # struct rỗng / khởi tạo zero
        parts = []
        for name, val in e.fields:
            # Trường mảng: initializer '{..}' trần (compound literal không hợp lệ ở đây)
            vc = self.gen_array_init(val) if isinstance(val, A.ArrayLit) else self.gen_expr(val)
            parts.append(f".{self.cn(name)} = {vc}")
        return f"(({self.cn(e.name)}){{ {', '.join(parts)} }})"

    # ---------- literal helpers ----------
    # Escape cố định cho byte điều khiển. Dùng escape BÁT PHÂN cho byte còn lại
    # vì \xNN của C *tham lam* (nuốt mọi chữ số hex theo sau) -> "\x1b" + "A"
    # sẽ thành một giá trị; \NNN bát phân tối đa 3 chữ số nên an toàn.
    _ESC_TABLE = {
        ord("\n"): "\\n", ord("\t"): "\\t", ord("\r"): "\\r",
        ord('"'): '\\"', ord("\\"): "\\\\", ord("\a"): "\\a",
        ord("\b"): "\\b", ord("\f"): "\\f", ord("\v"): "\\v",
    }

    def c_string(self, s: str) -> str:
        out = ['"']
        data = s.encode("utf-8")          # Unicode -> byte UTF-8 (C string là byte)
        for i, b in enumerate(data):
            if b in self._ESC_TABLE:
                out.append(self._ESC_TABLE[b])
            elif 32 <= b < 127:
                out.append(chr(b))
            else:
                # bát phân 3 chữ số: không bị nuốt bởi ký tự kế tiếp
                out.append(f"\\{b:03o}")
        out.append('"')
        return "".join(out)

    def c_char(self, ch: str) -> str:
        b = ch.encode("utf-8")
        if len(b) > 1:
            # ký tự ngoài ASCII: trả về điểm mã (char trong G là 1 byte/đơn vị)
            return str(ord(ch))
        v = b[0]
        special = {ord("\n"): "\\n", ord("\t"): "\\t", ord("\r"): "\\r",
                   0: "\\0", ord("'"): "\\'", ord("\\"): "\\\\"}
        if v in special:
            return f"'{special[v]}'"
        if 32 <= v < 127:
            return f"'{chr(v)}'"
        return f"'\\{v:03o}'"
