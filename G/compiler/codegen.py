"""
G Language - Code Generator: dịch AST (đã gắn kiểu) sang mã C.

Nơi 5 ngôn ngữ hội tụ:
  - Frontend Rust/Zig (let/mut, match, defer, comptime, loop)
  - Backend C/C++ (mọi thứ -> C -> mã máy)
  - ASM (inline assembly)
Tận dụng thông tin kiểu để: print tự chọn định dạng, auto-deref con trỏ, gọi method.
"""

from . import ast_nodes as A
from . import types as T


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
        self.enum_names = set()
        self.enum_variants = set()   # mọi tên variant (là hằng số C hợp lệ)
        self.global_inits = []       # (tên, biểu_thức) cho global khởi tạo lúc chạy
        self.scope_stack = []   # ngăn xếp scope cho defer (LIFO, theo block)
        self._tmp = 0

    # ---------- tiện ích ----------
    def w(self, line=""):
        self.out.append("    " * self.indent + line)

    def tmp(self, base="_g"):
        self._tmp += 1
        return f"{base}{self._tmp}"

    def c_type(self, t: A.Type) -> str:
        """Kiểu cơ sở (gồm các mức con trỏ tường minh), KHÔNG gồm phần mảng."""
        base = TYPE_MAP.get(t.name, t.name)
        base += "*" * t.ptr
        return base

    def _dims(self, t: A.Type) -> list:
        """Chuẩn hóa danh sách chiều mảng từ A.Type (gộp dims/array)."""
        if t.dims is not None:
            return list(t.dims)
        if t.array is not None:
            return [t.array]
        return []

    def c_decl(self, name, t: A.Type, init_c=None, const=False, decay_first=False):
        """Sinh khai báo C đầy đủ cho biến/trường/tham số, xử lý mảng nhiều chiều.
        decay_first=True: chiều ngoài cùng phân rã thành con trỏ (quy tắc tham số C).

        'const' đặt theo kiểu *east-const* (ngay trước tên) để bất biến áp lên
        CHÍNH biến: 'int* const p' (con trỏ bất biến, '*p' vẫn ghi được) —
        đúng ngữ nghĩa 'let' của G, khác hẳn 'const int* p' (cấm ghi '*p')."""
        cv = self.c_type(t)
        cq = "const " if const else ""   # đặt ngay trước định danh
        dims = self._dims(t)
        if decay_first and dims:
            dims = ["dyn"] + dims[1:]   # tham số: [N]... -> con trỏ tới phần còn lại
        # Tách run "dyn" dẫn đầu thành con trỏ; phần còn lại là mảng tĩnh.
        nptr = 0
        i = 0
        while i < len(dims) and dims[i] == "dyn":
            nptr += 1
            i += 1
        static_dims = dims[i:]
        if any(d == "dyn" for d in static_dims):
            # Chiều động xen giữa: phân rã toàn bộ thành con trỏ (mất kích thước tĩnh).
            decl = f"{cv}{'*' * len(dims)} {cq}{name}"
        elif nptr and static_dims:
            arr = "".join(f"[{d}]" for d in static_dims)
            decl = f"{cv} ({'*' * nptr}{cq}{name}){arr}"   # con trỏ tới mảng
        elif nptr:
            decl = f"{cv}{'*' * nptr} {cq}{name}"
        elif static_dims:
            arr = "".join(f"[{d}]" for d in static_dims)
            decl = f"{cv} {cq}{name}{arr}"
        else:
            decl = f"{cv} {cq}{name}"
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

    def emit_var_decl(self, name, t: A.Type, init_c=None, const=False):
        return self.c_decl(name, t, init_c, const=const) + ";"

    # ---------- điểm vào ----------
    def generate(self) -> str:
        self.w("// === Sinh tự động bởi trình biên dịch G ===")
        self.w('#include "g_runtime.h"')
        self.w("")

        struct_defs = {}
        for it in self.prog.items:
            if isinstance(it, A.StructDef):
                self.struct_names.add(it.name)
                struct_defs[it.name] = it
            elif isinstance(it, A.EnumDef):
                self.enum_names.add(it.name)
                for vname, _ in it.variants:
                    self.enum_variants.add(vname)

        # 1a) enum trước (struct có thể nhúng enum theo giá trị)
        for it in self.prog.items:
            if isinstance(it, A.EnumDef):
                self.gen_enum(it)

        # 1b) Khai báo tiến (forward decl) MỌI struct: cho phép tự/đệ-quy tham
        #     chiếu qua con trỏ (linked list) và tham chiếu lẫn nhau.
        if struct_defs:
            for it in self.prog.items:
                if isinstance(it, A.StructDef):
                    self.w(f"typedef struct {it.name} {it.name};")
            self.w("")

        # 1c) Định nghĩa struct theo thứ tự topo: struct nhúng struct khác THEO
        #     GIÁ TRỊ phải đứng sau struct đó (trường con trỏ không tạo ràng buộc).
        for name in self._topo_sort_structs(struct_defs):
            self.gen_struct(struct_defs[name])

        # 2) biến toàn cục
        for it in self.prog.items:
            if isinstance(it, A.GlobalVar):
                self.gen_global(it)
        self.w("")

        # 3) nguyên mẫu hàm + method
        for it in self.prog.items:
            if isinstance(it, A.Function):
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
                # phụ thuộc chỉ khi nhúng trực tiếp theo giá trị (ptr=0, không mảng-con-trỏ)
                if f.type.ptr == 0 and f.type.name in struct_defs:
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
        self.w(f"struct {s.name} {{")
        self.indent += 1
        if not s.fields:
            self.w("char _g_empty;")
        for f in s.fields:
            self.w(self.emit_var_decl(f.name, f.type))
        self.indent -= 1
        self.w("};")
        self.w("")

    def gen_enum(self, e: A.EnumDef):
        parts = []
        for vname, vval in e.variants:
            if vval is not None:
                parts.append(f"{vname} = {self.gen_expr(vval)}")
            else:
                parts.append(vname)
        self.w(f"typedef enum {{ {', '.join(parts)} }} {e.name};")
        self.w("")

    def gen_global(self, g: A.GlobalVar):
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
            self.w("static " + self.c_decl(g.name, decl_type, init,
                                           const=g.is_const) + ";")
            return

        # Initializer KHÔNG phải hằng số biên dịch (tham chiếu global khác, lời gọi
        # hàm, g_alloc...): C cấm. -> khai báo storage zero-init, gán lúc chạy trong
        # constructor. Bỏ 'const' ở mức C để gán được (G-checker vẫn cấm gán lại).
        self.w("static " + self.c_decl(g.name, decl_type, None, const=False) + ";")
        self._defer_global_init(g.name, g.value)

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
        return f"{fn.recv}__{fn.name}" if fn.recv else fn.name

    def fn_signature(self, fn: A.Function) -> str:
        parts = []
        for p in fn.params:
            parts.append(self.c_decl(p.name, p.type, decay_first=True))
        params = ", ".join(parts) if parts else "void"
        ret = self.c_type(fn.ret)
        qual = ""
        if fn.is_comptime:
            qual = "static inline "
        elif fn.is_extern:
            qual = "extern "
        return f"{qual}{ret} {self.mangle(fn)}({params})"

    def gen_fn(self, fn: A.Function):
        self.w(self.fn_signature(fn) + " {")
        self.scope_stack = []
        self.gen_scoped_body(fn.body, is_loop=False)
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
            self._emit_exit_defers("return")
            if st.value is not None:
                self.w(f"return {self.gen_expr(st.value)};")
            else:
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
        self.w(f"{tgt_c} {st.op} {val_c};")

    def gen_let(self, st: A.Let):
        const = not st.mutable
        name = getattr(st, "c_name", st.name)
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

        init_c = self.gen_expr(st.value) if st.value is not None else None
        if st.type is not None:
            self.w(self.c_decl(name, st.type, init_c, const=const) + ";")
        else:
            if init_c is None:
                self.w(f"int {name};")
            else:
                q = "const " if const else ""
                self.w(f"{q}__auto_type {name} = {init_c};")

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
        """Điền các chiều mảng còn để trống bằng độ dài literal tương ứng."""
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
        return A.Type(decl_t.name, ptr=decl_t.ptr, dims=filled, array=filled[0])

    def _gtype_to_ctype_decl(self, gt: T.GType) -> A.Type:
        """Suy ra A.Type (cho c_decl) từ GType mảng đã suy luận (khi không có annotation)."""
        dims = []
        cur = gt
        while cur is not None and cur.kind == "array":
            dims.append(cur.n if cur.n is not None else "dyn")
            cur = cur.elem
        base = cur if cur is not None else T.INT
        ptr = 0
        while base.kind == "ptr":
            ptr += 1
            base = base.elem
        name = base.name if base.name else base.kind
        return A.Type(name, ptr=ptr, dims=dims or None,
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
        self.w(f"__auto_type {end} = ({self.gen_expr(st.end)});")
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
                self.gen_scoped_body(st.body, is_loop=True,
                                     prologue=[self._elem_decl(var, elem_type,
                                                               f"({arr})[{i}]")])
                self.w("}")

    def gen_match(self, st: A.Match):
        subj_t = self.gtype_of(st.subject)
        is_str = subj_t.kind == "str" or (subj_t.kind == "ptr" and subj_t.elem and subj_t.elem.kind == "char")
        tmp = self.tmp("_gm")
        ctype = T.c_type(subj_t) if subj_t.kind != "unknown" else "__auto_type"
        if ctype == "__auto_type":
            self.w(f"{{ __auto_type {tmp} = {self.gen_expr(st.subject)};")
        else:
            self.w(f"{{ {ctype} {tmp} = {self.gen_expr(st.subject)};")
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
            return " || ".join(tests)

        bindings = getattr(st, "bindings", [None] * len(st.arms))
        # Binding pattern (kiểu Rust 'x =>' / 'x if x>0 =>'): bắt subject vào biến.
        # Khai báo MỘT lần ở scope match (giá trị subject đã ở 'tmp'), để guard và
        # thân nhánh dùng được; mỗi nhánh binding gán lại tên đó.
        bctype = ctype if ctype != "__auto_type" else "__auto_type"

        first = True
        default_body = None
        default_bind = None
        for (pats, guard, body), bcname in zip(st.arms, bindings):
            is_bind = bcname is not None
            # Mặc định tuyệt đối: '_' hoặc binding, đều KHÔNG guard -> để cuối.
            if (pats is None or is_bind) and guard is None:
                default_body = body
                default_bind = bcname
                continue
            kw = "if" if first else "else if"
            first = False
            if is_bind:
                # binding + guard: luôn khớp pattern, lọc bằng guard. Cần đưa biến
                # binding vào phạm vi trước khi tính guard -> dùng khối + cờ.
                self.w(f"{kw} (1) {{")
                self.indent += 1
                self.w(f"{bctype} {bcname} = {tmp}; (void){bcname};")
                self.w(f"if ({self.gen_expr(guard)}) {{")
                self.gen_scoped_body(body, is_loop=False)
                self.w("} else goto {0};".format(self._match_next_label()))
                self.indent -= 1
                self.w("}")
                self.w(f"{self._cur_match_label}: ;")
                continue
            if pats is None:
                cond = f"({self.gen_expr(guard)})"            # '_ if g'
            elif guard is None:
                cond = cond_for(pats)
            else:
                cond = f"({cond_for(pats)}) && ({self.gen_expr(guard)})"
            self.w(f"{kw} ({cond}) {{")
            self.gen_scoped_body(body, is_loop=False)
            self.w("}")
        if default_body is not None:
            self.w("else {" if not first else "{")
            if default_bind is not None:
                self.indent += 1
                self.w(f"{bctype} {default_bind} = {tmp}; (void){default_bind};")
                self.indent -= 1
            self.gen_scoped_body(default_body, is_loop=False)
            self.w("}")
        self.indent -= 1
        self.w("}")

    def gen_asm(self, st: A.Asm):
        lines = [l.strip() for l in st.code.split("\n") if l.strip()]
        joined = "\\n\\t".join(lines)
        vol = " __volatile__" if st.volatile else ""
        self.w(f'__asm__{vol}("{joined}");')

    # ---------- biểu thức ----------
    def gen_expr(self, e) -> str:
        if isinstance(e, A.IntLit):
            return e.value
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
            return getattr(e, "c_name", "") or e.name
        if isinstance(e, A.Binary):
            lc = self.gen_expr(e.left)
            rc = self.gen_expr(e.right)
            # Modulo số thực: C cấm '%' trên double -> dùng fmod().
            if e.op == "%":
                lt = self.gtype_of(e.left)
                rt = self.gtype_of(e.right)
                if lt.kind == "float" or rt.kind == "float":
                    return f"fmod({lc}, {rc})"
            return f"({lc} {e.op} {rc})"
        if isinstance(e, A.Unary):
            return f"({e.op}{self.gen_expr(e.operand)})"
        if isinstance(e, A.Ternary):
            return f"({self.gen_expr(e.cond)} ? {self.gen_expr(e.then)} : {self.gen_expr(e.els)})"
        if isinstance(e, A.Call):
            return self.gen_call(e)
        if isinstance(e, A.Index):
            return f"{self.gen_expr(e.base)}[{self.gen_expr(e.index)}]"
        if isinstance(e, A.FieldAccess):
            arrow = getattr(e, "auto_deref", False)
            sep = "->" if arrow else "."
            return f"{self.gen_expr(e.base)}{sep}{e.field}"
        if isinstance(e, A.Cast):
            return f"(({self.c_type(e.type)})({self.gen_expr(e.expr)}))"
        if isinstance(e, A.SizeOf):
            # Kích thước phải gồm CẢ các chiều mảng: sizeof([10]int) = 10*sizeof(int).
            # c_decl với tên rỗng sinh "int [10]" / "int (*)[3]" hợp lệ trong sizeof.
            return f"sizeof({self.c_decl('', e.type)})"
        if isinstance(e, A.SizeOfExpr):
            return f"sizeof({self.gen_expr(e.expr)})"
        if isinstance(e, A.ArrayLit):
            return "{ " + ", ".join(self.gen_expr(x) for x in e.elements) + " }"
        if isinstance(e, A.StructLit):
            return self.gen_struct_lit(e)
        raise CodegenError(f"biểu thức chưa hỗ trợ: {e}")

    @staticmethod
    def _is_addressable(e) -> bool:
        """Biểu thức có phải ô nhớ lấy địa chỉ được (lvalue) trong C không?
        Biến/trường/phần tử/deref và compound literal là lvalue; còn lời gọi,
        ternary, ép kiểu... là rvalue (không thể '&')."""
        if isinstance(e, (A.Ident, A.FieldAccess, A.Index, A.StructLit)):
            return True
        return isinstance(e, A.Unary) and e.op == "*"

    def gen_call(self, e: A.Call):
        # method call (đã phân giải trong checker)
        if getattr(e, "is_method", False):
            recv_c = self.gen_expr(e.recv)
            arg_c = [self.gen_expr(a) for a in e.args]

            def call_with(ptr_c):
                return f"{e.struct}__{e.method}({', '.join([ptr_c] + arg_c)})"

            # Ép '(Struct*)' để xoá 'const' khi recv là binding 'let' (bất biến);
            # checker đã cấm method GHI vào self trên recv bất biến nên an toàn.
            if e.recv_is_ptr:
                return call_with(f"({e.struct}*)({recv_c})")
            if self._is_addressable(e.recv):
                return call_with(f"({e.struct}*)&({recv_c})")
            # recv là rvalue (vd b.add(1).add(2)): vật hoá vào biến tạm rồi lấy
            # địa chỉ — '&' trên rvalue là không hợp lệ trong C.
            tmp = self.tmp("_grecv")
            return (f"({{ {e.struct} {tmp} = ({recv_c}); "
                    f"{call_with('&' + tmp)}; }})")
        # builtin
        if isinstance(e.func, A.Ident):
            name = e.func.name
            if name in ("print", "println", "eprint", "eprintln"):
                return self.gen_print(e, name)
            if name == "len":
                return self.gen_len(e)
            if name == "assert":
                return self.gen_assert(e)
            if name == "panic":
                msg = self.gen_expr(e.args[0]) if e.args else '"panic"'
                return f"g_panic({msg})"
            if name in ("unreachable", "todo"):
                loc = self.gen_expr(e.args[0]) if e.args else self.c_string(
                    f"{name}() tại {getattr(e, 'line', 0)}")
                return f"g_{name}({loc})"
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
        fn = self.gen_expr(e.func)
        args = ", ".join(self.gen_expr(a) for a in e.args)
        return f"{fn}({args})"

    def _type_expr_to_c(self, arg) -> str:
        """Render đối-số-là-kiểu (cho g_alloc/g_realloc) thành tên kiểu C.
        Tên trần -> ánh xạ C; '*T' (Unary '*') -> 'T*'. Fallback: gen_expr."""
        if isinstance(arg, A.Unary) and arg.op == "*":
            return self._type_expr_to_c(arg.operand) + "*"
        if isinstance(arg, A.Ident):
            return TYPE_MAP.get(arg.name, arg.name)
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
        fmt, c_args = self.build_format(template, value_args, newline)
        if c_args:
            return f"fprintf({stream}, {fmt}, {', '.join(c_args)})"
        return f"fprintf({stream}, {fmt})"

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
        """Chèn width/precision/căn lề (kiểu Zig/Rust) vào một printf specifier.
        flags: [<|>|^][0]?[width]?(.prec)?  ví dụ '5', '<8', '08', '.2', '8.3'.
          '<' = căn trái (-), '>'/'^' = mặc định, '0' = đệm số 0.
        Float có precision: %g -> %f (precision = số chữ số sau dấu phẩy)."""
        align = ""
        i = 0
        if i < len(flags) and flags[i] in "<>^":
            align = "-" if flags[i] == "<" else ""
            i += 1
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
        return "%" + align + zero + width + prec + rest

    def _fmt_placeholder(self, key, arg):
        """Trả về (specifier, c_arg | None) cho một placeholder, kèm ép kiểu
        để printf luôn nhận đúng kiểu (an toàn đa nền tảng).
        Hỗ trợ '{key:flags}' với flags width/precision/căn lề."""
        key, sep, flags = key.partition(":")
        if sep:
            spec, carg = self._fmt_placeholder(key, arg)
            return self._apply_fmt_flags(spec, flags), carg
        ce = self.gen_expr(arg) if arg is not None else None
        # bool tường minh -> in true/false
        if key == "b":
            if ce is not None:
                return "%s", f"(({ce}) ? \"true\" : \"false\")"
            return "%s", None
        # tự suy luận theo kiểu đối số
        if key in ("", "v"):
            gt = self.gtype_of(arg) if arg is not None else T.UNKNOWN
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

    def build_format(self, raw, value_args, newline=False):
        """Sinh chuỗi định dạng C + danh sách biểu thức C tương ứng.
        Placeholder rỗng {} => tự suy ra theo kiểu của tham số."""
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
                ai += 1
                spec, carg = self._fmt_placeholder(key, arg)
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
            return f"(({e.name}){{0}})"   # struct rỗng / khởi tạo zero
        parts = [f".{name} = {self.gen_expr(val)}" for name, val in e.fields]
        return f"(({e.name}){{ {', '.join(parts)} }})"

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
