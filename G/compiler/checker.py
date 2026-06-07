"""
G Language - Semantic Analyzer / Type Checker.
- Phân giải kiểu cho mọi biểu thức (gắn node.gtype).
- Kiểm tra: biến/định danh chưa khai báo, gán vào biến bất biến, sai số/kiểu tham số,
  kiểu lạ, sai kiểu trả về, break/continue ngoài vòng lặp, lệch placeholder...
- Phân giải lời gọi method (recv.method(...)).
- Chẩn đoán thông minh: gợi ý "có phải ... ?" (khoảng cách sửa Levenshtein).
"""

from . import ast_nodes as A
from . import types as T


class CheckError(Exception):
    def __init__(self, msg, line=0, col=0, file=None):
        super().__init__(msg)
        self.msg = msg
        self.line = line
        self.col = col
        self.file = file


BUILTINS = {"print", "println", "eprint", "eprintln", "printf",
            "len", "assert", "panic", "min", "max", "abs", "clamp",
            "g_alloc", "g_free", "g_realloc", "unreachable", "todo"}


def extract_placeholders(fmt: str):
    """Trả về danh sách key của các placeholder {...} (bỏ qua {{ và }}).
    '{}' -> '' (tự suy luận); '{d}' -> 'd'; v.v."""
    keys = []
    i = 0
    L = len(fmt)
    while i < L:
        c = fmt[i]
        if c == "{" and i + 1 < L and fmt[i + 1] == "{":
            i += 2; continue
        if c == "}" and i + 1 < L and fmt[i + 1] == "}":
            i += 2; continue
        if c == "{":
            j = fmt.find("}", i)
            if j != -1:
                keys.append(fmt[i + 1:j])
                i = j + 1
                continue
        i += 1
    return keys


def count_placeholders(fmt: str) -> int:
    """Đếm số placeholder {...} trong chuỗi định dạng (bỏ qua {{ và }})."""
    return len(extract_placeholders(fmt))


# Nhóm specifier tường minh -> tên kiểu mong đợi (để chẩn đoán). Dùng cho kiểm
# tra khớp giữa placeholder và kiểu đối số trong print/println.
_INT_SPECS = {"d", "ld", "u", "lu", "x", "X", "o", "lx", "lX", "lo"}
_FLOAT_SPECS = {"f", "lf", "g", "e", "lg", "le"}


def edit_distance(a: str, b: str) -> int:
    """Khoảng cách Levenshtein (cho gợi ý 'có phải ... ?')."""
    if a == b:
        return 0
    m, n = len(a), len(b)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[n]


def suggest(name: str, candidates) -> str:
    """Tìm ứng viên gần nhất với 'name' (None nếu quá xa)."""
    best, best_d = None, 1 << 30
    for c in candidates:
        if not isinstance(c, str) or c == name:
            continue
        d = edit_distance(name, c)
        if d < best_d:
            best, best_d = c, d
    limit = max(2, len(name) // 2)
    return best if best is not None and best_d <= limit else None


class Checker:
    def __init__(self, program: A.Program):
        self.prog = program
        self.structs = {}          # name -> {field: GType}
        self.struct_order = {}     # name -> [field names]
        self.enums = {}            # name -> {variant: value_int}
        self.enum_of_variant = {}  # variant -> enum name
        self.methods = {}          # struct -> {method: Function}
        self.funcs = {}            # name -> GType(func)
        self.func_defs = {}        # name -> Function (để kiểm tra tên tham số)
        self.globals = {}          # name -> (GType, mutable)
        self.scopes = []           # ngăn xếp scope cục bộ
        self.type_names = set()    # mọi tên kiểu hợp lệ (gợi ý lỗi)
        self.cur_ret = T.VOID
        self.cur_fn = "<global>"
        self.cur_file = None       # file đang kiểm tra (chẩn đoán đa module)
        self.loop_depth = 0        # độ sâu vòng lặp (kiểm tra break/continue)
        self.fn_cnames = set()     # mọi tên C đã dùng trong hàm hiện tại (chống shadow)

    # ---------- tiện ích lỗi ----------
    def err(self, msg, node=None):
        line = getattr(node, "line", 0) if node is not None else 0
        col = getattr(node, "col", 0) if node is not None else 0
        raise CheckError(msg, line, col, self.cur_file)

    # ---------- API ----------
    def check(self):
        self.collect_const_values()
        self.collect_types()
        self.collect_funcs()
        self.collect_globals()
        for it in self.prog.items:
            self.cur_file = getattr(it, "src_file", None)
            if isinstance(it, A.Function) and it.body is not None:
                self.check_function(it)
            elif isinstance(it, A.Impl):
                for m in it.methods:
                    if m.body is not None:
                        self.check_function(m)
        return self.prog

    # ---------- thu thập hằng nguyên (cho cỡ mảng tượng trưng) ----------
    def collect_const_values(self):
        """Thu thập giá trị nguyên của các global hằng (const/let bất biến gán
        literal) để có thể dùng tên hằng làm cỡ mảng: 'let a: [CAP]int'.
        Fold đơn giản: literal, '-N', và phép toán giữa các hằng đã biết."""
        self.const_ints = {}
        # nhiều lượt để hằng tham chiếu hằng khai báo trước
        for _ in range(8):
            changed = False
            for it in self.prog.items:
                if not isinstance(it, A.GlobalVar):
                    continue
                if it.mutable and not it.is_const:
                    continue
                if it.name in self.const_ints or it.value is None:
                    continue
                v = self._fold_const_int(it.value)
                if v is not None:
                    self.const_ints[it.name] = v
                    changed = True
            if not changed:
                break

    def _fold_const_int(self, e):
        """Tính giá trị nguyên của biểu thức hằng (hoặc None nếu không thể)."""
        if isinstance(e, A.IntLit):
            try:
                return int(e.value, 0)
            except ValueError:
                return None
        if isinstance(e, A.CharLit):
            return ord(e.value) if len(e.value) == 1 else None
        if isinstance(e, A.Ident):
            return self.const_ints.get(e.name)
        if isinstance(e, A.Unary):
            v = self._fold_const_int(e.operand)
            if v is None:
                return None
            return {"-": -v, "~": ~v, "+": v}.get(e.op)
        if isinstance(e, A.Binary):
            a = self._fold_const_int(e.left)
            b = self._fold_const_int(e.right)
            if a is None or b is None:
                return None
            try:
                return {
                    "+": a + b, "-": a - b, "*": a * b,
                    "/": a // b if b else None, "%": a % b if b else None,
                    "<<": a << b, ">>": a >> b,
                    "&": a & b, "|": a | b, "^": a ^ b,
                }.get(e.op)
            except (ValueError, ZeroDivisionError):
                return None
        if isinstance(e, A.Cast):
            return self._fold_const_int(e.expr)
        return None

    # ---------- thu thập khai báo ----------
    def collect_types(self):
        # Lượt 1: đăng ký TÊN struct/enum trước để cho phép tham chiếu tiến (forward).
        for it in self.prog.items:
            if isinstance(it, A.StructDef):
                self.structs.setdefault(it.name, {})
                self.struct_order.setdefault(it.name, [])
            elif isinstance(it, A.EnumDef):
                self.enums.setdefault(it.name, {})
        self.type_names = (set(T.PRIMITIVES) | set(self.structs) | set(self.enums))
        # Lượt 2: điền nội dung (giờ resolve thấy mọi tên kiểu).
        for it in self.prog.items:
            self.cur_file = getattr(it, "src_file", None)
            if isinstance(it, A.StructDef):
                for f in it.fields:
                    if f.name in self.structs[it.name]:
                        self.err(
                            f"struct '{it.name}' có trường trùng tên '{f.name}'",
                            getattr(f, "type", None) or it)
                    self.structs[it.name][f.name] = self.resolve(f.type)
                    self.struct_order[it.name].append(f.name)
            elif isinstance(it, A.EnumDef):
                table = {}
                nxt = 0
                for vname, vval in it.variants:
                    if vname in table:
                        self.err(
                            f"enum '{it.name}' có biến thể trùng tên '{vname}'", it)
                    if vname in self.enum_of_variant:
                        self.err(
                            f"biến thể '{vname}' đã thuộc enum "
                            f"'{self.enum_of_variant[vname]}' — tên biến thể phải "
                            f"duy nhất trên toàn chương trình (C dùng chung không "
                            f"gian tên cho hằng enum)", it)
                    if vval is not None and isinstance(vval, A.IntLit):
                        nxt = int(vval.value, 0)
                    elif vval is not None and (
                            isinstance(vval, A.Unary) and vval.op == "-"
                            and isinstance(vval.operand, A.IntLit)):
                        nxt = -int(vval.operand.value, 0)
                    table[vname] = nxt
                    self.enum_of_variant[vname] = it.name
                    nxt += 1
                self.enums[it.name] = table

    def collect_funcs(self):
        for it in self.prog.items:
            if isinstance(it, A.Function):
                self.cur_file = getattr(it, "src_file", None)
                # Định nghĩa trùng (cả hai có thân) sinh lỗi redefinition trong C.
                # Một prototype 'extern' + một định nghĩa thì hợp lệ.
                prev = self.func_defs.get(it.name)
                if (prev is not None and prev.body is not None
                        and it.body is not None):
                    self.err(f"hàm '{it.name}' được định nghĩa nhiều lần", it)
                self.register_func(it)
            elif isinstance(it, A.Impl):
                self.cur_file = getattr(it, "src_file", None)
                self.methods.setdefault(it.struct, {})
                for m in it.methods:
                    if m.name in self.methods[it.struct]:
                        self.err(
                            f"method '{it.struct}.{m.name}' được định nghĩa "
                            f"nhiều lần", m)
                    self.methods[it.struct][m.name] = m

    # ---------- phân tích: method có ghi vào *self không? ----------
    def method_mutates_self(self, struct, mname, _stack=None) -> bool:
        """True nếu method ghi vào đối tượng nhận (qua self.field = ..., self[i]=...,
        *self = ..., hoặc gọi method-tự-sửa khác trên self). Dùng để cấm gọi
        method-sửa trên giá trị bất biến ('let'). Có nhớ kết quả (memoize)."""
        cache = getattr(self, "_mut_cache", None)
        if cache is None:
            cache = self._mut_cache = {}
        key = (struct, mname)
        if key in cache:
            return cache[key]
        m = self.methods.get(struct, {}).get(mname)
        if m is None or m.body is None:
            cache[key] = False
            return False
        _stack = _stack or set()
        if key in _stack:          # đệ quy: giả định không-sửa để hội tụ
            return False
        _stack.add(key)
        result = self._body_mutates_self(m.body, struct, _stack)
        _stack.discard(key)
        cache[key] = result
        return result

    def _body_mutates_self(self, body, struct, stack) -> bool:
        for st in body:
            if self._stmt_mutates_self(st, struct, stack):
                return True
        return False

    def _stmt_mutates_self(self, st, struct, stack) -> bool:
        if isinstance(st, A.Assign):
            if self._target_is_self_storage(st.target):
                return True
        if isinstance(st, A.ExprStmt):
            return self._call_mutates_self(st.expr, struct, stack)
        if isinstance(st, A.Let):
            return st.value is not None and self._call_mutates_self(st.value, struct, stack)
        if isinstance(st, A.Return):
            return st.value is not None and self._call_mutates_self(st.value, struct, stack)
        if isinstance(st, A.If):
            return (self._body_mutates_self(st.then, struct, stack)
                    or (st.els is not None and self._body_mutates_self(st.els, struct, stack)))
        if isinstance(st, (A.While, A.Loop, A.For, A.ForEach, A.Block)):
            return self._body_mutates_self(getattr(st, "body", []), struct, stack)
        if isinstance(st, A.Match):
            return any(self._body_mutates_self(b, struct, stack) for _, _, b in st.arms)
        if isinstance(st, A.Defer):
            return self._stmt_mutates_self(st.stmt, struct, stack)
        return False

    @staticmethod
    def _target_is_self_storage(tgt) -> bool:
        """Đích gán có nằm TRONG bộ nhớ của *self không? self.x / self[i] / *self
        thì CÓ (sửa đối tượng nhận). Nhưng self.ptr_field[i] đi qua một con trỏ
        khác -> KHÔNG sửa chính *self."""
        e = tgt
        while True:
            if isinstance(e, A.Ident):
                return e.name == "self"
            if isinstance(e, A.FieldAccess):
                # self.field: nếu field là con trỏ và ta deref nó thì không tính,
                # nhưng FieldAccess trực tiếp (self.x = ...) là sửa self.
                bt = getattr(e.base, "gtype", None)
                if bt is not None and bt.kind == "ptr" and not (
                        isinstance(e.base, A.Ident) and e.base.name == "self"):
                    return False   # ghi qua con trỏ trung gian khác
                e = e.base
                continue
            if isinstance(e, A.Index):
                bt = getattr(e.base, "gtype", None)
                # index qua con trỏ/mảng-động (heap) -> không phải bộ nhớ *self
                if bt is not None and (bt.kind in ("ptr", "str") or
                                       (bt.kind == "array" and bt.n == "dyn")):
                    return False
                e = e.base
                continue
            if isinstance(e, A.Unary) and e.op == "*":
                return isinstance(e.operand, A.Ident) and e.operand.name == "self"
            return False

    def _call_mutates_self(self, e, struct, stack) -> bool:
        """Biểu thức có chứa lời gọi method-tự-sửa trên 'self' không?"""
        if isinstance(e, A.Call) and isinstance(e.func, A.FieldAccess):
            recv = e.func.base
            if isinstance(recv, A.Ident) and recv.name == "self":
                if self.method_mutates_self(struct, e.func.field, stack):
                    return True
        # quét đệ quy các nhánh con để bắt lời gọi lồng
        for child in self._expr_children(e):
            if self._call_mutates_self(child, struct, stack):
                return True
        return False

    @staticmethod
    def _expr_children(e):
        if isinstance(e, A.Binary):
            return [e.left, e.right]
        if isinstance(e, A.Unary):
            return [e.operand]
        if isinstance(e, A.Ternary):
            return [e.cond, e.then, e.els]
        if isinstance(e, A.Call):
            return [e.func] + list(e.args)
        if isinstance(e, A.Index):
            return [e.base, e.index]
        if isinstance(e, A.FieldAccess):
            return [e.base]
        if isinstance(e, A.Cast):
            return [e.expr]
        return []

    def collect_globals(self):
        # Khai báo trước MỌI tên global (UNKNOWN) để tham chiếu chéo không lỗi.
        for it in self.prog.items:
            if isinstance(it, A.GlobalVar):
                self.globals[it.name] = (T.UNKNOWN, it.mutable and not it.is_const)
        for it in self.prog.items:
            if isinstance(it, A.GlobalVar):
                self.cur_file = getattr(it, "src_file", None)
                if it.type is not None:
                    gt = self.resolve(it.type)
                    if it.value is not None:
                        vt = self.infer(it.value)
                        if not self.assignable(gt, vt):
                            self.err(
                                f"không thể gán giá trị kiểu '{self.tyname(vt)}' "
                                f"cho '{it.name}: {self.tyname(gt)}'", it)
                        self._check_int_range(it.value, gt, it)
                elif it.value is not None:
                    gt = self.infer(it.value)
                else:
                    gt = T.INT
                it.resolved_type = gt
                self.globals[it.name] = (gt, it.mutable and not it.is_const)

    def register_func(self, fn: A.Function):
        params = tuple(self.resolve(p.type) for p in fn.params)
        ret = self.resolve(fn.ret)
        self.funcs[fn.name] = T.GType("func", params=params, ret=ret)
        self.func_defs[fn.name] = fn

    # ---------- phân giải kiểu cú pháp -> GType ----------
    def resolve(self, ty: A.Type) -> T.GType:
        if ty is None:
            return T.UNKNOWN
        base = ty.name
        if base in T.PRIMITIVES:
            g = T.PRIMITIVES[base]
        elif base in self.structs:
            g = T.GType("struct", name=base)
        elif base in self.enums:
            g = T.GType("enum", name=base)
        else:
            sug = suggest(base, self.type_names)
            msg = f"kiểu chưa biết: '{base}'"
            if sug:
                msg += f" — có phải '{sug}'?"
            raise CheckError(msg, ty.line, ty.col, self.cur_file)
        # Mảng nhiều chiều: bọc từ chiều TRONG ra NGOÀI để [N][M]T = array(N, array(M, T)).
        dims = ty.dims if ty.dims is not None else (
            [ty.array] if ty.array is not None else [])
        dims = [self._fold_dim(d, ty) for d in dims]
        # Ghi đè lại vào node cú pháp để codegen (đọc thẳng ty.dims/ty.array) thấy
        # giá trị đã fold (số nguyên), không còn tên hằng tượng trưng.
        if ty.dims is not None:
            ty.dims = dims
            ty.array = dims[0] if dims else None
        elif ty.array is not None and dims:
            ty.array = dims[0]
        for d in reversed(dims):
            g = T.array_of(g, d)
        for _ in range(ty.ptr):
            g = T.ptr_of(g)
        return g

    def _fold_dim(self, d, ty):
        """Chuyển một chiều mảng tượng trưng (tên hằng) thành số nguyên.
        Số / 'dyn' giữ nguyên. Tên không phải hằng nguyên -> lỗi rõ ràng."""
        if not isinstance(d, str) or d == "dyn":
            return d
        v = getattr(self, "const_ints", {}).get(d)
        if v is None:
            raise CheckError(
                f"cỡ mảng '{d}' phải là hằng số nguyên đã biết "
                f"(const/let bất biến gán giá trị hằng)", ty.line, ty.col,
                self.cur_file)
        if v <= 0:
            raise CheckError(
                f"cỡ mảng '{d}' = {v} phải là số dương", ty.line, ty.col,
                self.cur_file)
        return v

    # ---------- scope ----------
    def push(self):
        self.scopes.append({})

    def pop(self):
        self.scopes.pop()

    def declare(self, name, gt, mutable):
        """Khai báo biến cục bộ; cấp một tên C duy nhất để cho phép shadowing
        (C cấm khai báo lại trong cùng scope). Trả về tên C đã cấp."""
        cname = name
        if cname in self.fn_cnames:
            k = 1
            while f"{name}_s{k}" in self.fn_cnames:
                k += 1
            cname = f"{name}_s{k}"
        self.fn_cnames.add(cname)
        self.scopes[-1][name] = (gt, mutable, cname)
        return cname

    def lookup(self, name):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        if name in self.globals:
            g = self.globals[name]
            return (g[0], g[1], name)   # global: tên C = chính nó
        return None

    # ---------- tương thích kiểu ----------
    @staticmethod
    def _is_dyn_array(t: T.GType) -> bool:
        return t is not None and t.kind == "array" and t.n == "dyn"

    @staticmethod
    def _is_static_array(t: T.GType) -> bool:
        return t is not None and t.kind == "array" and t.n != "dyn"

    def _ptrlike(self, t: T.GType) -> bool:
        # Trong C: *T, str, null và []T (mảng động) đều là con trỏ.
        return t.kind in ("ptr", "str", "null") or self._is_dyn_array(t)

    def assignable(self, dst: T.GType, src: T.GType) -> bool:
        """Có thể gán/chuyển 'src' cho nơi cần 'dst'? Nới lỏng kiểu C, chỉ
        từ chối các trường hợp rõ ràng sai (chuỗi<->số, struct lệch...)."""
        if dst is None or src is None:
            return True
        if dst.kind == "unknown" or src.kind in ("unknown", "null"):
            return True
        if dst.kind == "void":
            return False
        # Mảng tĩnh phân rã thành con trỏ -> gán được cho *T hoặc []T.
        if self._ptrlike(dst) and (self._ptrlike(src) or self._is_static_array(src)):
            return True
        if dst.kind == src.kind:
            if dst.kind in ("struct", "enum"):
                return dst.name == src.name
            if dst.kind == "array":
                return self.assignable(dst.elem, src.elem)
            return True
        numeric = ("int", "float", "char", "bool")
        if dst.kind in numeric and src.kind in numeric:
            return True
        if {dst.kind, src.kind} <= {"int", "char", "enum"}:
            return True
        return False

    def tyname(self, t: T.GType) -> str:
        return str(t) if t is not None else "?"

    # ---------- kiểm tra hàm ----------
    def check_function(self, fn: A.Function):
        self.cur_fn = fn.name
        self.fn_cnames = set()
        self.push()
        seen = set()
        for p in fn.params:
            if p.name in seen:
                self.err(f"tham số trùng tên '{p.name}' trong hàm '{fn.name}'", fn)
            seen.add(p.name)
            self.declare(p.name, self.resolve(p.type), True)
        self.cur_ret = self.resolve(fn.ret)
        self.check_block(fn.body)
        self.pop()
        # Phân tích đường về: hàm non-void phải trả về trên mọi nhánh.
        if self.cur_ret.kind != "void" and not self._always_returns(fn.body):
            self.err(
                f"hàm '{fn.name}' kiểu '{self.tyname(self.cur_ret)}' có thể kết thúc "
                f"mà không trả về giá trị (thiếu 'return' trên một nhánh)", fn)

    def check_block(self, body):
        self.push()
        for st in body:
            self.check_stmt(st)
        self.pop()

    # ---------- phân tích đường về (mọi nhánh có return/diverge?) ----------
    def _always_returns(self, body) -> bool:
        """True nếu khối CHẮC CHẮN không rơi xuống cuối (return/panic/loop vô hạn
        /if-else đều thoát/match vét cạn đều thoát). Phân tích bảo toàn (sound)."""
        for st in body:
            if self._stmt_diverges(st):
                return True
        return False

    def _stmt_diverges(self, st) -> bool:
        if isinstance(st, A.Return):
            return True
        if isinstance(st, A.ExprStmt):
            return self._expr_diverges(st.expr)
        if isinstance(st, A.If):
            # cần CẢ then và else, và else phải tồn tại
            if st.els is None:
                return False
            return self._always_returns(st.then) and self._always_returns(st.els)
        if isinstance(st, A.Block):
            return self._always_returns(st.body)
        if isinstance(st, A.Loop):
            # loop { } vô hạn diverge TRỪ KHI có 'break' thoát ra
            return not self._has_break(st.body)
        if isinstance(st, A.Match):
            # vét cạn (có nhánh _, HOẶC match enum phủ hết variant) và mọi nhánh
            # đều diverge. Nhánh có guard KHÔNG được tính là vét cạn (điều kiện có
            # thể sai lúc chạy -> rơi xuống).
            exhaustive = getattr(st, "has_default", False) or any(
                p is None and g is None for p, g, _ in st.arms
            ) or self._match_covers_enum(st)
            if not exhaustive:
                return False
            return all(self._always_returns(b) for _, _, b in st.arms)
        return False

    def _match_covers_enum(self, st: A.Match) -> bool:
        """match trên enum có liệt kê HẾT mọi variant không (vét cạn không cần '_')."""
        subj_t = getattr(st, "subject_type", None)
        if subj_t is None or subj_t.kind != "enum":
            return False
        all_variants = set(self.enums.get(subj_t.name, {}))
        if not all_variants:
            return False
        covered = set()
        for pats, guard, _ in st.arms:
            if pats is None or guard is not None:
                continue   # nhánh có guard không bảo đảm phủ -> bỏ qua
            for p in pats:
                if isinstance(p, A.Ident) and p.name in all_variants:
                    covered.add(p.name)
        return covered >= all_variants

    def _expr_diverges(self, e) -> bool:
        # panic/unreachable/todo không bao giờ trả về
        if isinstance(e, A.Call) and isinstance(e.func, A.Ident):
            if e.func.name in ("panic", "unreachable", "todo"):
                return True
        return False

    def _has_break(self, body) -> bool:
        """Có 'break' nào thuộc vòng lặp HIỆN TẠI (không tính vòng lặp lồng bên trong)."""
        for st in body:
            if isinstance(st, A.Break):
                return True
            if isinstance(st, A.If):
                if self._has_break(st.then):
                    return True
                if st.els and self._has_break(st.els):
                    return True
            elif isinstance(st, A.Block):
                if self._has_break(st.body):
                    return True
            elif isinstance(st, A.Match):
                if any(self._has_break(b) for _, _, b in st.arms):
                    return True
            # KHÔNG đệ quy vào While/For/ForEach/Loop: break ở đó thuộc vòng lặp khác
        return False

    def check_stmt(self, st):
        if isinstance(st, A.Let):
            val_t = self.infer(st.value) if st.value is not None else None
            # Gán kết quả của hàm void cho biến là vô nghĩa (C: 'declared void').
            if val_t is not None and val_t.kind == "void":
                fn = (st.value.func.name if isinstance(st.value, A.Call)
                      and isinstance(st.value.func, A.Ident) else "biểu thức")
                self.err(
                    f"không thể gán giá trị từ '{fn}' kiểu void cho biến "
                    f"'{st.name}' (hàm không trả về giá trị)", st)
            if st.type is not None:
                gt = self.resolve(st.type)
                if val_t is not None and not self.assignable(gt, val_t):
                    self.err(
                        f"không thể gán giá trị kiểu '{self.tyname(val_t)}' "
                        f"cho '{st.name}: {self.tyname(gt)}'", st)
                if st.value is not None:
                    self._check_int_range(st.value, gt, st)
            else:
                gt = val_t if val_t is not None else T.INT
            st.resolved_type = gt
            st.c_name = self.declare(st.name, gt, st.mutable)
        elif isinstance(st, A.Return):
            if st.value is not None:
                vt = self.infer(st.value)
                if not self.assignable(self.cur_ret, vt):
                    if self.cur_ret.kind == "void":
                        self.err(
                            f"hàm '{self.cur_fn}' kiểu void không trả về giá trị", st)
                    self.err(
                        f"sai kiểu trả về: hàm '{self.cur_fn}' cần "
                        f"'{self.tyname(self.cur_ret)}' nhưng trả '{self.tyname(vt)}'",
                        st)
            elif self.cur_ret.kind != "void":
                self.err(
                    f"hàm '{self.cur_fn}' cần trả về '{self.tyname(self.cur_ret)}'", st)
        elif isinstance(st, A.If):
            self.infer(st.cond)
            self.check_block(st.then)
            if st.els is not None:
                self.check_block(st.els)
        elif isinstance(st, A.While):
            self.infer(st.cond)
            self.loop_depth += 1
            self.check_block(st.body)
            self.loop_depth -= 1
        elif isinstance(st, A.Loop):
            self.loop_depth += 1
            self.check_block(st.body)
            self.loop_depth -= 1
        elif isinstance(st, A.For):
            self.check_for(st)
        elif isinstance(st, A.ForEach):
            self.check_foreach(st)
        elif isinstance(st, A.Match):
            self.check_match(st)
        elif isinstance(st, A.Block):
            self.check_block(st.body)
        elif isinstance(st, A.Defer):
            self.check_stmt(st.stmt)
        elif isinstance(st, A.Assign):
            self.check_assign(st)
        elif isinstance(st, A.Break):
            if self.loop_depth == 0:
                self.err("'break' nằm ngoài vòng lặp", st)
        elif isinstance(st, A.Continue):
            if self.loop_depth == 0:
                self.err("'continue' nằm ngoài vòng lặp", st)
        elif isinstance(st, A.ExprStmt):
            self.infer(st.expr)
        # Asm: không cần kiểm tra

    def check_for(self, st: A.For):
        st_t = self.infer(st.start)
        en_t = self.infer(st.end)
        if st.step is not None:
            self.infer(st.step)
        if st_t.is_numeric() and en_t.is_numeric():
            vt = T.common_numeric(st_t, en_t)
            if vt.kind == "float":
                vt = T.I64
        else:
            vt = T.INT
        st.var_type = vt
        self.loop_depth += 1
        self.push()
        st.c_name = self.declare(st.var, vt, True)
        for s in st.body:
            self.check_stmt(s)
        self.pop()
        self.loop_depth -= 1

    def check_foreach(self, st: A.ForEach):
        it_t = self.infer(st.iterable)
        if it_t.kind == "array":
            elem = it_t.elem
            st.iter_kind = "array"
        elif it_t.kind == "str":
            elem = T.CHAR
            st.iter_kind = "str"
        elif it_t.kind == "ptr" and it_t.elem is not None and it_t.elem.kind == "char":
            elem = T.CHAR
            st.iter_kind = "str"
        else:
            self.err(
                "chỉ có thể 'for x in ...' trên mảng tĩnh hoặc chuỗi "
                "(con trỏ/[]T thiếu độ dài — hãy dùng vòng lặp theo chỉ số)", st)
            return
        if st.iter_kind == "array" and not isinstance(
                st.iterable, (A.Ident, A.FieldAccess, A.Index, A.ArrayLit)):
            self.err("'for x in <mảng>' cần một biến mảng hoặc mảng literal "
                     "(để biết độ dài)", st)
        st.elem_type = elem or T.INT
        self.loop_depth += 1
        self.push()
        st.c_name = self.declare(st.var, st.elem_type, st.mutable)
        for s in st.body:
            self.check_stmt(s)
        self.pop()
        self.loop_depth -= 1

    def _binding_name(self, pats):
        """Một pattern là *binding* (kiểu Rust: 'x => ...' / 'x if x>0 => ...')
        khi nó là MỘT định danh trần CHƯA mang nghĩa nào khác — không phải biến
        thể enum, hằng/biến đã khai báo, tên hàm/kiểu. Khi đó nó bắt giá trị
        subject vào tên mới (dùng được trong guard và thân). Trả về tên, hoặc None."""
        if pats is None or len(pats) != 1:
            return None
        p = pats[0]
        if not isinstance(p, A.Ident):
            return None
        nm = p.name
        if (nm in self.enum_of_variant or nm in self.funcs or nm in self.enums
                or nm in self.structs or nm in T.PRIMITIVES or nm in BUILTINS):
            return None
        if self.lookup(nm) is not None:
            return None
        return nm

    def check_match(self, st: A.Match):
        subj_t = self.infer(st.subject)
        has_default = False
        str_subj = subj_t.kind == "str" or (
            subj_t.kind == "ptr" and subj_t.elem and subj_t.elem.kind == "char")
        st.bindings = []
        for pats, guard, body in st.arms:
            bind = self._binding_name(pats)
            self.push()
            bind_cname = None
            if bind is not None:
                bind_cname = self.declare(bind, subj_t, False)
                pats[0].c_name = bind_cname
                # binding KHÔNG guard = bắt mọi giá trị -> mặc định tuyệt đối.
                if guard is None:
                    has_default = True
            elif pats is None:
                if guard is None:
                    has_default = True
            else:
                for p in pats:
                    if isinstance(p, A.RangePat):
                        lo = self.infer(p.lo)
                        hi = self.infer(p.hi)
                        if not (lo.is_numeric() and hi.is_numeric()):
                            self.err("pattern khoảng (lo..hi) cần hai biên là số", p)
                        if str_subj:
                            self.err("không thể dùng pattern khoảng cho match chuỗi", p)
                    else:
                        self.infer(p)
            if guard is not None:
                gt = self.infer(guard)
                if gt.kind not in ("bool", "unknown", "int", "char"):
                    self.err("điều kiện 'if' trong match phải là biểu thức luận lý", guard)
            for s in body:
                self.check_stmt(s)
            self.pop()
            st.bindings.append(bind_cname)
        st.subject_type = subj_t
        st.has_default = has_default

    def check_assign(self, st: A.Assign):
        vt = self.infer(st.value)
        tgt = st.target
        tt = self.infer(tgt)
        self._check_lvalue_mutable(tgt, st)
        # C cấm gán cả mảng tĩnh bằng '=' (kiểu mảng không phải lvalue gán được).
        # Bắt sớm để báo lỗi rõ ràng thay vì rò lỗi C khó hiểu.
        if self._is_static_array(tt):
            self.err(
                f"không thể gán cả mảng tĩnh '{self.tyname(tt)}' bằng '=' "
                f"(sao chép từng phần tử, hoặc dùng con trỏ/[]T)", st)
        if not self.assignable(tt, vt):
            self.err(
                f"không thể gán giá trị kiểu '{self.tyname(vt)}' cho ô nhớ kiểu "
                f"'{self.tyname(tt)}'", st)

    def _check_lvalue_mutable(self, tgt, stmt):
        """Đi từ ô nhớ đích về biến gốc để kiểm tra tính bất biến.
        Ghi qua con trỏ (deref/index trên ptr) luôn được phép."""
        # Đích phải là ô nhớ (lvalue): biến, trường, phần tử, hoặc *con_trỏ.
        if not isinstance(tgt, (A.Ident, A.FieldAccess, A.Index)) and not (
                isinstance(tgt, A.Unary) and tgt.op == "*"):
            self.err("vế trái của phép gán phải là ô nhớ (biến/trường/phần tử/"
                     "*con_trỏ), không thể gán cho biểu thức này", stmt)
        e = tgt
        while True:
            if isinstance(e, A.Ident):
                info = self.lookup(e.name)
                if info is None:
                    self.err(f"biến chưa khai báo: '{e.name}'", e)
                mutable = info[1]
                e.c_name = info[2]
                if not mutable:
                    self.err(
                        f"không thể gán cho '{e.name}' (bất biến — dùng 'let mut')",
                        stmt)
                return
            if isinstance(e, A.FieldAccess):
                bt = getattr(e.base, "gtype", None)
                if bt is not None and bt.kind == "ptr":
                    return  # qua con trỏ struct -> cho phép
                e = e.base
                continue
            if isinstance(e, A.Index):
                bt = getattr(e.base, "gtype", None)
                # index qua con trỏ / chuỗi / mảng động (đều là con trỏ heap) -> cho phép
                if bt is not None and (bt.kind in ("ptr", "str")
                                       or self._is_dyn_array(bt)):
                    return
                e = e.base
                continue
            if isinstance(e, A.Unary) and e.op == "*":
                return  # deref con trỏ -> cho phép
            return  # trường hợp khác: không xác định, cho qua

    # ---------- suy luận kiểu biểu thức ----------
    def infer(self, e) -> T.GType:
        t = self._infer(e)
        try:
            e.gtype = t
        except Exception:
            pass
        return t

    # Biên giá trị cho mỗi kiểu nguyên (để bắt literal tràn).
    _INT_BOUNDS = {
        "i8": (-(1 << 7), (1 << 7) - 1),
        "i16": (-(1 << 15), (1 << 15) - 1),
        "i32": (-(1 << 31), (1 << 31) - 1),
        "int": (-(1 << 31), (1 << 31) - 1),
        "i64": (-(1 << 63), (1 << 63) - 1),
        "isize": (-(1 << 63), (1 << 63) - 1),
        "u8": (0, (1 << 8) - 1),
        "u16": (0, (1 << 16) - 1),
        "u32": (0, (1 << 32) - 1),
        "u64": (0, (1 << 64) - 1),
        "usize": (0, (1 << 64) - 1),
    }

    @staticmethod
    def _int_literal_value(e):
        """Giá trị nguyên của một literal (kể cả '-N' = Unary('-', IntLit)).
        None nếu không phải literal nguyên thuần."""
        neg = False
        if isinstance(e, A.Unary) and e.op == "-":
            neg = True
            e = e.operand
        if isinstance(e, A.IntLit):
            try:
                v = int(e.value, 0)
            except ValueError:
                return None
            return -v if neg else v
        return None

    def _check_int_range(self, value_node, target: T.GType, ctx_node):
        """Kiểm tra literal nguyên có nằm trong biên của kiểu đích không."""
        v = self._int_literal_value(value_node)
        if v is None or target is None or target.kind != "int":
            return
        bounds = self._INT_BOUNDS.get(target.name)
        if bounds is None:
            return
        lo, hi = bounds
        if not (lo <= v <= hi):
            self.err(
                f"số {v} vượt giới hạn kiểu '{target.name}' "
                f"(hợp lệ: {lo}..{hi})", ctx_node)

    def _infer(self, e) -> T.GType:
        if isinstance(e, A.IntLit):
            # Mọi literal phải biểu diễn được trong 64-bit (i64 hoặc u64).
            try:
                v = int(e.value, 0)
            except ValueError:
                v = 0
            if v > (1 << 64) - 1:
                self.err(
                    f"số nguyên {e.value} quá lớn (vượt 64-bit; tối đa u64 = "
                    f"{(1 << 64) - 1})", e)
            return T.INT
        if isinstance(e, A.FloatLit):
            return T.F64
        if isinstance(e, A.StrLit):
            return T.STR
        if isinstance(e, A.CharLit):
            return T.CHAR
        if isinstance(e, A.BoolLit):
            return T.BOOL
        if isinstance(e, A.NullLit):
            return T.NULL
        if isinstance(e, A.Ident):
            return self.infer_ident(e)
        if isinstance(e, A.Binary):
            return self.infer_binary(e)
        if isinstance(e, A.Unary):
            return self.infer_unary(e)
        if isinstance(e, A.Ternary):
            self.infer(e.cond)
            a = self.infer(e.then)
            b = self.infer(e.els)
            if a.is_numeric() and b.is_numeric():
                return T.common_numeric(a, b)
            return a if a.kind != "unknown" else b
        if isinstance(e, A.Call):
            return self.infer_call(e)
        if isinstance(e, A.Index):
            return self.infer_index(e)
        if isinstance(e, A.FieldAccess):
            return self.infer_field(e)
        if isinstance(e, A.Cast):
            self.infer(e.expr)
            return self.resolve(e.type)
        if isinstance(e, A.SizeOf):
            return T.USIZE
        if isinstance(e, A.SizeOfExpr):
            self.infer(e.expr)
            return T.USIZE
        if isinstance(e, A.ArrayLit):
            elem = self.infer(e.elements[0]) if e.elements else T.INT
            for el in e.elements[1:]:
                self.infer(el)
            return T.array_of(elem, len(e.elements))
        if isinstance(e, A.StructLit):
            return self.infer_struct_lit(e)
        return T.UNKNOWN

    def infer_ident(self, e: A.Ident):
        info = self.lookup(e.name)
        if info is not None:
            e.c_name = info[2]
            return info[0]
        if e.name in self.enum_of_variant:
            return T.GType("enum", name=self.enum_of_variant[e.name])
        if e.name in self.funcs:
            return self.funcs[e.name]
        if e.name in BUILTINS:
            return T.UNKNOWN
        if e.name in T.PRIMITIVES or e.name in self.structs or e.name in self.enums:
            return T.UNKNOWN  # tên kiểu dùng làm giá trị (vd trong g_alloc)
        cands = set()
        for s in self.scopes:
            cands |= set(s.keys())
        cands |= set(self.globals) | set(self.funcs)
        cands |= set(self.enum_of_variant) | BUILTINS
        sug = suggest(e.name, cands)
        msg = f"định danh chưa khai báo: '{e.name}'"
        if sug:
            msg += f" — có phải '{sug}'?"
        self.err(msg, e)

    def infer_binary(self, e: A.Binary):
        lt = self.infer(e.left)
        rt = self.infer(e.right)
        op = e.op
        unk = lt.kind == "unknown" or rt.kind == "unknown"
        if op in ("&&", "||"):
            return T.BOOL
        if op in ("==", "!=", "<", ">", "<=", ">="):
            if not unk and not self._comparable(lt, rt):
                self.err(
                    f"không thể so sánh '{self.tyname(lt)}' với '{self.tyname(rt)}'"
                    + (" (chuỗi: dùng streq/strcmp)" if "str" in (lt.kind, rt.kind)
                       else ""), e)
            return T.BOOL
        if op in ("<<", ">>", "&", "|", "^"):
            if not unk and not (lt.is_integer() and rt.is_integer()):
                self.err(
                    f"toán tử bit '{op}' cần hai số nguyên, nhận "
                    f"'{self.tyname(lt)}' và '{self.tyname(rt)}'", e)
            return lt if lt.kind == "int" else T.INT
        # số học con trỏ: CHỈ với con trỏ thật (*T) hoặc []T, KHÔNG với 'str'.
        # 'str' + int sẽ là số học con trỏ vào literal — gần như luôn là lỗi
        # (người dùng tưởng nối chuỗi). Chỉ '+'/'-' mới hợp lệ cho con trỏ.
        l_ptr = lt.kind == "ptr" or self._is_dyn_array(lt)
        r_ptr = rt.kind == "ptr" or self._is_dyn_array(rt)
        if op in ("+", "-"):
            if l_ptr and rt.is_integer():
                return lt
            if r_ptr and lt.is_integer() and op == "+":
                return rt
            if op == "-" and lt.kind == "ptr" and rt.kind == "ptr":
                return T.ISIZE   # hiệu hai con trỏ
        if lt.is_numeric() and rt.is_numeric():
            return T.common_numeric(lt, rt)
        if unk:
            return lt if lt.kind != "unknown" else rt
        hint = ""
        if "str" in (lt.kind, rt.kind):
            hint = " (G không nối chuỗi bằng '+' — dùng str_concat)"
        self.err(
            f"không thể dùng '{op}' giữa '{self.tyname(lt)}' và '{self.tyname(rt)}'"
            + hint, e)

    def _comparable(self, a: T.GType, b: T.GType) -> bool:
        if a.is_numeric() and b.is_numeric():
            return True
        if {a.kind, b.kind} <= {"int", "char", "enum", "bool"}:
            return True
        if a.kind == "bool" and b.kind == "bool":
            return True
        # con trỏ so với con trỏ / null
        ap = a.kind in ("ptr", "str", "null") or self._is_dyn_array(a)
        bp = b.kind in ("ptr", "str", "null") or self._is_dyn_array(b)
        if ap and bp:
            return True
        if a.kind == "enum" and b.kind == "enum":
            return a.name == b.name
        return False

    def infer_unary(self, e: A.Unary):
        ot = self.infer(e.operand)
        if e.op == "!":
            return T.BOOL
        if e.op == "&":
            return T.ptr_of(ot)
        if e.op == "*":
            if ot.kind == "ptr":
                return ot.elem
            if ot.kind == "str":
                return T.CHAR
            if ot.kind == "array":
                return ot.elem
            return T.UNKNOWN
        return ot  # - , ~

    def infer_index(self, e: A.Index):
        bt = self.infer(e.base)
        it = self.infer(e.index)
        if not it.is_integer() and it.kind != "unknown":
            self.err(f"chỉ số mảng phải là số nguyên, nhận '{self.tyname(it)}'", e)
        if bt.kind in ("array", "ptr"):
            return bt.elem
        if bt.kind == "str":
            return T.CHAR
        if bt.kind == "unknown":
            return T.UNKNOWN
        self.err(f"không thể lập chỉ số trên '{self.tyname(bt)}' "
                 f"(chỉ mảng, con trỏ hoặc chuỗi)", e)

    def infer_field(self, e: A.FieldAccess):
        bt = self.infer(e.base)
        e.auto_deref = (bt.kind == "ptr")
        sname = None
        if bt.kind == "struct":
            sname = bt.name
        elif bt.kind == "ptr" and bt.elem and bt.elem.kind == "struct":
            sname = bt.elem.name
        if sname and sname in self.structs:
            if e.field in self.structs[sname]:
                return self.structs[sname][e.field]
            if sname in self.methods and e.field in self.methods[sname]:
                return T.UNKNOWN  # method dùng như giá trị — để infer_call xử lý
            sug = suggest(e.field, set(self.structs[sname]) |
                          set(self.methods.get(sname, {})))
            msg = f"struct '{sname}' không có trường '{e.field}'"
            if sug:
                msg += f" — có phải '{sug}'?"
            self.err(msg, e)
        return T.UNKNOWN

    def infer_struct_lit(self, e: A.StructLit):
        if e.name not in self.structs:
            sug = suggest(e.name, set(self.structs))
            msg = f"struct chưa định nghĩa: '{e.name}'"
            if sug:
                msg += f" — có phải '{sug}'?"
            self.err(msg, e)
        fields = self.structs[e.name]
        seen = set()
        for fname, val in e.fields:
            vt = self.infer(val)
            if fname not in fields:
                sug = suggest(fname, set(fields))
                msg = f"struct '{e.name}' không có trường '{fname}'"
                if sug:
                    msg += f" — có phải '{sug}'?"
                self.err(msg, e)
            elif not self.assignable(fields[fname], vt):
                self.err(
                    f"trường '{e.name}.{fname}' kiểu '{self.tyname(fields[fname])}' "
                    f"không nhận giá trị kiểu '{self.tyname(vt)}'", e)
            seen.add(fname)
        return T.GType("struct", name=e.name)

    def _require_mutable_receiver(self, recv, sname, mname, node):
        """Đối tượng nhận của một method-tự-sửa phải khả biến. Lần ngược về biến
        gốc; chỉ chặn khi chắc chắn bất biến (biến 'let'). Qua con trỏ -> bỏ qua."""
        e = recv
        while True:
            if isinstance(e, A.Ident):
                info = self.lookup(e.name)
                if info is not None and not info[1]:
                    self.err(
                        f"không thể gọi method '{sname}.{mname}' (sửa đổi đối "
                        f"tượng) trên '{e.name}' bất biến — dùng 'let mut'", node)
                return
            if isinstance(e, A.FieldAccess):
                bt = getattr(e.base, "gtype", None)
                if bt is not None and bt.kind == "ptr":
                    return   # qua con trỏ struct: cho phép
                e = e.base
                continue
            if isinstance(e, A.Index):
                bt = getattr(e.base, "gtype", None)
                if bt is not None and (bt.kind in ("ptr", "str")
                                       or self._is_dyn_array(bt)):
                    return
                e = e.base
                continue
            if isinstance(e, A.Unary) and e.op == "*":
                return   # deref con trỏ: cho phép
            return       # rvalue (struct literal, kết quả hàm...): cho qua

    def infer_call(self, e: A.Call):
        # ----- method call: recv.method(args) -----
        if isinstance(e.func, A.FieldAccess):
            recv = e.func.base
            mname = e.func.field
            bt = self.infer(recv)
            sname = bt.name if bt.kind == "struct" else (
                bt.elem.name if bt.kind == "ptr" and bt.elem and bt.elem.kind == "struct" else None)
            if sname and sname in self.methods and mname in self.methods[sname]:
                e.is_method = True
                e.recv = recv
                e.method = mname
                e.struct = sname
                e.recv_is_ptr = (bt.kind == "ptr")
                # Method GHI vào *self trên một giá trị bất biến ('let') sẽ sửa
                # đối tượng gốc một cách bất ngờ -> cấm (yêu cầu 'let mut' hoặc
                # con trỏ). Qua con trỏ thì luôn cho phép (đã chủ ý mượn để ghi).
                if not e.recv_is_ptr and self.method_mutates_self(sname, mname):
                    self._require_mutable_receiver(recv, sname, mname, e)
                arg_types = [self.infer(a) for a in e.args]
                m = self.methods[sname][mname]
                want = max(0, len(m.params) - 1)  # trừ 'self'
                if len(e.args) != want:
                    self.err(
                        f"method '{sname}.{mname}' cần {want} tham số "
                        f"nhưng nhận {len(e.args)}", e)
                for i, at in enumerate(arg_types):
                    pt = self.resolve(m.params[i + 1].type)
                    if not self.assignable(pt, at):
                        self.err(
                            f"tham số {i + 1} của '{sname}.{mname}' cần "
                            f"'{self.tyname(pt)}' nhưng nhận '{self.tyname(at)}'", e)
                return self.resolve(m.ret)
        # ----- builtin -----
        if isinstance(e.func, A.Ident) and e.func.name in BUILTINS:
            return self.infer_builtin(e)
        # ----- gọi định danh không phải hàm? (biến thường) -----
        if isinstance(e.func, A.Ident):
            nm = e.func.name
            if nm not in self.funcs:
                info = self.lookup(nm)
                if info is not None and info[0].kind not in ("func", "unknown"):
                    self.err(
                        f"'{nm}' kiểu '{self.tyname(info[0])}' không phải hàm "
                        f"để gọi", e)
        # ----- hàm thường -----
        ft = self.infer(e.func)
        arg_types = [self.infer(a) for a in e.args]
        if isinstance(e.func, A.Ident) and e.func.name in self.funcs:
            fdef = self.funcs[e.func.name]
            if len(e.args) != len(fdef.params):
                self.err(
                    f"hàm '{e.func.name}' cần {len(fdef.params)} tham số "
                    f"nhưng nhận {len(e.args)}", e)
            for i, (at, pt) in enumerate(zip(arg_types, fdef.params)):
                if not self.assignable(pt, at):
                    self.err(
                        f"tham số {i + 1} của '{e.func.name}' cần "
                        f"'{self.tyname(pt)}' nhưng nhận '{self.tyname(at)}'", e)
            return fdef.ret
        if ft.kind == "func":
            return ft.ret
        return T.UNKNOWN

    def _check_fmt_spec(self, key, at: T.GType, node):
        """Kiểm tra một specifier tường minh có khớp kiểu đối số không.
        '{}'/'{v}' tự suy luận nên luôn hợp lệ; bool dùng '{}' hoặc '{b}'.
        Bỏ phần ':flags' (width/precision) trước khi kiểm tra kiểu."""
        key = key.split(":", 1)[0]
        if at.kind == "unknown":
            return
        if key in ("", "v", "b"):
            return
        if key in _INT_SPECS:
            if not (at.is_integer() or at.kind == "enum"):
                self.err(
                    f"placeholder '{{{key}}}' cần số nguyên nhưng đối số kiểu "
                    f"'{self.tyname(at)}' (dùng '{{}}' để tự suy luận, hoặc "
                    f"'{{f}}' cho số thực)", node)
        elif key in _FLOAT_SPECS:
            if at.kind != "float":
                self.err(
                    f"placeholder '{{{key}}}' cần số thực nhưng đối số kiểu "
                    f"'{self.tyname(at)}' (dùng '{{}}' hoặc '{{d}}' cho số nguyên)",
                    node)
        elif key == "s":
            if not (at.kind == "str" or
                    (at.kind in ("ptr", "null") and at.elem is not None
                     and at.elem.kind == "char")):
                self.err(
                    f"placeholder '{{s}}' cần chuỗi nhưng đối số kiểu "
                    f"'{self.tyname(at)}'", node)
        elif key == "c":
            if not (at.is_integer() or at.kind == "char"):
                self.err(
                    f"placeholder '{{c}}' cần ký tự/số nguyên nhưng đối số kiểu "
                    f"'{self.tyname(at)}'", node)
        # 'p' và key lạ: bỏ qua (linh hoạt)

    def _type_arg_to_gtype(self, arg):
        """Phân giải đối số-là-kiểu của g_alloc/g_realloc. Chấp nhận tên kiểu trần
        (int, Node...), con trỏ (*T, viết là Unary('*', ...)), giúp cấp phát mảng
        con trỏ: g_alloc(*Node, n). Trả None nếu không nhận ra là kiểu."""
        if isinstance(arg, A.Unary) and arg.op == "*":
            inner = self._type_arg_to_gtype(arg.operand)
            return T.ptr_of(inner) if inner is not None else None
        if isinstance(arg, A.Ident):
            tn = arg.name
            if tn in T.PRIMITIVES:
                return T.PRIMITIVES[tn]
            if tn in self.structs:
                return T.GType("struct", name=tn)
            if tn in self.enums:
                return T.GType("enum", name=tn)
        return None

    def infer_builtin(self, e: A.Call):
        name = e.func.name
        if name == "g_alloc":
            # g_alloc(T, n): tham số đầu là KIỂU (tên trần hoặc con trỏ *T).
            if e.args:
                elem = self._type_arg_to_gtype(e.args[0])
                if elem is None:
                    self.err("g_alloc(T, n): tham số đầu phải là tên kiểu "
                             "(hoặc con trỏ *T)", e)
                    elem = T.INT
                if len(e.args) > 1:
                    self.infer(e.args[1])
                return T.ptr_of(elem)
            self.err("g_alloc(T, n): cần tên kiểu và số lượng", e)
            return T.ptr_of(T.VOID)
        if name == "g_realloc":
            for a in e.args:
                self.infer(a)
            return self.infer(e.args[0]) if e.args else T.ptr_of(T.VOID)
        if name in ("min", "max"):
            if len(e.args) != 2:
                self.err(f"{name}(a, b) cần đúng 2 tham số", e)
            a = self.infer(e.args[0]) if e.args else T.INT
            b = self.infer(e.args[1]) if len(e.args) > 1 else T.INT
            return T.common_numeric(a, b) if a.is_numeric() and b.is_numeric() else a
        if name == "clamp":
            if len(e.args) != 3:
                self.err("clamp(x, lo, hi) cần đúng 3 tham số", e)
            ts = [self.infer(a) for a in e.args]
            return ts[0] if ts else T.INT
        if name == "abs":
            if len(e.args) != 1:
                self.err("abs(x) cần đúng 1 tham số", e)
            return self.infer(e.args[0]) if e.args else T.INT
        if name == "len":
            if len(e.args) != 1:
                self.err("len(x) cần đúng 1 tham số", e)
            if e.args:
                at = self.infer(e.args[0])
                if self._is_dyn_array(at) or at.kind == "ptr":
                    self.err(
                        "len() không dùng được cho con trỏ/[]T (không lưu độ dài) — "
                        "hãy theo dõi độ dài riêng", e)
                elif at.kind not in ("array", "str") and at.kind != "unknown":
                    self.err(
                        f"len() cần mảng tĩnh hoặc chuỗi, nhận '{self.tyname(at)}'", e)
            return T.USIZE
        if name in ("print", "println", "eprint", "eprintln"):
            arg_ts = [self.infer(a) for a in e.args]
            value_ts = arg_ts[1:] if (e.args and isinstance(e.args[0], A.StrLit)) else arg_ts
            for at in value_ts:
                if at.kind in ("struct", "void") or self._is_static_array(at):
                    self.err(
                        f"không thể in trực tiếp giá trị kiểu '{self.tyname(at)}' "
                        f"(in từng trường/phần tử)", e)
            if e.args and isinstance(e.args[0], A.StrLit):
                keys = extract_placeholders(e.args[0].value)
                want = len(keys)
                got = len(e.args) - 1
                if want != got:
                    self.err(
                        f"chuỗi định dạng có {want} placeholder nhưng nhận {got} đối số",
                        e)
                # Khớp specifier tường minh với kiểu đối số (bắt UB của printf).
                for key, at in zip(keys, value_ts):
                    self._check_fmt_spec(key, at, e)
            return T.VOID
        if name == "assert":
            if not e.args:
                self.err("assert(cond[, msg]) cần ít nhất 1 tham số", e)
            for a in e.args:
                self.infer(a)
            return T.VOID
        # printf/panic/g_free và khác
        for a in e.args:
            self.infer(a)
        return T.VOID
