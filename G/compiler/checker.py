"""
G Language - Semantic Analyzer / Type Checker.
- Phân giải kiểu cho mọi biểu thức (gắn node.gtype).
- Kiểm tra: biến/định danh chưa khai báo, gán vào biến bất biến, sai số/kiểu tham số,
  kiểu lạ, sai kiểu trả về, break/continue ngoài vòng lặp, lệch placeholder...
- Phân giải lời gọi method (recv.method(...)).
- Chẩn đoán thông minh: gợi ý "có phải ... ?" (khoảng cách sửa Levenshtein).
"""

import re
from . import ast_nodes as A
from . import types as T


class _CTReturn(Exception):
    """Tín hiệu 'return' trong bộ thông dịch comptime (mang theo giá trị nguyên)."""
    def __init__(self, value):
        self.value = value


class _CTAbort(Exception):
    """Bộ thông dịch comptime gặp cấu trúc không gấp được -> coi như không-hằng."""


class CheckError(Exception):
    def __init__(self, msg, line=0, col=0, file=None):
        super().__init__(msg)
        self.msg = msg
        self.line = line
        self.col = col
        self.file = file


class CheckErrors(Exception):
    """Gói NHIỀU lỗi kiểm tra (checker phục hồi theo từng câu lệnh/hàm rồi báo
    hết một lượt, như gcc/rustc — không bắt người dùng sửa-chạy-lại từng lỗi)."""
    MAX = 20

    def __init__(self, errors):
        super().__init__(errors[0].msg if errors else "")
        self.errors = errors


BUILTINS = {"print", "println", "eprint", "eprintln", "printf", "format",
            "len", "assert", "panic", "min", "max", "abs", "clamp",
            "g_alloc", "g_free", "g_realloc", "unreachable", "todo",
            "typeof", "swap", "dbg",
            "assert_eq", "assert_ne", "check_eq", "check_ne", "test_summary",
            # so sánh THỨ TỰ (số/char/enum/chuỗi): dừng (assert_*) / ghi nhận (check_*)
            "assert_lt", "assert_le", "assert_gt", "assert_ge",
            "check_lt", "check_le", "check_gt", "check_ge",
            # ----- intrinsics phát triển hệ điều hành -----
            # bộ nhớ thô (libc hosted / runtime freestanding tự cài):
            "memcpy", "memset", "memmove", "memcmp",
            # MMIO (đọc/ghi qua 'volatile'):
            "vol_read", "vol_write",
            # thao tác bit (theo bề rộng kiểu):
            "popcount", "clz", "ctz", "bswap", "rotl", "rotr",
            # điều khiển CPU & thời gian (x86; lệnh đặc quyền chạy ở ring 0):
            "halt", "cli", "sti", "pause", "breakpoint", "io_wait", "rdtsc",
            # cổng I/O x86 (đặc quyền):
            "inb", "outb", "inw", "outw", "inl", "outl",
            # điều khiển bộ nhớ ảo / thanh ghi điều khiển / MSR (đặc quyền, ring 0):
            "read_cr0", "read_cr2", "read_cr3", "read_cr4",
            "write_cr0", "write_cr3", "write_cr4",
            "invlpg", "wbinvd", "rdmsr", "wrmsr",
            # khẳng định lúc biên dịch:
            "static_assert"}

# Nhóm intrinsics đơn giản dùng chung khi suy luận kiểu.
_OS_NULLARY_VOID = {"halt", "cli", "sti", "pause", "breakpoint", "io_wait",
                    "wbinvd"}
_OS_PORT_OUT = {"outb", "outw", "outl"}
_OS_BIT_TO_INT = {"popcount", "clz", "ctz"}    # trả về int
_OS_BIT_SAME = {"bswap", "rotl", "rotr"}       # trả về kiểu của đối số đầu
# Thanh ghi điều khiển (control register) — đọc trả u64, ghi nhận 1 giá trị.
_OS_CR_READ = {"read_cr0", "read_cr2", "read_cr3", "read_cr4"}   # () -> u64
_OS_CR_WRITE = {"write_cr0", "write_cr3", "write_cr4"}           # (v) -> void

# Hàm thư viện C bị kéo vào bởi runtime (stdio/stdlib/string/math/time...). Một
# hàm G *không* 'extern' trùng tên một trong số này sẽ gây lỗi C khó hiểu
# (conflicting types / redefinition). Bắt sớm để báo lỗi G rõ ràng.
LIBC_NAMES = {
    "malloc", "calloc", "realloc", "free", "abort", "exit", "atexit", "system",
    "getenv", "qsort", "bsearch", "atoi", "atol", "atof", "strtol", "strtod",
    "rand", "srand", "random", "srandom",
    "printf", "fprintf", "sprintf", "snprintf", "scanf", "sscanf", "puts",
    "putchar", "getchar", "fopen", "fclose", "fread", "fwrite", "fgets",
    "fputs", "perror", "remove", "rename", "fflush",
    "strlen", "strcmp", "strncmp", "strcpy", "strncpy", "strcat", "strncat",
    "strchr", "strrchr", "strstr", "strtok", "strdup", "strerror",
    "memcpy", "memmove", "memset", "memcmp",
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "sqrt", "cbrt",
    "pow", "exp", "log", "log2", "log10", "floor", "ceil", "round", "trunc",
    "fabs", "fmod", "hypot", "sinh", "cosh", "tanh",
    "time", "clock", "difftime", "mktime", "gmtime", "localtime",
}


def extract_placeholders(fmt: str, bad=None):
    """Trả về danh sách key của các placeholder {...} (bỏ qua {{ và }}).
    '{}' -> '' (tự suy luận); '{d}' -> 'd'; v.v.
    'bad' (list tuỳ chọn): nhận về các lỗi cú pháp của chuỗi định dạng — '{'
    không có '}' đóng, hoặc '}' đơn lẻ (gần như luôn là gõ thiếu, và trước đây
    bị in ra như ký tự thường một cách âm thầm)."""
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
            if bad is not None:
                bad.append("'{' không có '}' đóng — viết '{{' nếu muốn in dấu "
                           "'{' theo nghĩa đen")
        elif c == "}" and bad is not None:
            bad.append("'}' đơn lẻ không khớp với '{' nào — viết '}}' nếu muốn "
                       "in dấu '}' theo nghĩa đen")
        i += 1
    return keys


def count_placeholders(fmt: str) -> int:
    """Đếm số placeholder {...} trong chuỗi định dạng (bỏ qua {{ và }})."""
    return len(extract_placeholders(fmt))


# Nhóm specifier tường minh -> tên kiểu mong đợi (để chẩn đoán). Dùng cho kiểm
# tra khớp giữa placeholder và kiểu đối số trong print/println.
_INT_SPECS = {"d", "ld", "u", "lu", "x", "X", "o", "lx", "lX", "lo"}
_FLOAT_SPECS = {"f", "lf", "g", "e", "lg", "le"}
# Chữ kiểu đơn được phép đặt SAU dấu ':' (kiểu Rust: '{:x}', '{:08x}', '{:.2f}').
_FMT_TYPE_CHARS = set("duxXofgescb")
# Mọi khoá placeholder hợp lệ ('' và 'v' = tự suy luận).
_FMT_KEYS = {"", "v", "b", "p"} | _INT_SPECS | _FLOAT_SPECS | {"s", "c"}
_FMT_FLAGS_RE = re.compile(r"[<>^]?[+ ]?#?0?\d*(\.\d*)?")


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
    # Duyệt theo thứ tự SẮP XẾP để gợi ý ổn định giữa các lần chạy (candidates
    # thường là set -> thứ tự băm ngẫu nhiên; hoà điểm sẽ chọn tên nhỏ hơn).
    for c in sorted(c for c in candidates if isinstance(c, str)):
        if c == name:
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
        # Đăng ký sớm thân MỌI hàm cho bộ thông dịch comptime (chỉ cần tên +
        # params + body, KHÔNG cần phân giải kiểu) — nhờ vậy việc gấp lời gọi
        # hàm thành hằng (cỡ mảng '[sq(3)]int', giá trị const) hoạt động ở mọi
        # giai đoạn, kể cả trước khi collect_funcs() chạy. (Trước đây '_all_funcs'
        # không bao giờ được gán -> toàn bộ trình thông dịch comptime là mã chết.)
        self._all_funcs = {
            it.name: it for it in self.prog.items
            if isinstance(it, A.Function) and it.body is not None
        }
        self.collect_const_values()
        self.collect_types()
        # Chia sẻ bảng giá trị enum cho codegen (để sinh hàm tên-biến-thể, khử
        # trùng nhãn 'case' theo giá trị) — tránh phụ thuộc ngược checker<-codegen.
        self.prog.enum_tables = self.enums
        self.collect_funcs()
        self.collect_globals()
        self._errors = []
        # Kiểm tra thuộc tính @ (đích hợp lệ, số/kiểu đối số) trước khi sinh mã
        # (phục hồi theo từng mục để báo hết một lượt).
        for it in self.prog.items:
            self.cur_file = getattr(it, "src_file", None)
            if isinstance(it, A.Function):
                self._recover(self.validate_attrs, getattr(it, "attrs", []), "fn", it)
            elif isinstance(it, A.StructDef):
                self._recover(self.validate_attrs, getattr(it, "attrs", []), "struct", it)
            elif isinstance(it, A.GlobalVar):
                self._recover(self.validate_attrs, getattr(it, "attrs", []), "global", it)
            elif isinstance(it, A.Impl):
                for m in it.methods:
                    self._recover(self.validate_attrs, getattr(m, "attrs", []), "fn", m)
        for it in self.prog.items:
            self.cur_file = getattr(it, "src_file", None)
            if isinstance(it, A.Function) and it.body is not None:
                self._recover(self.check_function, it)
            elif isinstance(it, A.Impl):
                for m in it.methods:
                    if m.body is not None:
                        self._recover(self.check_function, m)
        if self._errors:
            raise CheckErrors(self._errors)
        return self.prog

    def _recover(self, fn, *args):
        """Chạy 'fn' và NUỐT CheckError: ghi lại lỗi rồi tiếp tục để báo được
        nhiều lỗi trong một lần biên dịch. Phạm vi/scope được khôi phục về độ sâu
        trước khi gọi (câu lệnh lỗi có thể đã push mà chưa pop). Dừng thu thập
        khi vượt CheckErrors.MAX. Chỉ dùng ở ranh giới câu lệnh/hàm — bên trong
        biểu thức vẫn ném để không suy luận tiếp trên AST hỏng."""
        depth = len(self.scopes)
        loop_depth = self.loop_depth
        try:
            return fn(*args)
        except CheckError as e:
            errs = getattr(self, "_errors", None)
            if errs is None:
                raise
            del self.scopes[depth:]
            self.loop_depth = loop_depth
            errs.append(e)
            if len(errs) >= CheckErrors.MAX:
                raise CheckErrors(errs)
            return None

    # ---------- thuộc tính @ (ABI/bố cục cho phát triển hệ điều hành) ----------
    # tên -> (đích hợp lệ, số đối số, loại đối số)  loại: None | 'int' | 'str'
    _ATTR_TABLE = {
        "packed":    ({"struct"}, 0, None),
        "align":     ({"struct", "fn", "global"}, 1, "int"),
        "aligned":   ({"struct", "fn", "global"}, 1, "int"),
        "naked":     ({"fn"}, 0, None),
        "noreturn":  ({"fn"}, 0, None),
        "interrupt": ({"fn"}, 0, None),
        "inline":    ({"fn"}, 0, None),
        "used":      ({"fn", "global"}, 0, None),
        "section":   ({"fn", "global"}, 1, "str"),
    }

    def validate_attrs(self, attrs, kind, node):
        seen = {}
        for a in attrs:
            if a.name in seen:
                self.err(f"thuộc tính '@{a.name}' bị lặp lại", a)
            seen[a.name] = a
            spec = self._ATTR_TABLE.get(a.name)
            if spec is None:
                sug = suggest(a.name, set(self._ATTR_TABLE))
                msg = f"thuộc tính '@{a.name}' không nhận ra"
                if sug:
                    msg += f" — có phải '@{sug}'?"
                self.err(msg, a)
            targets, arity, argkind = spec
            if kind not in targets:
                self.err(
                    f"thuộc tính '@{a.name}' không áp dụng cho {kind} "
                    f"(chỉ: {', '.join(sorted(targets))})", a)
            if len(a.args) != arity:
                self.err(
                    f"thuộc tính '@{a.name}' cần {arity} đối số, nhận {len(a.args)}", a)
            if argkind == "int":
                v = self._fold_const_int(a.args[0])
                if v is None or v <= 0 or (v & (v - 1)) != 0:
                    self.err(
                        f"'@{a.name}' cần một hằng số nguyên dương là LUỸ THỪA CỦA "
                        f"HAI (vd 8, 16, 4096)", a)
            elif argkind == "str":
                if not isinstance(a.args[0], A.StrLit):
                    self.err(f"'@{a.name}' cần một chuỗi literal "
                             f"(vd '@{a.name}(\".text.boot\")')", a)
        if "align" in seen and "aligned" in seen:
            self.err("'@align' và '@aligned' là một — chỉ dùng một trong hai",
                     seen["aligned"])
        if "naked" in seen and "inline" in seen:
            self.err("'@naked' không kết hợp được với '@inline' (hàm naked không "
                     "có prologue/epilogue để inline)", seen["inline"])
        if kind == "fn" and "naked" in seen:
            self._check_naked_fn(node, seen["naked"])

    def _check_naked_fn(self, fn: A.Function, attr):
        """Hàm @naked KHÔNG có prologue/epilogue: C chỉ cho phép thân là asm
        thuần (gcc: 'basic asm' only) — biến cục bộ, biểu thức hay 'return' sẽ
        sinh mã dùng stack/thanh ghi chưa thiết lập (UB / lỗi gcc khó hiểu)."""
        if fn.name == "main":
            self.err("'main' không thể là @naked (điểm vào hosted cần "
                     "prologue/epilogue chuẩn)", attr)
            return
        if fn.is_extern or fn.body is None:
            return
        if fn.ret is not None and self.resolve(fn.ret).kind != "void":
            self.err(f"hàm @naked '{fn.name}' không thể khai báo kiểu trả về — "
                     f"không có epilogue C để trả giá trị; đặt kết quả vào "
                     f"thanh ghi bằng asm và bỏ '-> T'", attr)
        for st in fn.body:
            if not isinstance(st, A.Asm):
                self.err(f"thân hàm @naked '{fn.name}' chỉ được chứa khối "
                         f"'asm {{ ... }}' (gcc không cho phép mã C khác trong "
                         f"hàm naked)", st)
                break

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
        """Tính giá trị nguyên của biểu thức hằng (hoặc None nếu không thể).
        Hỗ trợ: literal, char, bool, tên hằng/biến thể enum, toán tử một/hai ngôi
        (kể cả so sánh & luận lý), ternary, ép kiểu, và LỜI GỌI hàm comptime/thuần
        (gấp qua một bộ thông dịch có giới hạn — xem _eval_const_call)."""
        if isinstance(e, A.IntLit):
            try:
                return int(e.value, 0)
            except ValueError:
                return None
        if isinstance(e, A.CharLit):
            return ord(e.value) if len(e.value) == 1 else None
        if isinstance(e, A.BoolLit):
            return 1 if e.value else 0
        if isinstance(e, A.Ident):
            v = self.const_ints.get(e.name)
            if v is not None:
                return v
            if e.name in self.enum_of_variant:
                return self.enums.get(self.enum_of_variant[e.name], {}).get(e.name)
            return None
        if isinstance(e, A.Unary):
            v = self._fold_const_int(e.operand)
            if v is None:
                return None
            return {"-": -v, "~": ~v, "+": v, "!": (0 if v else 1)}.get(e.op)
        if isinstance(e, A.Binary):
            if e.op in ("&&", "||"):    # đoản mạch
                a = self._fold_const_int(e.left)
                if a is None:
                    return None
                if e.op == "&&" and not a:
                    return 0
                if e.op == "||" and a:
                    return 1
                b = self._fold_const_int(e.right)
                return None if b is None else (1 if b else 0)
            a = self._fold_const_int(e.left)
            b = self._fold_const_int(e.right)
            if a is None or b is None:
                return None
            return self._ct_binop(e.op, a, b)
        if isinstance(e, A.Ternary):
            c = self._fold_const_int(e.cond)
            if c is None:
                return None
            return self._fold_const_int(e.then if c else e.els)
        if isinstance(e, A.Cast):
            return self._fold_const_int(e.expr)
        if isinstance(e, A.SizeOf) and not getattr(e, "align", False):
            # sizeof của kiểu nguyên thủy BỀ RỘNG CỐ ĐỊNH là hằng số biên dịch
            # độc lập nền tảng (i64 luôn 8 byte...) — gấp được để dùng làm cỡ
            # mảng '[sizeof(u32)]byte' hay giá trị enum. (alignof và sizeof của
            # int/usize/con trỏ/struct phụ thuộc ABI -> để codegen tự lo.)
            return self._sizeof_fixed(e.type)
        if isinstance(e, A.Call):
            return self._eval_const_call(e)
        return None

    # Cỡ (byte) các kiểu nguyên thủy bề rộng cố định — KHỚP <stdint.h> trên mọi
    # nền tảng (không gồm 'int'/'usize'/'isize'/con trỏ vì phụ thuộc ABI/word-size).
    _FIXED_SIZE = {
        "i8": 1, "u8": 1, "i16": 2, "u16": 2, "i32": 4, "u32": 4,
        "i64": 8, "u64": 8, "f32": 4, "f64": 8, "float": 4, "double": 8,
        "char": 1, "bool": 1,
    }

    def _sizeof_fixed(self, ty):
        """Cỡ byte của một kiểu VÔ HƯỚNG bề rộng cố định (hằng đa nền tảng), hoặc
        None nếu không chắc chắn (con trỏ/mảng/struct/int/usize...)."""
        if ty is None or getattr(ty, "is_fn", False):
            return None
        if ty.ptr or getattr(ty, "elem_ptr", 0) or ty.dims or ty.array is not None:
            return None
        return self._FIXED_SIZE.get(ty.name)

    # ---------- bộ thông dịch comptime (gấp lời gọi hàm lúc biên dịch) ----------
    @staticmethod
    def _ct_binop(op, a, b):
        """Phép toán hai ngôi trên số nguyên với ngữ nghĩa C (chia/lấy dư cắt về 0).
        Trả về None nếu không hợp lệ (chia 0, dịch âm) — caller coi là không-hằng."""
        if op == "/" or op == "%":
            if b == 0:
                return None
            q = abs(a) // abs(b)
            if (a < 0) != (b < 0):
                q = -q
            return q if op == "/" else a - q * b
        if op in ("<<", ">>"):
            if b < 0:
                return None
            return a << b if op == "<<" else a >> b
        return {
            "+": a + b, "-": a - b, "*": a * b,
            "&": a & b, "|": a | b, "^": a ^ b,
            "==": 1 if a == b else 0, "!=": 1 if a != b else 0,
            "<": 1 if a < b else 0, ">": 1 if a > b else 0,
            "<=": 1 if a <= b else 0, ">=": 1 if a >= b else 0,
            "&&": 1 if (a and b) else 0, "||": 1 if (a or b) else 0,
        }.get(op)

    def _eval_const_call(self, e: A.Call):
        """Gấp một lời gọi hàm thành hằng nguyên (nếu được). Dùng cho cỡ mảng
        '[sq(3)]int', giá trị enum, sizeof... Đánh giá thân hàm qua một bộ thông
        dịch CÓ GIỚI HẠN (ngân sách bước + độ sâu) trên tập con nguyên của G:
        let/assign/if/while/for/return + số học. Bất kỳ thứ gì ngoài tập đó ->
        None (không-hằng), an toàn rơi về chẩn đoán lỗi cũ."""
        funcs = getattr(self, "_all_funcs", None)
        if not funcs or not isinstance(e.func, A.Ident):
            return None
        argvals = []
        for a in e.args:
            v = self._fold_const_int(a)
            if v is None:
                return None
            argvals.append(v)
        try:
            return self._ct_call(e.func.name, argvals, [200000], 0)
        except (_CTAbort, _CTReturn):
            return None

    def _ct_call(self, name, argvals, budget, depth):
        if depth > 256:
            raise _CTAbort()
        if name in ("min", "max", "abs", "clamp"):
            return self._ct_builtin(name, argvals)
        fn = self._all_funcs.get(name)
        if fn is None or fn.body is None or len(argvals) != len(fn.params):
            raise _CTAbort()
        env = {p.name: v for p, v in zip(fn.params, argvals)}
        try:
            self._ct_body(fn.body, env, budget, depth + 1)
        except _CTReturn as r:
            if r.value is None:
                raise _CTAbort()
            return r.value
        raise _CTAbort()   # rơi khỏi thân mà không return giá trị

    @staticmethod
    def _ct_builtin(name, argvals):
        if name == "abs" and len(argvals) == 1:
            return abs(argvals[0])
        if name in ("min", "max") and len(argvals) == 2:
            return (min if name == "min" else max)(argvals[0], argvals[1])
        if name == "clamp" and len(argvals) == 3:
            x, lo, hi = argvals
            return lo if x < lo else (hi if x > hi else x)
        raise _CTAbort()

    def _ct_body(self, body, env, budget, depth):
        for st in body:
            self._ct_stmt(st, env, budget, depth)

    def _ct_tick(self, budget):
        budget[0] -= 1
        if budget[0] <= 0:
            raise _CTAbort()

    def _ct_stmt(self, st, env, budget, depth):
        self._ct_tick(budget)
        if isinstance(st, A.Let):
            env[st.name] = (self._ct_expr(st.value, env, budget, depth)
                            if st.value is not None else 0)
        elif isinstance(st, A.Assign):
            if not isinstance(st.target, A.Ident):
                raise _CTAbort()
            rhs = self._ct_expr(st.value, env, budget, depth)
            if st.op == "=":
                env[st.target.name] = rhs
            else:
                cur = env.get(st.target.name)
                if cur is None:
                    raise _CTAbort()
                r = self._ct_binop(st.op[:-1], cur, rhs)
                if r is None:
                    raise _CTAbort()
                env[st.target.name] = r
        elif isinstance(st, A.Return):
            raise _CTReturn(self._ct_expr(st.value, env, budget, depth)
                            if st.value is not None else None)
        elif isinstance(st, A.If):
            if self._ct_expr(st.cond, env, budget, depth):
                self._ct_body(st.then, env, budget, depth)
            elif st.els is not None:
                self._ct_body(st.els, env, budget, depth)
        elif isinstance(st, A.While):
            while self._ct_expr(st.cond, env, budget, depth):
                self._ct_tick(budget)
                self._ct_body(st.body, env, budget, depth)
        elif isinstance(st, A.For):
            start = self._ct_expr(st.start, env, budget, depth)
            end = self._ct_expr(st.end, env, budget, depth)
            step = (self._ct_expr(st.step, env, budget, depth)
                    if st.step is not None else 1)
            if step == 0:
                raise _CTAbort()
            i = start
            while (i <= end if st.inclusive else i < end) if step > 0 \
                    else (i >= end if st.inclusive else i > end):
                self._ct_tick(budget)
                env[st.var] = i
                self._ct_body(st.body, env, budget, depth)
                i += step
        elif isinstance(st, A.Block):
            self._ct_body(st.body, env, budget, depth)
        elif isinstance(st, A.ExprStmt):
            self._ct_expr(st.expr, env, budget, depth)
        else:
            raise _CTAbort()   # match/defer/asm/... : không gấp được

    def _ct_expr(self, e, env, budget, depth):
        self._ct_tick(budget)
        if isinstance(e, A.IntLit):
            try:
                return int(e.value, 0)
            except ValueError:
                raise _CTAbort()
        if isinstance(e, A.CharLit):
            if len(e.value) == 1:
                return ord(e.value)
            raise _CTAbort()
        if isinstance(e, A.BoolLit):
            return 1 if e.value else 0
        if isinstance(e, A.Ident):
            if e.name in env:
                return env[e.name]
            if e.name in self.const_ints:
                return self.const_ints[e.name]
            if e.name in self.enum_of_variant:
                return self.enums[self.enum_of_variant[e.name]][e.name]
            raise _CTAbort()
        if isinstance(e, A.Unary):
            v = self._ct_expr(e.operand, env, budget, depth)
            if e.op == "-":
                return -v
            if e.op == "~":
                return ~v
            if e.op == "+":
                return v
            if e.op == "!":
                return 0 if v else 1
            raise _CTAbort()
        if isinstance(e, A.Binary):
            a = self._ct_expr(e.left, env, budget, depth)
            if e.op == "&&":
                return 1 if (a and self._ct_expr(e.right, env, budget, depth)) else 0
            if e.op == "||":
                return 1 if (a or self._ct_expr(e.right, env, budget, depth)) else 0
            b = self._ct_expr(e.right, env, budget, depth)
            r = self._ct_binop(e.op, a, b)
            if r is None:
                raise _CTAbort()
            return r
        if isinstance(e, A.Ternary):
            c = self._ct_expr(e.cond, env, budget, depth)
            return self._ct_expr(e.then if c else e.els, env, budget, depth)
        if isinstance(e, A.Cast):
            return self._ct_expr(e.expr, env, budget, depth)
        if isinstance(e, A.Call) and isinstance(e.func, A.Ident):
            argvals = [self._ct_expr(a, env, budget, depth) for a in e.args]
            return self._ct_call(e.func.name, argvals, budget, depth)
        raise _CTAbort()

    # ---------- thu thập khai báo ----------
    def collect_types(self):
        # Lượt 1: đăng ký TÊN struct/enum trước để cho phép tham chiếu tiến (forward).
        for it in self.prog.items:
            if isinstance(it, (A.StructDef, A.EnumDef)):
                self.cur_file = getattr(it, "src_file", None)
                kind = "struct" if isinstance(it, A.StructDef) else "enum"
                # Trùng tên kiểu (struct-struct, enum-enum, struct-enum, hay đè
                # lên kiểu nguyên thuỷ) -> C 'redefinition'/'conflicting types'.
                if it.name in self.structs or it.name in self.enums:
                    prev = "struct" if it.name in self.structs else "enum"
                    self.err(f"{kind} '{it.name}' được định nghĩa nhiều lần "
                             f"(đã có {prev} cùng tên)", it)
                if it.name in T.PRIMITIVES:
                    self.err(f"không thể đặt tên {kind} là '{it.name}' (trùng kiểu "
                             f"nguyên thuỷ)", it)
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
                # Ghi DẦN vào chính dict đã tạo ở lượt 1 (không tạo dict mới), để
                # một biến thể tham chiếu được biến thể TRƯỚC trong cùng enum khi
                # gấp hằng (vd 'enum E { A = 1 << 2, B, C = A + 10 }').
                table = self.enums[it.name]
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
                    # Giá trị biến thể là một BIỂU THỨC HẰNG (không chỉ literal):
                    # '1 << 2', 'A + 10', '-1', tên hằng... Gấp về số nguyên để
                    # bảng enum của checker KHỚP giá trị C thật. (Trước đây chỉ
                    # nhận IntLit/-IntLit nên mọi biểu thức khác bị ghi sai giá
                    # trị -> sai cỡ mảng '[V]int', sai gấp comptime, và nhãn
                    # 'case' trùng giá trị không được khử -> lỗi biên dịch C.)
                    if vval is not None:
                        folded = self._fold_const_int(vval)
                        if folded is not None:
                            nxt = folded
                        # Không gấp được (vd 'sizeof' struct): giữ bộ đếm tự tăng
                        # như cũ — codegen vẫn phát sinh đúng biểu thức cho C.
                    table[vname] = nxt
                    self.enum_of_variant[vname] = it.name
                    nxt += 1
        self._check_struct_value_cycles()

    def _check_struct_value_cycles(self):
        """Bắt struct chứa CHÍNH NÓ theo GIÁ TRỊ (trực tiếp hoặc gián tiếp) — kích
        thước vô hạn, C báo 'field has incomplete type' khó hiểu. Trường con trỏ
        (*T), con trỏ phần tử ([N]*T) và con trỏ hàm KHÔNG tạo chu trình (đủ một
        forward-decl). Mảng-theo-giá-trị '[N]T' VẪN nhúng theo giá trị nên tính."""
        sdefs = {it.name: it for it in self.prog.items
                 if isinstance(it, A.StructDef)}
        # Cạnh phụ thuộc theo-giá-trị: name -> {tên struct nhúng trực tiếp}.
        deps = {}
        for name, s in sdefs.items():
            d = set()
            for f in s.fields:
                ft = f.type
                if (ft.ptr == 0 and getattr(ft, "elem_ptr", 0) == 0
                        and not getattr(ft, "is_fn", False)
                        and ft.name in sdefs):
                    d.add(ft.name)
            deps[name] = d
        # DFS tìm chu trình; báo lỗi tại struct đầu tiên (theo thứ tự khai báo).
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in sdefs}

        def visit(n, path):
            color[n] = GRAY
            for m in deps[n]:
                if color[m] == GRAY:
                    cyc = path[path.index(m):] + [m] if m in path else [n, m]
                    chain = " -> ".join(cyc)
                    who = sdefs[n]
                    self.cur_file = getattr(who, "src_file", None)
                    self.err(
                        f"struct '{n}' chứa chính nó theo giá trị (chu trình "
                        f"{chain}) — kích thước vô hạn; dùng con trỏ '*{m}' để phá "
                        f"vòng", who)
                if color[m] == WHITE:
                    visit(m, path + [m])
            color[n] = BLACK

        for n in sdefs:
            if color[n] == WHITE:
                visit(n, [n])

    def collect_funcs(self):
        for it in self.prog.items:
            if isinstance(it, A.Function):
                self.cur_file = getattr(it, "src_file", None)
                # Hàm G (có thân, không 'extern') trùng tên hàm libc -> lỗi C khó
                # hiểu về sau. Báo sớm bằng chẩn đoán G rõ ràng.
                if (it.body is not None and not it.is_extern
                        and it.name in LIBC_NAMES):
                    self.err(
                        f"tên hàm '{it.name}' trùng với hàm thư viện chuẩn C "
                        f"(runtime nạp sẵn) — đổi tên (vd '{it.name}_g' hoặc một "
                        f"tên khác) để tránh xung đột khi biên dịch", it)
                # Định nghĩa trùng (cả hai có thân) sinh lỗi redefinition trong C.
                # Một prototype 'extern' + một định nghĩa thì hợp lệ.
                prev = self.func_defs.get(it.name)
                if (prev is not None and prev.body is not None
                        and it.body is not None):
                    self.err(f"hàm '{it.name}' được định nghĩa nhiều lần", it)
                elif prev is not None and (prev.is_extern or it.is_extern):
                    # Hai khai báo cùng tên (extern + extern / extern + định
                    # nghĩa) phải CÙNG chữ ký — C báo 'conflicting types'.
                    sig_prev = self._sig_text(prev)
                    sig_new = self._sig_text(it)
                    if sig_prev != sig_new:
                        self.err(
                            f"'{it.name}' được khai báo lại với chữ ký khác: "
                            f"trước là 'fn {it.name}{sig_prev}', nay là "
                            f"'fn {it.name}{sig_new}'", it)
                self.register_func(it)
            elif isinstance(it, A.Impl):
                self.cur_file = getattr(it, "src_file", None)
                if it.struct not in self.structs and it.struct not in self.enums:
                    sug = suggest(it.struct, set(self.structs) | set(self.enums))
                    msg = f"'impl {it.struct}': không có struct/enum tên '{it.struct}'"
                    if sug:
                        msg += f" — có phải '{sug}'?"
                    self.err(msg, it)
                self.methods.setdefault(it.struct, {})
                for m in it.methods:
                    if m.name in self.methods[it.struct]:
                        self.err(
                            f"method '{it.struct}.{m.name}' được định nghĩa "
                            f"nhiều lần", m)
                    # Method TĨNH (không có 'self' đầu tiên): gọi qua 'Type.name(...)'.
                    m.is_static = not (m.params and m.params[0].name == "self")
                    if it.struct in self.enums and not m.is_static:
                        # 'self' của method trên enum là *Enum (parser đặt ptr=1)
                        # — giữ nguyên, codegen cast như struct.
                        pass
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
        # Đồng thời bắt KHAI BÁO TRÙNG: hai global cùng tên (hoặc global trùng tên
        # một hàm) sinh 'redefinition'/'redeclared' trong C — báo sớm bằng lỗi G.
        for it in self.prog.items:
            if isinstance(it, A.GlobalVar):
                self.cur_file = getattr(it, "src_file", None)
                if it.name in self.globals:
                    self.err(
                        f"biến toàn cục '{it.name}' được khai báo nhiều lần", it)
                if it.name in self.funcs:
                    self.err(
                        f"biến toàn cục '{it.name}' trùng tên với một hàm đã "
                        f"khai báo", it)
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
                        self._check_array_lit_shape(it.value, gt, it)
                        self._check_int_div_to_float(it.value, gt, it)
                elif it.value is not None:
                    gt = self.infer(it.value)
                else:
                    gt = T.INT
                it.resolved_type = gt
                self.globals[it.name] = (gt, it.mutable and not it.is_const)
        self._check_global_init_order()

    def _check_global_init_order(self):
        """Initializer của global chỉ được tham chiếu global khai báo TRƯỚC nó.
        Global không-hằng được khởi tạo lúc chạy theo thứ tự khai báo (constructor),
        nên tham chiếu tiến/chu trình ('const A = B + 1; const B = A + 1') đọc giá
        trị 0 chưa khởi tạo một cách âm thầm. Qua lời gọi hàm thì không truy vết
        (hàm có thể đọc global — chấp nhận, như C)."""
        seen = set()
        for it in self.prog.items:
            if not isinstance(it, A.GlobalVar):
                continue
            self.cur_file = getattr(it, "src_file", None)
            if it.value is not None:
                for ref in self._global_refs(it.value):
                    if ref == it.name:
                        self.err(f"global '{it.name}' tự tham chiếu trong giá trị "
                                 f"khởi tạo của chính nó", it)
                    if ref not in seen:
                        self.err(
                            f"giá trị khởi tạo của '{it.name}' dùng global '{ref}' "
                            f"khai báo SAU nó — lúc đó '{ref}' chưa được khởi tạo "
                            f"(đọc 0). Đổi thứ tự khai báo", it)
            seen.add(it.name)

    def _global_refs(self, e):
        """Tên các global được đọc trực tiếp trong biểu thức (không đi vào lời gọi)."""
        out = []
        if isinstance(e, A.Ident):
            if e.name in self.globals:
                out.append(e.name)
        elif isinstance(e, A.Binary):
            out += self._global_refs(e.left) + self._global_refs(e.right)
        elif isinstance(e, A.Unary):
            out += self._global_refs(e.operand)
        elif isinstance(e, A.Ternary):
            out += self._global_refs(e.cond) + self._global_refs(e.then) + self._global_refs(e.els)
        elif isinstance(e, A.Cast):
            out += self._global_refs(e.expr)
        elif isinstance(e, A.Index):
            out += self._global_refs(e.base) + self._global_refs(e.index)
        elif isinstance(e, A.FieldAccess):
            out += self._global_refs(e.base)
        elif isinstance(e, A.ArrayLit):
            for x in e.elements:
                out += self._global_refs(x)
        elif isinstance(e, A.StructLit):
            for _, v in e.fields:
                out += self._global_refs(v)
        return out

    def _sig_text(self, fn: A.Function) -> str:
        params = ", ".join(self.tyname(self.resolve(p.type)) for p in fn.params)
        ret = self.resolve(fn.ret)
        return f"({params})" + ("" if ret.kind == "void" else f" -> {self.tyname(ret)}")

    def register_func(self, fn: A.Function):
        params = tuple(self.resolve(p.type) for p in fn.params)
        ret = self.resolve(fn.ret)
        self.funcs[fn.name] = T.GType("func", params=params, ret=ret)
        self.func_defs[fn.name] = fn

    # ---------- phân giải kiểu cú pháp -> GType ----------
    def resolve(self, ty: A.Type) -> T.GType:
        if ty is None:
            return T.UNKNOWN
        # ----- chiều mảng: fold về số nguyên & ghi lại vào node (cho codegen) -----
        # Bọc từ chiều TRONG ra NGOÀI: [N][M]T = array(N, array(M, T)).
        dims = ty.dims if ty.dims is not None else (
            [ty.array] if ty.array is not None else [])
        dims = [self._fold_dim(d, ty) for d in dims]
        if ty.dims is not None:
            ty.dims = dims
            ty.array = dims[0] if dims else None
        elif ty.array is not None and dims:
            ty.array = dims[0]
        # ----- kiểu cơ sở -----
        if getattr(ty, "is_fn", False):
            pts = tuple(self.resolve(p) for p in (ty.fn_params or []))
            rt = self.resolve(ty.fn_ret) if ty.fn_ret is not None else T.VOID
            g = T.GType("func", params=pts, ret=rt)
        else:
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
        # con trỏ-phần-tử ([N]*T) -> bọc mảng (trong->ngoài) -> con trỏ ngoài (*[N]T)
        for _ in range(getattr(ty, "elem_ptr", 0)):
            g = T.ptr_of(g)
        for d in reversed(dims):
            g = T.array_of(g, d)
        for _ in range(ty.ptr):
            g = T.ptr_of(g)
        return g

    def _fold_dim(self, d, ty):
        """Chuyển một chiều mảng thành số nguyên dương. Chấp nhận: số, tên hằng,
        hoặc biểu thức hằng (literal/tên hằng/phép toán giữa hằng). 'dyn' giữ
        nguyên. Không fold được hoặc không dương -> lỗi rõ ràng."""
        if d == "dyn":
            return d
        if isinstance(d, int):
            v = d
        elif isinstance(d, str):   # tên hằng trần (đường cũ, giữ tương thích)
            v = getattr(self, "const_ints", {}).get(d)
            if v is None:
                raise CheckError(
                    f"cỡ mảng '{d}' phải là hằng số nguyên đã biết "
                    f"(const/let bất biến gán giá trị hằng)", ty.line, ty.col,
                    self.cur_file)
        else:                      # nút biểu thức AST: '[N+1]', '[2*CAP]'...
            v = self._fold_const_int(d)
            if v is None:
                raise CheckError(
                    "cỡ mảng phải là biểu thức hằng số nguyên (literal, tên hằng, "
                    "hoặc phép toán giữa các hằng đã biết)", ty.line, ty.col,
                    self.cur_file)
        if v <= 0:
            raise CheckError(
                f"cỡ mảng = {v} phải là số dương", ty.line, ty.col, self.cur_file)
        return v

    # ---------- scope ----------
    def push(self):
        self.scopes.append({})

    def pop(self):
        self.scopes.pop()

    def declare(self, name, gt, mutable):
        """Khai báo biến cục bộ; cấp một tên C duy nhất để cho phép shadowing
        (C cấm khai báo lại trong cùng scope). Trả về tên C đã cấp."""
        cname = self.safe_c_name(name)
        if (cname in self.fn_cnames or name in self.globals
                or name in self.funcs or name in self.func_defs):
            # Trùng với tên đã dùng trong hàm, với GLOBAL hoặc với HÀM toàn cục:
            # cấp tên mới. (Nếu giữ nguyên, 'let x = x + 1' với x global sẽ thành
            # 'int x = x + 1' trong C — tự tham chiếu biến chưa khởi tạo.)
            k = 1
            while (f"{cname}_s{k}" in self.fn_cnames or f"{cname}_s{k}" in self.globals
                   or f"{cname}_s{k}" in self.funcs):
                k += 1
            cname = f"{cname}_s{k}"
        self.fn_cnames.add(cname)
        self.scopes[-1][name] = (gt, mutable, cname)
        return cname

    # Từ khoá / định danh dành riêng của C (và tên macro/hàm libc hay gặp) không
    # được dùng làm tên C: đổi tên bằng hậu tố '_g' (người dùng G không thấy).
    C_RESERVED = frozenset("""
        auto break case char const continue default do double else enum extern
        float for goto if inline int long register restrict return short signed
        sizeof static struct switch typedef union unsigned void volatile while
        _Bool _Complex _Imaginary _Static_assert _Noreturn _Alignas _Alignof
        _Atomic _Generic _Thread_local
        NULL EOF stdin stdout stderr errno bool true false
        main printf puts putchar malloc calloc realloc free exit abort memcpy
        memset memmove memcmp strlen strcmp strcpy strcat strncpy strncmp
        abs labs llabs div atoi atol atof time clock rand srand
        isatty fileno fprintf sprintf snprintf sscanf scanf getchar fgets fputs
        fopen fclose fread fwrite fflush
        int8_t int16_t int32_t int64_t uint8_t uint16_t uint32_t uint64_t
        size_t ptrdiff_t intptr_t uintptr_t
    """.split())

    @classmethod
    def safe_c_name(cls, name: str) -> str:
        """Tên C an toàn cho một định danh G (biến/trường/biến thể enum)."""
        if name in cls.C_RESERVED or name.startswith("_g") or name.startswith("__"):
            return name + "_g"
        return name

    def lookup(self, name):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        if name in self.globals:
            g = self.globals[name]
            return (g[0], g[1], self.safe_c_name(name))   # global: tên C = chính nó (đã làm sạch)
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
            if dst.kind == "func":
                return self._func_compatible(dst, src)
            return True
        # Số thực -> số nguyên/char/bool NGẦM: mất phần lẻ âm thầm ('let n: int
        # = 1.5' -> 1). Bắt buộc ép kiểu tường minh 'x as int' (như Rust/Go).
        if src.kind == "float" and dst.kind in ("int", "char", "bool"):
            return False
        # Số -> bool ngầm ('let b: bool = 5') cũng từ chối: viết 'x != 0'.
        if dst.kind == "bool" and src.kind in ("int", "float", "char"):
            return False
        numeric = ("int", "float", "char", "bool")
        if dst.kind in numeric and src.kind in numeric:
            return True
        # enum -> số: cho phép ngầm (giá trị enum là số nguyên). Số -> enum thì
        # KHÔNG (có thể tạo giá trị không thuộc biến thể nào; 'match' rơi qua âm
        # thầm) — yêu cầu 'x as E' tường minh.
        if src.kind == "enum" and dst.kind in ("int", "char"):
            return True
        return False

    def _func_compatible(self, dst: T.GType, src: T.GType) -> bool:
        """Hai kiểu con trỏ hàm có tương thích để gán/truyền không? Cần KHỚP cả
        số tham số, kiểu từng tham số, lẫn kiểu trả về (gán một hàm sai chữ ký vào
        biến/tham số fn(...)->R sinh lời gọi sai ABI -> hành vi không xác định ở C).
        Kiểm theo hai chiều (mỗi vị trí phải gán được cả tới lẫn lui) để không nới
        quá lỏng — vd không cho lẫn lộn 'int' với 'str'. 'unknown' được bỏ qua."""
        if len(dst.params) != len(src.params):
            return False
        for dp, sp in zip(dst.params, src.params):
            if dp.kind == "unknown" or sp.kind == "unknown":
                continue
            if not (self.assignable(dp, sp) and self.assignable(sp, dp)):
                return False
        dr = dst.ret if dst.ret is not None else T.VOID
        sr = src.ret if src.ret is not None else T.VOID
        if dr.kind == "unknown" or sr.kind == "unknown":
            return True
        return self.assignable(dr, sr) and self.assignable(sr, dr)

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
            p.c_name = self.declare(p.name, self.resolve(p.type), True)
        self.cur_ret = self.resolve(fn.ret)
        if self.cur_ret.kind == "array":
            self.err(
                f"hàm '{fn.name}' không thể trả về mảng theo giá trị "
                f"('{self.tyname(self.cur_ret)}') — hãy bọc mảng trong struct, "
                f"hoặc nhận con trỏ tới bộ đệm đầu ra làm tham số", fn)
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
            # Phục hồi theo từng câu lệnh: lỗi ở câu này không chặn kiểm tra câu
            # sau (biến 'let' lỗi vẫn được khai báo kiểu 'unknown' — xem check_let).
            self._recover(self.check_stmt, st)
        self.pop()
        self._check_unreachable(body)

    @staticmethod
    def _stmt_pos(st):
        """Nút mang vị trí (line/col) cho một câu lệnh — lần vào biểu thức/câu
        lệnh con với các nút bọc không có line/col riêng (ExprStmt, Defer)."""
        if isinstance(st, A.ExprStmt):
            return st.expr
        if isinstance(st, A.Defer):
            return Checker._stmt_pos(st.stmt)
        return st

    def _hard_diverges(self, st) -> bool:
        """Câu lệnh thoát TƯỜNG MINH (return/break/continue/panic/unreachable/todo).
        Khác _stmt_diverges: KHÔNG tính diverge suy luận (match vét cạn, if-else đều
        thoát, loop vô hạn) — vì mã sau những cấu trúc đó thường là 'return phòng
        thủ' hợp lệ. Chỉ mã sau một terminator tường minh mới chắc chắn là chết."""
        if isinstance(st, (A.Return, A.Break, A.Continue)):
            return True
        if isinstance(st, A.ExprStmt):
            return self._expr_diverges(st.expr)   # panic/unreachable/todo
        return False

    def _check_unreachable(self, body):
        """Báo lỗi nếu một câu lệnh nằm NGAY SAU một câu lệnh thoát tường minh
        ('return'/'break'/'continue'/'panic'...) trong cùng khối — mã đó không bao
        giờ chạy, gần như luôn là sót lại hoặc nhầm luồng."""
        for i in range(len(body) - 1):
            if self._hard_diverges(body[i]):
                self.err(
                    "mã không thể tới được: câu lệnh này nằm sau một câu lệnh luôn "
                    "thoát ('return'/'break'/'continue'/'panic') — hãy xoá hoặc sửa "
                    "lại luồng điều khiển",
                    self._stmt_pos(body[i + 1]))
                return

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
        if isinstance(st, A.While):
            # 'while true' / 'while 1' / 'while <hằng khác 0>' là vòng lặp vô hạn
            # (như 'loop') -> diverge nếu không có 'break' thoát ra. Điều kiện gấp
            # được thành hằng khác 0 lúc biên dịch mới tính (bảo toàn).
            c = self._fold_const_int(st.cond)
            if c is not None and c != 0:
                return not self._has_break(st.body)
            return False
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

    def _check_return_local_addr(self, v, st):
        """'return &x' / 'return &arr[i]' / 'return arr' với x/arr là BIẾN CỤC BỘ
        (không phải tham số con trỏ/global): trả về con trỏ tới stack frame đã bị
        huỷ -> segfault/rác âm thầm. Bắt tĩnh trường hợp trực tiếp."""
        root = None
        if isinstance(v, A.Unary) and v.op == "&":
            root = v.operand
            # đi về biến gốc qua .field / [i] (không đi qua con trỏ)
            while True:
                if isinstance(root, A.FieldAccess):
                    bt = getattr(root.base, "gtype", None)
                    if bt is not None and bt.kind == "ptr":
                        return
                    root = root.base
                elif isinstance(root, A.Index):
                    bt = getattr(root.base, "gtype", None)
                    if bt is None or bt.kind != "array" or bt.n == "dyn":
                        return
                    root = root.base
                else:
                    break
        elif isinstance(v, A.Ident):
            vt = getattr(v, "gtype", None)
            if vt is not None and self._is_static_array(vt):
                root = v          # mảng tĩnh cục bộ phân rã thành con trỏ
        if not isinstance(root, A.Ident):
            return
        name = root.name
        # cục bộ (trong scopes, KHÔNG phải global)?
        local = any(name in sc for sc in self.scopes)
        if not local:
            return
        info = self.lookup(name)
        if info is None:
            return
        # tham số/biến kiểu con trỏ hoặc []T trỏ ra ngoài frame -> 'return &p[i]'
        # đã bị loại ở trên (bt.kind != array). Còn lại: ô nhớ trong frame.
        self.err(f"trả về địa chỉ của biến cục bộ '{name}' — bộ nhớ này bị huỷ "
                 f"khi hàm kết thúc (con trỏ treo). Cấp phát heap (g_alloc) hoặc "
                 f"nhận con trỏ tới bộ đệm đầu ra làm tham số", st)

    def _match_covers_enum(self, st: A.Match) -> bool:
        """match trên enum có liệt kê HẾT mọi variant không (vét cạn không cần '_')."""
        subj_t = getattr(st, "subject_type", None)
        if subj_t is not None and subj_t.kind == "bool":
            # bool: 'true' và 'false' (không guard) là vét cạn.
            covered = set()
            for pats, guard, _ in st.arms:
                if pats is None or guard is not None:
                    continue
                for p in pats:
                    if isinstance(p, A.BoolLit):
                        covered.add(bool(p.value))
            return covered == {True, False}
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
                pv = self._pat_variant(p)
                if pv is not None and pv in all_variants:
                    covered.add(pv)
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
            try:
                self._check_let(st)
            except CheckError:
                # Vẫn khai báo biến (kiểu 'unknown') để các câu sau không báo
                # thêm hàng loạt "chưa khai báo" vô ích khi phục hồi lỗi.
                if self.scopes and st.name not in self.scopes[-1]:
                    gt = T.UNKNOWN
                    if st.type is not None:
                        try:
                            gt = self.resolve(st.type)
                        except CheckError:
                            gt = T.UNKNOWN
                    st.resolved_type = gt
                    st.c_name = self.declare(st.name, gt, st.mutable)
                raise
            return
        self._check_stmt(st)

    def _check_let(self, st: A.Let):
        if True:
            # Mảng literal có chú thích kiểu: cho phép phần tử 'null' (kiểu đích
            # là mảng con trỏ) — gắn kiểu mong đợi trước khi suy luận.
            if isinstance(st.value, A.ArrayLit) and st.type is not None:
                try:
                    st.value.expected = self.resolve(st.type)
                except CheckError:
                    pass
            # 'const N = ...' CỤC BỘ cũng là hằng biên dịch: ghi vào const_ints để
            # dùng được làm cỡ mảng ('[N]int') và số lần lặp ('[v; N]'), giống
            # const toàn cục. Tên bị che (shadow) sẽ ghi đè — đúng phạm vi từ đây.
            if getattr(st, "is_const", False) and st.value is not None:
                cv = self._fold_const_int(st.value)
                if cv is not None:
                    self.const_ints[st.name] = cv
                else:
                    self.const_ints.pop(st.name, None)
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
                    self._check_array_lit_shape(st.value, gt, st)
                    self._check_int_div_to_float(st.value, gt, st)
            else:
                gt = val_t if val_t is not None else T.INT
            st.resolved_type = gt
            st.c_name = self.declare(st.name, gt, st.mutable)

    def _check_stmt(self, st):
        if isinstance(st, A.Return):
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
                self._check_int_range(st.value, self.cur_ret, st)
                self._check_int_div_to_float(st.value, self.cur_ret, st)
                self._check_return_local_addr(st.value, st)
            elif self.cur_ret.kind != "void":
                self.err(
                    f"hàm '{self.cur_fn}' cần trả về '{self.tyname(self.cur_ret)}'", st)
        elif isinstance(st, A.If):
            self._check_cond(st.cond, "if")
            self.check_block(st.then)
            if st.els is not None:
                self.check_block(st.els)
        elif isinstance(st, A.While):
            self._check_cond(st.cond, "while")
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
            self._check_defer_escape(st)
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
        elif isinstance(st, A.Asm):
            if not st.code.strip() and not st.outputs and not st.inputs:
                self.err("khối 'asm { }' rỗng — cần ít nhất một chuỗi lệnh "
                         "(vd asm { \"cli\" })", st)
            # Ràng buộc toán hạng phải hợp lệ: output bắt đầu bằng '=' hoặc '+',
            # input KHÔNG được có '=' (gcc báo 'invalid lvalue'/'output operand
            # constraint lacks =' khó hiểu).
            for cons, ex in getattr(st, "outputs", []):
                if not cons or cons[0] not in "=+":
                    self.err(f"ràng buộc output asm \"{cons}\" phải bắt đầu bằng "
                             f"'=' (ghi) hoặc '+' (đọc-ghi)", st)
            for cons, ex in getattr(st, "inputs", []):
                if cons and cons[0] in "=+":
                    self.err(f"ràng buộc input asm \"{cons}\" không được có '='/'+' "
                             f"(chỉ output mới ghi)", st)
            # asm mở rộng: phân giải các toán hạng (gắn gtype/c_name, bắt biến chưa
            # khai báo). Toán hạng output phải là ô nhớ (lvalue) khả biến.
            for cons, ex in getattr(st, "outputs", []):
                self.infer(ex)
                if not self._is_lvalue(ex):
                    self.err("toán hạng output ('=...') của asm phải là một ô nhớ "
                             "(biến/trường/phần tử/*con_trỏ)", st)
                self._check_lvalue_mutable(ex, st)
            for cons, ex in getattr(st, "inputs", []):
                self.infer(ex)

    def check_for(self, st: A.For):
        st_t = self.infer(st.start)
        en_t = self.infer(st.end)
        if st.step is not None:
            self.infer(st.step)
            sv = self._fold_const_int(st.step)
            if sv is not None and sv == 0:
                self.err("bước lặp 'step 0' không hợp lệ (vòng lặp sẽ không bao giờ "
                         "tiến — lặp vô hạn hoặc không chạy)", st)
        if st_t.is_numeric() and en_t.is_numeric():
            vt = T.common_numeric(st_t, en_t)
            if vt.kind == "float":
                vt = T.I64
        else:
            vt = T.INT
        st.var_type = vt
        self.loop_depth += 1
        self.push()
        # Biến đếm của 'for i in a..b' là BẤT BIẾN (như Rust): gán vào nó sẽ làm
        # hỏng chính vòng lặp (nó là biến đếm C). Muốn sửa thì 'let mut j = i'.
        st.c_name = self.declare(st.var, vt, False)
        rv = getattr(self, "_range_vars", None)
        if rv is None:
            rv = self._range_vars = set()
        rv.add(st.var)
        for s in st.body:
            self._recover(self.check_stmt, s)
        rv.discard(st.var)
        self.pop()
        self.loop_depth -= 1
        self._check_unreachable(st.body)

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
        self._check_unreachable(st.body)

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

    def _pat_variant(self, p):
        """Tên biến thể enum của một pattern ('Red' hoặc 'Color.Red'), hoặc None."""
        if isinstance(p, A.Ident) and p.name in self.enum_of_variant:
            return p.name
        ev = getattr(p, "enum_variant", None)
        if ev is not None:
            return ev[1]
        return None

    def check_match(self, st: A.Match):
        subj_t = self.infer(st.subject)
        # 'match self' trong method của enum (self: *Enum): tự giải tham chiếu.
        if subj_t.kind == "ptr" and subj_t.elem is not None and subj_t.elem.kind == "enum":
            st.deref_subject = True
            subj_t = subj_t.elem
        has_default = False
        str_subj = subj_t.kind == "str" or (
            subj_t.kind == "ptr" and subj_t.elem and subj_t.elem.kind == "char")
        st.bindings = []
        for pats, guard, body in st.arms:
            bind = self._binding_name(pats)
            # Subject là enum mà nhánh là một tên VIẾT HOA chưa biết ('C' khi enum
            # chỉ có A, B): gần như chắc chắn là gõ sai tên biến thể — nếu coi là
            # binding thì nó bắt-tất cả và nuốt luôn các nhánh sau (bẫy Rust).
            if (bind is not None and subj_t.kind == "enum" and bind[:1].isupper()):
                sug = suggest(bind, set(self.enums.get(subj_t.name, {})))
                msg = (f"'{bind}' không phải biến thể của enum '{subj_t.name}' "
                       f"(sẽ bị hiểu là binding bắt mọi giá trị)")
                if sug:
                    msg += f" — có phải '{sug}'?"
                self.err(msg, pats[0])
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
                        # Biến thể enum làm pattern phải thuộc ĐÚNG enum của
                        # subject — 'match sign { Red => }' (Red thuộc Color) gần
                        # như luôn là lỗi; C lại so hai số enum nên chạy sai âm thầm.
                        pv = self._pat_variant(p)
                        pe = (getattr(p, "enum_variant", (None,))[0]
                              or (self.enum_of_variant.get(pv) if pv else None))
                        if (subj_t.kind == "enum" and pv is not None
                                and pe != subj_t.name):
                            self.err(
                                f"biến thể '{pv}' thuộc enum "
                                f"'{pe}' nhưng subject của "
                                f"match là kiểu '{subj_t.name}'", p)
            if guard is not None:
                gt = self.infer(guard)
                if gt.kind not in ("bool", "unknown", "int", "char"):
                    self.err("điều kiện 'if' trong match phải là biểu thức luận lý", guard)
            if getattr(st, "is_expr", False):
                # match-BIỂU THỨC: 'body' là một biểu thức giá trị, không phải
                # danh sách câu lệnh. Suy kiểu trong phạm vi có binding.
                st.arm_types.append(self.infer(body))
            else:
                for s in body:
                    self.check_stmt(s)
            self.pop()
            if not getattr(st, "is_expr", False):
                self._check_unreachable(body)
            st.bindings.append(bind_cname)
        st.subject_type = subj_t
        st.has_default = has_default
        self._check_match_arms_reachable(st, subj_t)
        # match trên enum KHÔNG có nhánh bắt-tất ('_'/binding trần) phải phủ HẾT
        # mọi biến thể; nếu thiếu, có giá trị rơi qua âm thầm (không nhánh nào chạy).
        if subj_t.kind == "enum" and not has_default:
            all_v = set(self.enums.get(subj_t.name, {}))
            covered = set()
            for pats, guard, _ in st.arms:
                if pats is None or guard is not None:
                    continue
                for p in pats:
                    pv = self._pat_variant(p)
                    if pv is not None and pv in all_v:
                        covered.add(pv)
            missing = all_v - covered
            if all_v and missing:
                self.err(
                    f"match trên enum '{subj_t.name}' chưa vét cạn — thiếu biến "
                    f"thể: {', '.join(sorted(missing))} (liệt kê đủ hoặc thêm nhánh "
                    f"'_')", st)

    def infer_match_expr(self, e: A.MatchExpr) -> T.GType:
        """'let v = match x { p => val, ... }'. Dùng lại toàn bộ kiểm tra của
        match-câu-lệnh (vét cạn, nhánh chết, binding, guard) qua cờ 'is_expr',
        rồi hợp nhất kiểu của các nhánh. Vì biểu thức LUÔN phải cho một giá trị,
        match-biểu thức bắt buộc vét cạn (enum/bool đủ nhánh, hoặc có '_')."""
        e.arm_types = []
        e.is_expr = True
        self.check_match(e)
        subj_t = e.subject_type
        exhaustive = e.has_default
        if not exhaustive and subj_t.kind in ("enum", "bool"):
            exhaustive = self._match_covers_enum(e)
        if not exhaustive:
            self.err(
                "'match' ở vị trí biểu thức phải vét cạn (luôn cho một giá trị) — "
                "thêm nhánh '_ => ...' để bắt các trường hợp còn lại", e)
        ts = [t for t in e.arm_types if t.kind != "unknown"]
        if not ts:
            return T.UNKNOWN
        res = ts[0]
        for i, t in enumerate(ts[1:], start=2):
            if res.is_numeric() and t.is_numeric():
                res = T.common_numeric(res, t)
                continue
            if not (self.assignable(res, t) or self.assignable(t, res)):
                self.err(
                    f"các nhánh của 'match' phải cùng kiểu: nhánh 1 cho "
                    f"'{self.tyname(res)}' nhưng nhánh {i} cho '{self.tyname(t)}'",
                    e)
                break
        e.result_type = res
        return res

    def _check_match_arms_reachable(self, st: A.Match, subj_t: T.GType):
        """Bắt nhánh match KHÔNG BAO GIỜ chạy: (1) nhánh sau một nhánh bắt-tất
        ('_' hoặc binding trần, không guard); (2) pattern hằng lặp lại một
        pattern đã có ở nhánh trước (không guard) — nhánh đầu luôn thắng."""
        seen = {}          # khoá pattern -> chỉ số nhánh
        ranges = []        # [(lo, hi, idx)] các khoảng số nguyên đã gặp (không guard)
        catch_all_at = None
        bools_seen = set()
        for idx, (pats, guard, _body) in enumerate(st.arms):
            if catch_all_at is not None:
                self.err(
                    f"nhánh match thứ {idx + 1} không bao giờ chạy — nhánh "
                    f"{catch_all_at + 1} ('_'/binding) đã bắt mọi giá trị", st)
            bind = self._binding_name(pats)
            if (pats is None or bind is not None) and guard is None:
                catch_all_at = idx
                continue
            if pats is None or bind is not None:
                continue
            for p in pats:
                if isinstance(p, A.RangePat):
                    lo = self._fold_const_int(p.lo)
                    hi = self._fold_const_int(p.hi)
                    if lo is None or hi is None:
                        continue
                    if not p.inclusive:
                        hi -= 1
                    if lo > hi:
                        self.err(f"khoảng pattern rỗng ({lo}..{'=' if p.inclusive else ''}"
                                 f"{self._fold_const_int(p.hi)}) — không giá trị nào khớp", p)
                    if guard is None:
                        for (plo, phi, pidx) in ranges:
                            if plo <= lo and hi <= phi:
                                self.err(f"khoảng pattern này nằm trọn trong khoảng ở "
                                         f"nhánh {pidx + 1} — nhánh này không bao giờ "
                                         f"chạy", p)
                                break
                        ranges.append((lo, hi, idx))
                    continue
                key = self._pat_key(p, subj_t)
                if key is None:
                    continue
                if key in seen and guard is None:
                    self.err(
                        f"pattern '{key[1]}' lặp lại (đã có ở nhánh {seen[key] + 1}) "
                        f"— nhánh này không bao giờ chạy", p)
                if key[0] in ("int", "char") and guard is None:
                    v = key[1] if key[0] == "int" else (
                        ord(key[1]) if isinstance(key[1], str) and len(key[1]) == 1 else None)
                    for (plo, phi, pidx) in ranges:
                        if v is not None and plo <= v <= phi:
                            self.err(f"pattern '{key[1]}' đã nằm trong khoảng ở nhánh "
                                     f"{pidx + 1} — nhánh này không bao giờ chạy", p)
                            break
                if key[0] == "bool":
                    bools_seen.add(key[1])
                seen.setdefault(key, idx)
        # match trên bool phải vét cạn (true & false hoặc '_'), như enum.
        if (subj_t.kind == "bool" and catch_all_at is None
                and bools_seen != {True, False}):
            missing = ", ".join(str(b).lower() for b in ({True, False} - bools_seen))
            self.err(f"match trên bool chưa vét cạn — thiếu: {missing} "
                     f"(thêm nhánh hoặc '_')", st)

    def _pat_key(self, p, subj_t: T.GType):
        """Khoá so trùng cho pattern hằng: ('int', giá trị) / ('str', chuỗi) /
        ('enum', tên biến thể). None nếu không phải hằng đơn giản."""
        if isinstance(p, A.RangePat):
            return None
        pv = self._pat_variant(p)
        if pv is not None:
            return ("enum", pv)
        if isinstance(p, A.StrLit):
            return ("str", p.value)
        if isinstance(p, A.CharLit):
            return ("char", p.value)
        if isinstance(p, A.BoolLit):
            return ("bool", bool(p.value))
        v = self._fold_const_int(p)
        if v is not None and not isinstance(p, A.Ident):
            return ("int", v)
        return None

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
        # Số học con trỏ qua '+='/'-=' : 'p += n' / 'p -= n' với p là con trỏ (hoặc
        # []T phân rã) và n nguyên — hợp lệ trong C, di chuyển con trỏ n phần tử.
        if st.op in ("+=", "-=") and self._ptrlike(tt) and vt.is_integer():
            return
        if not self.assignable(tt, vt):
            self.err(
                f"không thể gán giá trị kiểu '{self.tyname(vt)}' cho ô nhớ kiểu "
                f"'{self.tyname(tt)}'", st)
        if st.op == "=":
            self._check_int_range(st.value, tt, st)
            self._check_int_div_to_float(st.value, tt, st)

    def _is_range_loop_var(self, name) -> bool:
        return name in getattr(self, "_range_vars", set())

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
                        f"không thể gán cho '{e.name}' (bất biến — dùng 'let mut'"
                        + ("; biến đếm 'for i in a..b' không sửa được — sao chép ra "
                           "'let mut j = i'" if self._is_range_loop_var(e.name) else "")
                        + ")",
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
                if bt is not None and bt.kind == "str":
                    # 'str' là 'const char*' (literal nằm trong vùng chỉ đọc):
                    # ghi 's[i] = c' là lỗi C / segfault. Cần bộ đệm char riêng.
                    self.err("không thể ghi vào phần tử của 'str' (chuỗi chỉ đọc) "
                             "— sao chép sang bộ đệm '[N]char' hoặc dùng "
                             "'*char' cấp phát riêng rồi ghi", stmt)
                # index qua con trỏ / mảng động (đều là con trỏ heap) -> cho phép
                if bt is not None and (bt.kind == "ptr"
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
        if target is None or target.kind != "int":
            return
        bounds = self._INT_BOUNDS.get(target.name)
        if bounds is None:
            return
        lo, hi = bounds
        v = self._int_literal_value(value_node)
        if v is not None:
            if not (lo <= v <= hi):
                self.err(
                    f"số {v} vượt giới hạn kiểu '{target.name}' "
                    f"(hợp lệ: {lo}..{hi})", ctx_node)
            return
        # Biểu thức HẰNG (vd '100000 * 100000', 'CAP * 4'): gấp rồi kiểm — C sẽ
        # tràn âm thầm trong 'int' 32-bit và cho kết quả sai.
        if isinstance(value_node, (A.Binary, A.Unary)) and not self._mentions_runtime_value(value_node):
            cv = self._fold_const_int(value_node)
            if cv is not None and not (lo <= cv <= hi):
                self.err(
                    f"biểu thức hằng có giá trị {cv} vượt giới hạn kiểu "
                    f"'{target.name}' (hợp lệ: {lo}..{hi}) — dùng kiểu rộng hơn "
                    f"(vd i64) hoặc ép kiểu tường minh", ctx_node)

    def _check_array_lit_shape(self, value_node, target: T.GType, ctx_node):
        """Mảng literal KHÔNG được nhiều phần tử hơn cỡ mảng tĩnh đã khai báo.
        C chỉ cảnh báo 'excess elements' rồi cắt bớt âm thầm (mất dữ liệu) — bắt
        sớm thành lỗi G rõ ràng. Ít phần tử hơn vẫn HỢP LỆ (đệm 0, kiểu Go/C).
        Kiểm đệ quy cho mảng nhiều chiều. Chỉ áp khi cả hai bên là mảng/literal."""
        if not isinstance(value_node, A.ArrayLit) or target is None:
            return
        if target.kind != "array" or target.n in (None, "dyn"):
            return
        n = len(value_node.elements)
        if n > target.n:
            self.err(
                f"mảng literal có {n} phần tử nhưng kiểu '{self.tyname(target)}' "
                f"chỉ chứa {target.n} (thừa {n - target.n} phần tử sẽ bị cắt)",
                ctx_node)
        # Đệ quy vào từng phần tử nếu phần tử lại là mảng (nhiều chiều).
        if target.elem is not None and target.elem.kind == "array":
            for el in value_node.elements:
                self._check_array_lit_shape(el, target.elem, ctx_node)

    def _check_int_div_to_float(self, value_node, target: T.GType, ctx_node):
        """Bắt bẫy kinh điển: chia hai số NGUYÊN rồi gán cho kiểu thực — phần lẻ
        bị cắt TRƯỚC khi đổi sang float ('let x: f64 = 7 / 2' -> 3.0, không phải
        3.5). Chỉ xét phép chia ở mức ngoài cùng (rõ ràng là chủ ý sai), không
        truy sâu để tránh báo nhầm chỉ số nguyên trong biểu thức thực."""
        if target is None or target.kind != "float":
            return
        if isinstance(value_node, A.Binary) and value_node.op == "/":
            lt = getattr(value_node.left, "gtype", None)
            rt = getattr(value_node.right, "gtype", None)
            if (lt is not None and rt is not None
                    and lt.is_integer() and rt.is_integer()):
                self.err(
                    "chia hai số NGUYÊN rồi mới đổi sang số thực — phần lẻ bị cắt "
                    "(vd '7 / 2' = 3.0, không phải 3.5). Ép một toán hạng sang thực "
                    "để chia thực: '(a as f64) / b'", ctx_node)

    def _check_defer_escape(self, st):
        """Câu lệnh trong 'defer' KHÔNG được chuyển điều khiển ra ngoài defer
        (return, hoặc break/continue nhắm tới vòng lặp bao ngoài). Những thứ này
        vô nghĩa về ngữ nghĩa VÀ làm trình sinh mã đệ quy vô hạn (xả-defer khi
        return lại kích hoạt xả-defer). break/continue cho một vòng lặp NẰM TRONG
        defer thì hợp lệ."""
        kw = self._defer_escape_kw(st, in_loop=False)
        if kw is not None:
            self.err(
                f"không thể dùng '{kw}' trong 'defer' — câu lệnh defer chỉ chạy khi "
                f"rời phạm vi (thường là dọn dẹp); chuyển điều khiển ('{kw}') ra "
                f"ngoài là không hợp lệ", self._stmt_pos(st.stmt))

    def _defer_escape_kw(self, st, in_loop):
        if isinstance(st, A.Return):
            return "return"
        if isinstance(st, A.Break):
            return None if in_loop else "break"
        if isinstance(st, A.Continue):
            return None if in_loop else "continue"
        if isinstance(st, A.Defer):
            return self._defer_escape_kw(st.stmt, in_loop)
        if isinstance(st, A.Block):
            return self._first_escape(st.body, in_loop)
        if isinstance(st, A.If):
            return (self._first_escape(st.then, in_loop)
                    or self._first_escape(st.els or [], in_loop))
        if isinstance(st, (A.While, A.Loop, A.For, A.ForEach)):
            # vòng lặp bên trong defer: break/continue của NÓ là hợp lệ, nhưng
            # 'return' vẫn thoát khỏi hàm -> vẫn cấm.
            return self._first_escape(getattr(st, "body", []), in_loop=True)
        if isinstance(st, A.Match):
            for _, _, b in st.arms:
                r = self._first_escape(b, in_loop)
                if r:
                    return r
        return None

    def _first_escape(self, body, in_loop):
        for s in body:
            r = self._defer_escape_kw(s, in_loop)
            if r:
                return r
        return None

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
            # Suy luận BỀ RỘNG theo giá trị (như C/Rust): literal vừa i32 -> int;
            # vượt i32 nhưng vừa i64 -> i64; chỉ vừa u64 -> u64. Nhờ vậy
            # '5000000000' hay '0xFFFFFFFFFF' in/đánh giá đúng 64-bit thay vì bị
            # cắt cụt về i32. (Gán literal lớn vào kiểu nhỏ vẫn bị _check_int_range
            # bắt riêng — đây chỉ là kiểu khi KHÔNG có chú thích.)
            if v <= (1 << 31) - 1:
                return T.INT
            if v <= (1 << 63) - 1:
                return T.I64
            return T.U64
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
            self._check_cond(e.cond, "?:")
            a = self.infer(e.then)
            b = self.infer(e.els)
            if a.is_numeric() and b.is_numeric():
                return T.common_numeric(a, b)
            return a if a.kind != "unknown" else b
        if isinstance(e, A.MatchExpr):
            return self.infer_match_expr(e)
        if isinstance(e, A.Call):
            return self.infer_call(e)
        if isinstance(e, A.Index):
            return self.infer_index(e)
        if isinstance(e, A.FieldAccess):
            return self.infer_field(e)
        if isinstance(e, A.Cast):
            src = self.infer(e.expr)
            rt = self.resolve(e.type)
            # 'as' chỉ ép được sang/từ kiểu VÔ HƯỚNG hoặc CON TRỎ. Ép sang mảng
            # hoặc struct là vô nghĩa và sinh C không hợp lệ ('(int[3])x' / '(P)x').
            # Mảng nguồn được CHO PHÉP (tự phân rã thành con trỏ: 'arr as *int').
            ok_target = ("int", "float", "char", "bool", "ptr", "str", "null",
                         "enum", "func", "unknown")
            if rt.kind not in ok_target:
                self.err(
                    f"không thể ép kiểu ('as') sang '{self.tyname(rt)}' — chỉ ép "
                    f"được sang kiểu vô hướng (số/bool/char), con trỏ, enum hoặc "
                    f"con trỏ hàm", e)
            if src.kind in ("struct", "void"):
                self.err(
                    f"không thể ép kiểu ('as') một giá trị kiểu '{self.tyname(src)}'",
                    e)
            # Số thực <-> con trỏ: C không cho phép ('(int*)1.5' là lỗi cú pháp C).
            if (src.kind == "float" and rt.kind in ("ptr", "func", "str")) or \
                    (rt.kind == "float" and src.kind in ("ptr", "func", "str", "null")):
                self.err(
                    f"không thể ép kiểu ('as') giữa số thực '{self.tyname(src if src.kind == 'float' else rt)}' "
                    f"và con trỏ/chuỗi — ép qua số nguyên trước (vd 'p as usize as f64')", e)
            # Số -> bool qua 'as': C cho '(bool)5' = true nhưng ý đồ thường mơ hồ;
            # G yêu cầu viết rõ 'x != 0'.
            if rt.kind == "bool" and src.kind in ("int", "float", "char", "ptr", "str", "func"):
                self.err(
                    f"không thể ép '{self.tyname(src)}' sang 'bool' bằng 'as' — viết rõ "
                    f"'x != 0' (số) hoặc 'p != null' (con trỏ)", e)
            # Chuỗi literal/str -> số nguyên: gần như luôn nhầm với parse_int.
            if src.kind == "str" and rt.kind in ("int", "float", "char"):
                self.err(
                    f"không thể ép chuỗi 'str' sang '{self.tyname(rt)}' bằng 'as' — "
                    f"dùng parse_int/parse_float (std) hoặc 'as usize' nếu muốn địa chỉ", e)
            return rt
        if isinstance(e, A.SizeOf):
            # Fold chiều mảng tượng trưng/biểu thức khi base là KIỂU thật (kể cả
            # kiểu hàm) — để 'sizeof([CAP+1]int)' thành hằng số biên dịch. Còn
            # 'sizeof(biến)' (name là tên biến) thì để codegen tự lo.
            if getattr(e.type, "is_fn", False) or e.type.name in self.type_names:
                self.resolve(e.type)
            return T.USIZE
        if isinstance(e, A.SizeOfExpr):
            self.infer(e.expr)
            return T.USIZE
        if isinstance(e, A.ArrayLit):
            # '[v; N]': nhân bản phần tử thành N bản ngay tại đây, sau đó mọi
            # bước sau (suy kiểu, sinh mã, len()) dùng chung đường mảng literal.
            if getattr(e, "repeat", None) is not None:
                n = self._fold_const_int(e.repeat)
                if n is None:
                    self.err("số phần tử của '[v; N]' phải là HẰNG số nguyên biết "
                             "lúc biên dịch (cỡ mảng tĩnh) — dùng g_alloc cho cỡ "
                             "động", e)
                    n = 1
                elif n <= 0:
                    self.err(f"số phần tử của '[v; N]' phải > 0, nhận {n}", e)
                    n = 1
                elif n > 65536:
                    self.err(f"'[v; {n}]' quá lớn để trải thành mảng tĩnh "
                             f"(tối đa 65536) — dùng g_alloc + vòng lặp", e)
                    n = 1
                e.elements = e.elements * n
                e.repeat = None
            if not e.elements:
                self.err("mảng literal rỗng '[]' không suy luận được kiểu/cỡ — khai "
                         "báo kiểu tường minh và điền phần tử (vd 'let a: [4]int = "
                         "[0, 0, 0, 0]') hoặc dùng g_alloc cho mảng động", e)
                return T.array_of(T.INT, 0)
            elem = self.infer(e.elements[0])
            for i, el in enumerate(e.elements[1:], start=2):
                et = self.infer(el)
                # Mọi phần tử phải CÙNG kiểu (số với số thì được — C thăng cấp;
                # mảng lồng so theo phần tử). '[1, "x"]' từng lọt xuống C.
                if elem.kind == "unknown" or et.kind == "unknown":
                    continue
                if not (self.assignable(elem, et) or self.assignable(et, elem)):
                    self.err(
                        f"mảng literal có phần tử không cùng kiểu: phần tử 1 là "
                        f"'{self.tyname(elem)}' nhưng phần tử {i} là "
                        f"'{self.tyname(et)}'", el)
                # Kiểu chung cho số: 'int' + 'f64' -> mảng f64; 'int' + 'i64' -> i64.
                if elem.is_numeric() and et.is_numeric() and elem.kind != "char" \
                        and et.kind != "char":
                    elem = T.common_numeric(elem, et)
            exp = getattr(e, "expected", None)
            if elem.kind == "null" and exp is not None and exp.kind == "array" \
                    and exp.elem is not None and self._ptrlike(exp.elem):
                elem = exp.elem
            if elem.kind in ("null", "void"):
                self.err(
                    "không suy luận được kiểu phần tử của mảng literal "
                    f"('{self.tyname(elem)}') — khai báo kiểu tường minh, vd "
                    "'let a: [2]*int = [null, null]'", e)
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
            e.is_enum_variant = True
            return T.GType("enum", name=self.enum_of_variant[e.name])
        if e.name in self.funcs:
            fdef = self.func_defs.get(e.name)
            # Hàm extern (libc/asm) giữ NGUYÊN tên C; hàm G thường được làm sạch
            # (tránh trùng từ khoá C như 'switch', 'default'...).
            e.c_name = e.name if (fdef is not None and fdef.is_extern) \
                else self.safe_c_name(e.name)
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

    _REL_OPS = {"<", ">", "<=", ">="}

    # Họ builtin so sánh hai giá trị (hiển thị trái/phải khi sai). assert_* dừng
    # chương trình, check_* ghi nhận rồi tiếp tục. eq/ne so BẰNG (gồm struct/chuỗi
    # theo nội dung); lt/le/gt/ge so THỨ TỰ (số/char/enum/chuỗi).
    _CMP_BUILTINS = {
        "assert_eq", "assert_ne", "assert_lt", "assert_le", "assert_gt", "assert_ge",
        "check_eq", "check_ne", "check_lt", "check_le", "check_gt", "check_ge",
    }

    def infer_binary(self, e: A.Binary):
        # Bắt "so sánh dây chuyền" kiểu toán học: 'a < b < c' trong C/G nghĩa là
        # '(a < b) < c' (so sánh một bool với c) — gần như luôn là lỗi. Báo lỗi
        # rõ ràng thay vì để chương trình chạy sai âm thầm.
        if e.op in self._REL_OPS:
            for side in (e.left, e.right):
                if isinstance(side, A.Binary) and side.op in self._REL_OPS:
                    self.err(
                        f"so sánh dây chuyền '{side.op}' ... '{e.op}' không có nghĩa "
                        f"như toán học (kết hợp trái: '(a {side.op} b) {e.op} c' so "
                        f"sánh một bool) — tách bằng '&&': '(a {side.op} b) && "
                        f"(b {e.op} c)'", e)
        lt = self.infer(e.left)
        rt = self.infer(e.right)
        op = e.op
        unk = lt.kind == "unknown" or rt.kind == "unknown"
        if op in ("&&", "||"):
            return T.BOOL
        if op in ("==", "!=", "<", ">", "<=", ">="):
            eq_op = op in ("==", "!=")
            ok = self._eq_comparable(lt, rt) if eq_op else self._comparable(lt, rt)
            # So sánh THỨ TỰ hai chuỗi bằng '<'/'>' là so ĐỊA CHỈ trong C — gần như
            # luôn là lỗi. (== / != trên chuỗi thì so nội dung, xem codegen.)
            if (not eq_op and lt.kind == "str" and rt.kind == "str"):
                ok = False
            if not unk and not ok:
                hint = ""
                if "str" in (lt.kind, rt.kind):
                    hint = (" (chuỗi: '==' so nội dung; thứ tự dùng strcmp(a, b) < 0)"
                            if not eq_op else " (chuỗi: dùng streq/strcmp)")
                elif not eq_op and "struct" in (lt.kind, rt.kind):
                    hint = " (struct chỉ so được bằng '=='/'!=' — theo từng trường)"
                self.err(
                    f"không thể so sánh '{self.tyname(lt)}' với '{self.tyname(rt)}'"
                    + hint, e)
            return T.BOOL
        if op in ("<<", ">>", "&", "|", "^"):
            if not unk and not (lt.is_integer() and rt.is_integer()):
                self.err(
                    f"toán tử bit '{op}' cần hai số nguyên, nhận "
                    f"'{self.tyname(lt)}' và '{self.tyname(rt)}'", e)
            # Lượng dịch là HẰNG: bắt các dạng hành vi không xác định của C.
            #  • dịch ÂM: luôn UB.
            #  • dịch >= 64 bit: vượt mọi kiểu nguyên của G (UB kể cả khi đã 64-bit).
            #  • dịch >= bề rộng của một TOÁN HẠNG TRÁI không-hằng (biến kiểu hẹp):
            #    'x: i32 << 40' là UB — không thể nâng bề rộng vì không biết giá trị.
            # Riêng '<<' khi toán hạng trái LÀ hằng (vd '1 << 40') thì an toàn nâng
            # lên 64-bit bên dưới (codegen ép '(int64_t)1 << 40'), nên không báo.
            if op in ("<<", ">>"):
                d = "trái" if op == "<<" else "phải"
                sh = self._fold_const_int(e.right)
                left_const = self._fold_const_int(e.left) is not None
                if sh is not None and sh < 0:
                    self.err(
                        f"dịch {d} một lượng âm ({sh}) là hành vi không xác định", e)
                elif sh is not None and sh >= 64:
                    self.err(
                        f"dịch {d} {sh} bit vượt 64-bit (hành vi không xác định) — "
                        f"lượng dịch hợp lệ là 0..63", e)
                elif (sh is not None and not left_const and lt.kind == "int"
                        and lt.bits and sh >= lt.bits):
                    self.err(
                        f"dịch {d} {sh} bit vượt bề rộng kiểu '{self.tyname(lt)}' "
                        f"({lt.bits} bit) — hành vi không xác định; ép kiểu rộng hơn "
                        f"(vd '(x as i64) {op} {sh}') hoặc giảm lượng dịch", e)
            res = lt if lt.kind == "int" else T.INT
            # Hằng dịch trái cho kết quả vượt 32-bit phải được NÂNG bề rộng để C
            # không tính trong 'int' rồi cắt cụt: '1 << 40' = 0 nếu giữ i32. Suy
            # luận theo GIÁ TRỊ (như literal): vừa i64 -> i64, chỉ vừa u64 -> u64.
            if op == "<<" and res.kind == "int" and res.bits < 64:
                cv = self._fold_const_int(e)
                if cv is not None and not (-(1 << 31) <= cv <= (1 << 31) - 1):
                    res = T.I64 if -(1 << 63) <= cv <= (1 << 63) - 1 else T.U64
            return res
        # Chia/lấy dư cho HẰNG 0 là hành vi không xác định trong C — bắt sớm khi
        # mẫu số gấp được thành 0 lúc biên dịch (literal, tên hằng, biểu thức hằng).
        if op in ("/", "%") and not unk and lt.is_integer() and rt.is_integer():
            if self._fold_const_int(e.right) == 0:
                self.err(
                    f"{'chia' if op == '/' else 'lấy dư'} cho 0 — mẫu số là hằng "
                    f"số 0 (hành vi không xác định)", e)
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
            res = T.common_numeric(lt, rt)
            # char ⊕ char (vd 'z' - 'a') là KHOẢNG CÁCH/số, không phải ký tự —
            # trả 'int' như C thăng cấp (trước đây trả 'char' và in ra ký tự điều
            # khiển \x19). char ⊕ int đã cho int qua common_numeric.
            if lt.kind == "char" and rt.kind == "char":
                res = T.INT
            # Biểu thức HẰNG toàn số nguyên mà giá trị vượt 'int' 32-bit (vd
            # '100000 * 100000', 'CAP * CAP'): nâng lên i64/u64 như với literal
            # lớn — nếu không, C tính trong int và tràn âm thầm (1410065408).
            if (res.kind == "int" and res.bits <= 32 and op in ("+", "-", "*", "/", "%")
                    and lt.name in ("int", "i32", "i64", "u64") and rt.name in ("int", "i32", "i64", "u64")
                    and not self._mentions_runtime_value(e)):
                cv = self._fold_const_int(e)
                if cv is not None and not (-(1 << 31) <= cv <= (1 << 31) - 1):
                    e.widen_i64 = True
                    return T.I64 if -(1 << 63) <= cv <= (1 << 63) - 1 else T.U64
            return res
        if unk:
            return lt if lt.kind != "unknown" else rt
        hint = ""
        if "str" in (lt.kind, rt.kind):
            hint = " (G không nối chuỗi bằng '+' — dùng str_concat)"
        self.err(
            f"không thể dùng '{op}' giữa '{self.tyname(lt)}' và '{self.tyname(rt)}'"
            + hint, e)

    def _eq_comparable(self, a: T.GType, b: T.GType) -> bool:
        """Hai giá trị có so sánh BẰNG được không (cho assert_eq/check_eq)? Như
        '_comparable' nhưng cho thêm hai struct CÙNG loại (so theo trường). Mảng
        tĩnh trần KHÔNG hỗ trợ (mất độ dài khi phân rã — so từng phần tử thủ công)."""
        if a.kind == "unknown" or b.kind == "unknown":
            return True
        if a.kind == "struct" and b.kind == "struct":
            return a.name == b.name
        return self._comparable(a, b)

    def _comparable(self, a: T.GType, b: T.GType) -> bool:
        if a.is_numeric() and b.is_numeric():
            return True
        # Hai enum: CHỈ so sánh được khi cùng một enum (giá trị enum khác loại so
        # với nhau gần như luôn là lỗi logic). Kiểm tra trước nhánh tập rộng bên
        # dưới để không lọt 'EnumA == EnumB'.
        if a.kind == "enum" and b.kind == "enum":
            return a.name == b.name
        # bool CHỈ so với bool ('b == 1' / 'x == true' gần như luôn là lỗi logic;
        # 'let b: bool = 1' cũng đã bị từ chối — nhất quán).
        if a.kind == "bool" or b.kind == "bool":
            return a.kind == "bool" and b.kind == "bool"
        if {a.kind, b.kind} <= {"int", "char", "enum"}:
            return True
        # con trỏ so với con trỏ / null (con trỏ hàm cũng là con trỏ)
        ap = a.kind in ("ptr", "str", "null", "func") or self._is_dyn_array(a)
        bp = b.kind in ("ptr", "str", "null", "func") or self._is_dyn_array(b)
        if ap and bp:
            return True
        return False

    def infer_unary(self, e: A.Unary):
        ot = self.infer(e.operand)
        if e.op == "!":
            if ot.kind in ("str", "struct", "void") or self._is_static_array(ot):
                self.err(f"toán tử '!' không áp dụng cho giá trị kiểu "
                         f"'{self.tyname(ot)}'", e)
            return T.BOOL
        if e.op == "&":
            # '&' chỉ lấy được địa chỉ của một Ô NHỚ (lvalue). '&(a+b)', '&f()',
            # '&(x as T)'... là rvalue -> C báo "lvalue required" khó hiểu; bắt sớm.
            if not self._is_lvalue(e.operand):
                self.err(
                    "không thể lấy địa chỉ ('&') của giá trị tạm — chỉ lấy được "
                    "địa chỉ của ô nhớ (biến/trường/phần tử/*con_trỏ). Gán vào một "
                    "'let' trước rồi lấy '&' của biến đó", e)
            return T.ptr_of(ot)
        if e.op == "*":
            if ot.kind == "ptr":
                return ot.elem
            if ot.kind == "str":
                return T.CHAR
            if ot.kind == "array":
                return ot.elem
            if ot.kind == "unknown":
                return T.UNKNOWN
            self.err(
                f"không thể giải tham chiếu ('*') giá trị kiểu '{self.tyname(ot)}' "
                f"(chỉ áp dụng cho con trỏ)", e)
        if e.op in ("-", "~") and ot.kind != "unknown" and not ot.is_numeric():
            self.err(f"toán tử '{e.op}' cần một số, nhận '{self.tyname(ot)}'", e)
        if e.op == "~" and ot.kind == "float":
            self.err("toán tử '~' (đảo bit) chỉ áp dụng cho số nguyên, nhận "
                     f"'{self.tyname(ot)}'", e)
        if e.op == "-":
            # Phủ định số KHÔNG DẤU / hẹp: C thăng cấp lên int rồi in theo kiểu
            # cũ ('-a' với a: u8 in ra 4294967291). Kết quả của '-' là kiểu CÓ DẤU
            # ít nhất 32 bit (như C thực sự tính) — 'u64' giữ nguyên (không có
            # kiểu có dấu rộng hơn; người dùng chủ ý làm số học modulo).
            if ot.kind == "char":
                return T.INT
            if ot.kind == "int":
                if ot.bits < 32:
                    return T.INT
                if not ot.signed and ot.bits == 32:
                    e.widen_signed = True     # codegen: '-(int64_t)w'
                    return T.I64
            return ot
        if e.op == "~":
            if ot.kind == "char" or (ot.kind == "int" and ot.bits < 32):
                return T.INT
            return ot
        return ot

    @staticmethod
    def _is_lvalue(e) -> bool:
        """Biểu thức có phải ô nhớ lấy địa chỉ được (lvalue) không? Biến/trường/
        phần tử/deref con trỏ là lvalue; lời gọi, toán tử, ép kiểu, literal là rvalue."""
        if isinstance(e, (A.Ident, A.FieldAccess, A.Index)):
            return True
        return isinstance(e, A.Unary) and e.op == "*"

    def _require_numeric_args(self, name, types, node):
        for i, t in enumerate(types, start=1):
            if t.kind != "unknown" and not t.is_numeric():
                self.err(f"{name}(): tham số {i} phải là số, nhận '{self.tyname(t)}'",
                         node)

    def _check_cond(self, cond, where: str) -> T.GType:
        """Điều kiện của if/while/?: phải là bool (hoặc số/con trỏ — kiểu C, so
        với 0/null). Chuỗi, struct, mảng tĩnh, void... không phải điều kiện:
        'if s' với s: str luôn đúng (con trỏ khác null) — gần như luôn là lỗi."""
        ct = self.infer(cond)
        if ct.kind in ("str", "struct", "void") or self._is_static_array(ct):
            hint = ""
            if ct.kind == "str":
                hint = " — muốn kiểm tra rỗng dùng 'strlen(s) == 0' hoặc so sánh '=='"
            elif ct.kind == "void":
                hint = " — hàm không trả về giá trị"
            self.err(
                f"điều kiện '{where}' không thể là giá trị kiểu '{self.tyname(ct)}'"
                f"{hint}", cond)
        return ct

    def infer_index(self, e: A.Index):
        bt = self.infer(e.base)
        it = self.infer(e.index)
        if not it.is_integer() and it.kind != "unknown":
            self.err(f"chỉ số mảng phải là số nguyên, nhận '{self.tyname(it)}'", e)
        if bt.kind in ("array", "ptr"):
            # Chỉ số HẰNG trên mảng TĨNH: bắt vượt biên ngay lúc biên dịch (C chỉ
            # cảnh báo rồi đọc/ghi bộ nhớ lân cận — UB âm thầm).
            if bt.kind == "array" and isinstance(bt.n, int):
                iv = self._fold_const_int(e.index)
                if iv is not None and (iv < 0 or iv >= bt.n):
                    self.err(
                        f"chỉ số {iv} vượt biên mảng '{self.tyname(bt)}' "
                        f"(hợp lệ: 0..{bt.n - 1})", e)
            return bt.elem
        if bt.kind == "str":
            # Chuỗi LITERAL + chỉ số hằng: kiểm biên ngay (kể cả '\0' cuối).
            if isinstance(e.base, A.StrLit):
                iv = self._fold_const_int(e.index)
                n = len(e.base.value.encode("utf-8"))
                if iv is not None and (iv < 0 or iv > n):
                    self.err(f"chỉ số {iv} vượt biên chuỗi literal dài {n} "
                             f"(hợp lệ: 0..{n}, {n} là ký tự kết thúc '\\0')", e)
            return T.CHAR
        if bt.kind == "unknown":
            return T.UNKNOWN
        self.err(f"không thể lập chỉ số trên '{self.tyname(bt)}' "
                 f"(chỉ mảng, con trỏ hoặc chuỗi)", e)

    def _type_name_ident(self, e) -> str | None:
        """'e' là một Ident trỏ tới TÊN KIỂU (struct/enum) không bị biến che? Trả
        tên kiểu, ngược lại None. Dùng cho 'Enum.Variant' và 'Type.static_fn()'."""
        if isinstance(e, A.Ident) and self.lookup(e.name) is None \
                and e.name not in self.funcs:
            if e.name in self.enums or e.name in self.structs:
                return e.name
        return None

    def infer_field(self, e: A.FieldAccess):
        # 'Enum.Variant' — truy cập biến thể có tên đầy đủ (rõ ràng hơn tên trần,
        # tránh nhập nhằng khi hai enum trùng tên biến thể).
        tn = self._type_name_ident(e.base)
        if tn is not None and tn in self.enums:
            if e.field in self.enums[tn]:
                e.enum_variant = (tn, e.field)
                return T.GType("enum", name=tn)
            if tn in self.methods and e.field in self.methods[tn]:
                return T.UNKNOWN  # method tĩnh dùng như giá trị
            sug = suggest(e.field, set(self.enums[tn]))
            msg = f"enum '{tn}' không có biến thể '{e.field}'"
            if sug:
                msg += f" — có phải '{sug}'?"
            self.err(msg, e)
        if tn is not None and tn in self.structs:
            if tn in self.methods and e.field in self.methods[tn]:
                return T.UNKNOWN
            self.err(f"'{tn}.{e.field}': struct '{tn}' không có method tĩnh "
                     f"'{e.field}' (truy cập trường cần một GIÁ TRỊ struct)", e)
        bt = self.infer(e.base)
        e.auto_deref = (bt.kind == "ptr")
        sname = None
        if bt.kind == "struct":
            sname = bt.name
        elif bt.kind == "ptr" and bt.elem and bt.elem.kind == "struct":
            sname = bt.elem.name
        # Method trên ENUM: 'c.name' với c: Color (hoặc *Color).
        ename = None
        if bt.kind == "enum":
            ename = bt.name
        elif bt.kind == "ptr" and bt.elem and bt.elem.kind == "enum":
            ename = bt.elem.name
        if ename and ename in self.methods and e.field in self.methods[ename]:
            return T.UNKNOWN
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
        # Truy cập trường/method '.x' trên giá trị KHÔNG phải struct (int, mảng,
        # con trỏ tới phi-struct...) là vô nghĩa — C sẽ báo 'request for member in
        # something not a structure'. Bắt sớm thành lỗi G rõ ràng. 'unknown' giữ
        # nguyên để không báo nhầm khi kiểu chưa phân giải được.
        if bt.kind != "unknown":
            self.err(
                f"không thể truy cập trường/method '.{e.field}' trên giá trị kiểu "
                f"'{self.tyname(bt)}' (chỉ struct hoặc con trỏ tới struct mới có "
                f"trường)", e)
        return T.UNKNOWN

    # Method dựng sẵn trên 'str': tên -> (hàm runtime, kiểu tham số phụ, kiểu trả về,
    # có cấp phát heap không). Receiver là tham số đầu tiên của hàm runtime.
    # 'heap=True' -> kết quả là chuỗi MỚI, người dùng phải g_free.
    _STR_METHODS = {
        "len":         ("g_str_len_i",     [],            "usize", False),
        "is_empty":    ("g_str_is_empty",  [],            "bool",  False),
        "eq":          ("g_str_eq",        ["str"],       "bool",  False),
        "contains":    ("g_str_contains",  ["str"],       "bool",  False),
        "starts_with": ("g_str_starts_with", ["str"],     "bool",  False),
        "ends_with":   ("g_str_ends_with", ["str"],       "bool",  False),
        "index_of":    ("g_str_index_i",   ["str"],       "int",   False),
        "count":       ("g_str_count_i",   ["char"],      "int",   False),
        "at":          ("g_str_at",        ["int"],       "char",  False),
        "upper":       ("g_str_upper",     [],            "str",   True),
        "lower":       ("g_str_lower",     [],            "str",   True),
        "trim":        ("g_str_trim",      [],            "str",   True),
        "rev":         ("g_str_rev",       [],            "str",   True),
        "concat":      ("g_str_concat",    ["str"],       "str",   True),
        "repeat":      ("g_str_repeat_i",  ["int"],       "str",   True),
        "sub":         ("g_substr_i",      ["int", "int"], "str",  True),
        "to_int":      ("g_parse_int",     [],            "i64",   False),
        "to_float":    ("g_parse_float",   [],            "f64",   False),
    }

    def _check_str_method(self, e: A.Call, recv, mname: str) -> T.GType:
        """'s.upper()' / 's.contains(x)' — method dựng sẵn trên chuỗi."""
        spec = self._STR_METHODS.get(mname)
        if spec is None:
            sug = suggest(mname, set(self._STR_METHODS))
            msg = f"'str' không có method '{mname}'"
            if sug:
                msg += f" — có phải '{sug}'?"
            self.err(msg + f" (method của str: {', '.join(sorted(self._STR_METHODS))})",
                     e)
            return T.UNKNOWN
        cfn, params, ret, heap = spec
        e.is_str_method = True
        e.str_c_fn = cfn
        e.recv = recv
        arg_types = [self.infer(a) for a in e.args]
        if len(e.args) != len(params):
            self.err(f"'str.{mname}()' cần {len(params)} tham số nhưng nhận "
                     f"{len(e.args)}", e)
        for i, at in enumerate(arg_types[:len(params)]):
            want = T.PRIMITIVES.get(params[i]) or T.STR
            if not self.assignable(want, at):
                self.err(f"tham số {i + 1} của 'str.{mname}()' cần "
                         f"'{self.tyname(want)}' nhưng nhận '{self.tyname(at)}'", e)
        return T.PRIMITIVES.get(ret) or T.STR

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
            if fname in seen:
                self.err(
                    f"trường '{fname}' của struct '{e.name}' được gán nhiều lần "
                    f"trong cùng một literal", e)
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
            # ----- method TĨNH: Type.name(args) (không có self) -----
            tn = self._type_name_ident(recv)
            if tn is not None:
                m = self.methods.get(tn, {}).get(mname)
                if m is None:
                    cands = set(self.methods.get(tn, {}))
                    sug = suggest(mname, cands)
                    msg = f"'{tn}' không có method '{mname}'"
                    if sug:
                        msg += f" — có phải '{sug}'?"
                    self.err(msg, e)
                if not m.is_static:
                    self.err(
                        f"'{tn}.{mname}' là method THỂ HIỆN (có 'self') — gọi trên "
                        f"một giá trị: 'x.{mname}(...)'", e)
                e.is_static_method = True
                e.struct = tn
                e.method = mname
                arg_types = [self.infer(a) for a in e.args]
                if len(e.args) != len(m.params):
                    self.err(
                        f"method tĩnh '{tn}.{mname}' cần {len(m.params)} tham số "
                        f"nhưng nhận {len(e.args)}", e)
                for i, at in enumerate(arg_types):
                    pt = self.resolve(m.params[i].type)
                    if not self.assignable(pt, at):
                        self.err(
                            f"tham số {i + 1} của '{tn}.{mname}' cần "
                            f"'{self.tyname(pt)}' nhưng nhận '{self.tyname(at)}'", e)
                return self.resolve(m.ret)
            bt = self.infer(recv)
            # ----- method DỰNG SẴN trên 'str' ('s.len()', 's.upper()'...) -----
            # Cú pháp method cho kiểu nguyên thuỷ (không cần 'import std'): chỉ là
            # đường cú pháp gọi hàm runtime, receiver là tham số đầu.
            if bt.kind == "str" or (bt.kind == "ptr" and bt.elem
                                    and bt.elem.kind == "char"):
                return self._check_str_method(e, recv, mname)
            sname = bt.name if bt.kind in ("struct", "enum") else (
                bt.elem.name if bt.kind == "ptr" and bt.elem and bt.elem.kind in ("struct", "enum") else None)
            if sname and sname in self.methods and mname in self.methods[sname]:
                m = self.methods[sname][mname]
                if m.is_static:
                    self.err(
                        f"'{sname}.{mname}' là method TĨNH (không có 'self') — gọi "
                        f"qua tên kiểu: '{sname}.{mname}(...)'", e)
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
        # ----- gọi qua một định danh: biến/tham số CHE (shadow) hàm cùng tên -----
        # Một biến cục bộ/tham số/global trùng tên với hàm toàn cục phải được ưu
        # tiên (gọi như con trỏ hàm) — KHÔNG phân giải nhầm về hàm toàn cục. (Trước
        # đây 'name in self.funcs' được kiểm trước, nên 'fn f' toàn cục che mất một
        # tham số tên 'f' — vd 'fold(..., f)' trong std — gây lỗi số tham số sai.)
        if isinstance(e.func, A.Ident):
            nm = e.func.name
            binding = self.lookup(nm)
            if binding is not None and binding[0].kind not in ("func", "unknown"):
                self.err(
                    f"'{nm}' kiểu '{self.tyname(binding[0])}' không phải hàm "
                    f"để gọi", e)
        # ----- hàm thường -----
        ft = self.infer(e.func)
        arg_types = [self.infer(a) for a in e.args]
        if (isinstance(e.func, A.Ident) and e.func.name in self.funcs
                and self.lookup(e.func.name) is None):
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
            # Gọi qua một GIÁ TRỊ con trỏ hàm (biến/tham số/trường kiểu fn(...)->R).
            if len(e.args) != len(ft.params):
                self.err(
                    f"con trỏ hàm cần {len(ft.params)} tham số nhưng nhận "
                    f"{len(e.args)}", e)
            for i, (at, pt) in enumerate(zip(arg_types, ft.params)):
                if not self.assignable(pt, at):
                    self.err(
                        f"tham số {i + 1} (qua con trỏ hàm) cần "
                        f"'{self.tyname(pt)}' nhưng nhận '{self.tyname(at)}'", e)
            return ft.ret
        return T.UNKNOWN

    def _check_fmt_spec(self, key, at: T.GType, node):
        """Kiểm tra một specifier tường minh có khớp kiểu đối số không.
        '{}'/'{v}' tự suy luận nên luôn hợp lệ; bool dùng '{}' hoặc '{b}'.
        Bỏ phần ':flags' (width/precision) trước khi kiểm tra kiểu — nhưng nếu
        cờ kết thúc bằng một chữ kiểu kiểu-Rust ('{:08x}') thì chữ đó MỚI là kiểu."""
        base, sep, flags = key.partition(":")
        if (sep and base in ("", "v") and flags
                and flags[-1] in _FMT_TYPE_CHARS):
            base = flags[-1]
            flags = flags[:-1]
        # Khoá phải là một specifier đã biết: '{name}' (nội suy biến kiểu Rust)
        # hay '{0}' (chỉ số) KHÔNG được hỗ trợ — trước đây âm thầm in thập phân.
        if base not in _FMT_KEYS:
            hint = ""
            if base.isdigit():
                hint = " — G không hỗ trợ placeholder đánh số; dùng '{}' theo thứ tự"
            elif base.isidentifier():
                hint = (" — G không nội suy tên biến trong chuỗi; viết '{}' và "
                        f"truyền '{base}' làm đối số")
            self.err(f"placeholder '{{{key}}}' không hợp lệ: khoá '{base}' không "
                     f"phải specifier (hợp lệ: {{}}, {{d}}, {{x}}, {{f}}, {{s}}, "
                     f"{{c}}, {{b}}, {{p}}... hoặc '{{:cờ}}'){hint}", node)
        if sep and not _FMT_FLAGS_RE.fullmatch(flags):
            self.err(f"cờ định dạng ':{flags}' trong '{{{key}}}' không hợp lệ "
                     f"(dạng: [<|>|^][+| ][#][0][độ_rộng][.độ_chính_xác][chữ_kiểu], "
                     f"vd '{{:>8}}', '{{:08.3f}}', '{{:#x}}')", node)
        key = base
        if at.kind == "unknown":
            return
        if key in ("", "v"):
            return
        if key == "b":
            if not (at.kind in ("bool", "char", "enum") or at.is_integer()):
                self.err(
                    f"placeholder '{{b}}' cần bool (in true/false) hoặc số nguyên "
                    f"(in nhị phân) nhưng đối số kiểu '{self.tyname(at)}'", node)
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
        elif key == "p":
            if not (at.is_pointerish() or self._is_dyn_array(at)
                    or at.kind == "func"):
                self.err(
                    f"placeholder '{{p}}' (địa chỉ) cần con trỏ/chuỗi nhưng đối số "
                    f"kiểu '{self.tyname(at)}' — dùng '{{x}}' để in số ở dạng hex",
                    node)

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

    def _mentions_runtime_value(self, e) -> bool:
        """Biểu thức có tham chiếu tới biến cục bộ/global (không phải const) hoặc
        lời gọi hàm không? — những thứ C không coi là hằng trong _Static_assert."""
        if isinstance(e, A.Ident):
            if e.name in self.const_ints or e.name in self.enum_of_variant:
                return False
            return self.lookup(e.name) is not None
        if isinstance(e, A.Call):
            return True
        if isinstance(e, (A.SizeOf,)):
            return False
        if isinstance(e, A.SizeOfExpr):
            return False            # sizeof(biểu thức) không đánh giá biểu thức
        if isinstance(e, A.Unary):
            return self._mentions_runtime_value(e.operand)
        if isinstance(e, A.Binary):
            return (self._mentions_runtime_value(e.left)
                    or self._mentions_runtime_value(e.right))
        if isinstance(e, A.Ternary):
            return any(self._mentions_runtime_value(x) for x in (e.cond, e.then, e.els))
        if isinstance(e, A.Cast):
            return self._mentions_runtime_value(e.expr)
        return False
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
                if len(e.args) != 2:
                    self.err(f"g_alloc(T, n) cần đúng 2 tham số (kiểu và số lượng), "
                             f"nhận {len(e.args)} — cấp phát một phần tử: "
                             f"g_alloc(T, 1)", e)
                nt = self.infer(e.args[1])
                if not nt.is_integer() and nt.kind != "unknown":
                    self.err(f"g_alloc(T, n): số lượng phải là số nguyên, nhận "
                             f"'{self.tyname(nt)}'", e)
                return T.ptr_of(elem)
            self.err("g_alloc(T, n): cần tên kiểu và số lượng", e)
            return T.ptr_of(T.VOID)
        if name == "g_realloc":
            # g_realloc(p, T, n)
            if len(e.args) != 3:
                self.err(f"g_realloc(p, T, n) cần đúng 3 tham số, nhận {len(e.args)}", e)
            pt = self.infer(e.args[0]) if e.args else T.ptr_of(T.VOID)
            if len(e.args) > 1:
                elem = self._type_arg_to_gtype(e.args[1])
                if elem is None:
                    self.err("g_realloc(p, T, n): tham số thứ hai phải là tên kiểu", e)
                elif pt.kind == "ptr" and pt.elem is not None and pt.elem.kind != "unknown" \
                        and not self.assignable(pt.elem, elem) and not self.assignable(elem, pt.elem):
                    self.err(f"g_realloc: con trỏ kiểu '{self.tyname(pt)}' nhưng kiểu "
                             f"phần tử yêu cầu là '{self.tyname(elem)}'", e)
            if len(e.args) > 2:
                nt = self.infer(e.args[2])
                if not nt.is_integer() and nt.kind != "unknown":
                    self.err(f"g_realloc(p, T, n): số lượng phải là số nguyên, nhận "
                             f"'{self.tyname(nt)}'", e)
            return pt
        if name == "g_free":
            if len(e.args) != 1:
                self.err(f"g_free(p) cần đúng 1 tham số, nhận {len(e.args)}", e)
            for a in e.args:
                at = self.infer(a)
                if self._is_static_array(at):
                    self.err("g_free(p): không thể giải phóng mảng tĩnh (không cấp phát "
                             "bằng g_alloc)", e)
                elif at.kind not in ("ptr", "null", "unknown", "str") and not self._is_dyn_array(at):
                    self.err(f"g_free(p): cần con trỏ, nhận '{self.tyname(at)}'", e)
            return T.VOID
        if name in ("min", "max"):
            if len(e.args) != 2:
                self.err(f"{name}(a, b) cần đúng 2 tham số", e)
            a = self.infer(e.args[0]) if e.args else T.INT
            b = self.infer(e.args[1]) if len(e.args) > 1 else T.INT
            self._require_numeric_args(name, [a, b], e)
            return T.common_numeric(a, b) if a.is_numeric() and b.is_numeric() else a
        if name == "clamp":
            if len(e.args) != 3:
                self.err("clamp(x, lo, hi) cần đúng 3 tham số", e)
            ts = [self.infer(a) for a in e.args]
            self._require_numeric_args(name, ts, e)
            # clamp(x, lo, hi) với lo > hi (hằng): kết quả vô nghĩa.
            if len(ts) == 3:
                lo = self._fold_const_int(e.args[1])
                hi = self._fold_const_int(e.args[2])
                if lo is not None and hi is not None and lo > hi:
                    self.err(f"clamp(x, lo, hi): lo = {lo} lớn hơn hi = {hi} — "
                             f"thứ tự tham số là clamp(x, lo, hi)", e)
            return ts[0] if ts else T.INT
        if name == "abs":
            if len(e.args) != 1:
                self.err("abs(x) cần đúng 1 tham số", e)
            at = self.infer(e.args[0]) if e.args else T.INT
            self._require_numeric_args(name, [at], e)
            if at.kind == "int" and not at.signed:
                self.err(f"abs() trên số KHÔNG DẤU '{self.tyname(at)}' là vô nghĩa "
                         f"(luôn trả chính nó)", e)
            return at
        if name in ("panic", "unreachable", "todo"):
            # panic(msg) bắt buộc 1 chuỗi; unreachable()/todo() nhận 0-1 chuỗi.
            if name == "panic" and len(e.args) != 1:
                self.err("panic(msg) cần đúng 1 tham số là chuỗi thông điệp", e)
            if name != "panic" and len(e.args) > 1:
                self.err(f"{name}([msg]) nhận tối đa 1 tham số", e)
            for a in e.args:
                at = self.infer(a)
                if at.kind not in ("str", "unknown") and not (
                        at.kind == "ptr" and at.elem is not None and at.elem.kind == "char"):
                    self.err(f"{name}: thông điệp phải là chuỗi (str), nhận "
                             f"'{self.tyname(at)}' — dùng format(...) để ghép giá trị", a)
            return T.VOID
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
        if name == "typeof":
            # typeof(expr): trả về CHUỖI tên kiểu suy luận (hằng lúc biên dịch).
            if len(e.args) != 1:
                self.err("typeof(x) cần đúng 1 tham số", e)
            if e.args:
                self.infer(e.args[0])
            return T.STR
        if name == "dbg":
            # dbg(x): in '[dbg dòng N] <giá trị>' ra stderr (kiểu Rust) rồi TRẢ LẠI
            # chính x — đặt xen vào biểu thức để soi giá trị mà không đổi luồng:
            # 'let y = dbg(a + b)'. Đánh giá x đúng một lần.
            if len(e.args) != 1:
                self.err("dbg(x) cần đúng 1 tham số", e)
                return T.UNKNOWN
            at = self.infer(e.args[0])
            if at.kind == "void" or self._is_static_array(at):
                self.err(
                    f"dbg() chưa in trực tiếp được giá trị kiểu '{self.tyname(at)}' "
                    f"(in từng phần tử, hoặc dùng '&x' để in địa chỉ)", e)
            return at
        if name == "swap":
            # swap(a, b): tráo hai ô nhớ cùng kiểu (đánh giá địa chỉ đúng MỘT lần).
            if len(e.args) != 2:
                self.err("swap(a, b) cần đúng 2 tham số", e)
            ta = self.infer(e.args[0]) if e.args else T.UNKNOWN
            tb = self.infer(e.args[1]) if len(e.args) > 1 else T.UNKNOWN
            for a in e.args:
                self._check_lvalue_mutable(a, e)   # phải là ô nhớ khả biến
            if not (self.assignable(ta, tb) and self.assignable(tb, ta)):
                self.err(
                    f"swap: hai đối số phải cùng kiểu, nhận '{self.tyname(ta)}' và "
                    f"'{self.tyname(tb)}'", e)
            return T.VOID
        if name in ("print", "println", "eprint", "eprintln", "format"):
            arg_ts = [self.infer(a) for a in e.args]
            # 'format' BẮT BUỘC có chuỗi định dạng literal đầu tiên (vì luôn dựng
            # chuỗi kết quả); print thì cho phép in trực tiếp một giá trị.
            if name == "format" and (not e.args
                                     or not isinstance(e.args[0], A.StrLit)):
                self.err("format(\"...\", ...): tham số đầu phải là chuỗi định dạng "
                         "literal", e)
            # print(x) (một giá trị, không chuỗi định dạng) là lối tắt hợp lệ;
            # nhưng print(x, y, ...) KHÔNG có chuỗi định dạng thì mơ hồ — các đối
            # số thừa sẽ bị bỏ âm thầm. Yêu cầu chuỗi định dạng tường minh.
            if (name != "format" and len(e.args) > 1
                    and not isinstance(e.args[0], A.StrLit)):
                self.err(
                    f"{name}(...) với nhiều đối số cần một chuỗi định dạng literal "
                    f"làm tham số đầu (vd '{name}(\"{{}} {{}}\", a, b)') — nếu không, "
                    f"các đối số sau đối số đầu sẽ bị bỏ qua", e)
            value_ts = arg_ts[1:] if (e.args and isinstance(e.args[0], A.StrLit)) else arg_ts
            # struct giờ ĐƯỢC in trực tiếp: codegen tự bung 'Tên { trường: gtrị,
            # ... }'. Chỉ void và mảng-tĩnh-theo-giá-trị là không in được ('{}' với
            # mảng thiếu thông tin độ dài tin cậy; in từng phần tử).
            for at in value_ts:
                if at.kind == "void" or self._is_static_array(at):
                    self.err(
                        f"không thể định dạng trực tiếp giá trị kiểu "
                        f"'{self.tyname(at)}' (dùng từng trường/phần tử)", e)
            if e.args and isinstance(e.args[0], A.StrLit):
                bad = []
                keys = extract_placeholders(e.args[0].value, bad)
                for msg in dict.fromkeys(bad):
                    self.err(f"chuỗi định dạng không hợp lệ: {msg}", e)
                want = len(keys)
                got = len(e.args) - 1
                if want != got:
                    self.err(
                        f"chuỗi định dạng có {want} placeholder nhưng nhận {got} đối số",
                        e)
                # Khớp specifier tường minh với kiểu đối số (bắt UB của printf).
                for key, at in zip(keys, value_ts):
                    self._check_fmt_spec(key, at, e)
            return T.STR if name == "format" else T.VOID
        if name == "assert":
            if not e.args or len(e.args) > 2:
                self.err("assert(cond[, msg]) cần 1 hoặc 2 tham số", e)
            if e.args:
                self._check_cond(e.args[0], "assert")
            if len(e.args) > 1:
                mt = self.infer(e.args[1])
                if mt.kind not in ("str", "unknown"):
                    self.err(f"assert(cond, msg): thông điệp phải là chuỗi, nhận "
                             f"'{self.tyname(mt)}'", e.args[1])
            for a in e.args[2:]:
                self.infer(a)
            return T.VOID
        if name in self._CMP_BUILTINS:
            # So sánh BẰNG/KHÁC/THỨ TỰ generic, hiển thị 'trái'/'phải'. assert_*
            # dừng khi sai; check_* ghi nhận pass/fail rồi tiếp tục (trả bool). Tham
            # số thứ ba tuỳ chọn: assert_* coi là thông điệp, check_* coi là TÊN ca test.
            ordered = name.rsplit("_", 1)[1] in ("lt", "le", "gt", "ge")
            if len(e.args) < 2:
                self.err(f"{name}(trái, phải[, "
                         f"{'tên' if name.startswith('check') else 'msg'}]) cần ít "
                         f"nhất 2 tham số", e)
                return T.BOOL if name.startswith("check") else T.VOID
            ta = self.infer(e.args[0])
            tb = self.infer(e.args[1])
            if len(e.args) > 2:
                self.infer(e.args[2])
            for t in (ta, tb):
                if t.kind == "void" or self._is_static_array(t):
                    self.err(
                        f"{name}: không so sánh/in được giá trị kiểu "
                        f"'{self.tyname(t)}' (mảng tĩnh: so từng phần tử thủ công)", e)
            # So sánh THỨ TỰ chỉ áp cho số/char/enum/chuỗi (không struct — không có
            # thứ tự tự nhiên theo trường). So sánh BẰNG còn cho phép struct cùng loại.
            ok = self._comparable(ta, tb) if ordered else self._eq_comparable(ta, tb)
            if not ok:
                extra = (" — so sánh thứ tự cần số/char/enum/chuỗi"
                         if ordered and (ta.kind == "struct" or tb.kind == "struct")
                         else "")
                self.err(
                    f"{name}: hai vế phải cùng kiểu để so sánh, nhận "
                    f"'{self.tyname(ta)}' và '{self.tyname(tb)}'{extra}", e)
            return T.BOOL if name.startswith("check") else T.VOID
        if name == "test_summary":
            if e.args:
                self.err("test_summary() không nhận tham số", e)
            return T.INT
        # ===== intrinsics phát triển hệ điều hành =====
        if name in _OS_NULLARY_VOID:
            if e.args:
                self.err(f"{name}() không nhận tham số", e)
            return T.VOID
        if name == "rdtsc":
            if e.args:
                self.err("rdtsc() không nhận tham số", e)
            return T.U64
        # ----- thanh ghi điều khiển / TLB / MSR (đặc quyền, ring 0) -----
        if name in _OS_CR_READ:
            if e.args:
                self.err(f"{name}() không nhận tham số", e)
            return T.U64
        if name in _OS_CR_WRITE:
            if len(e.args) != 1:
                self.err(f"{name}(giá_trị) cần đúng 1 tham số", e)
            if e.args:
                vt = self.infer(e.args[0])
                if not vt.is_integer() and vt.kind != "unknown":
                    self.err(f"{name}: giá trị phải là số nguyên, nhận "
                             f"'{self.tyname(vt)}'", e)
            return T.VOID
        if name == "invlpg":
            # invlpg(địa_chỉ): vô hiệu một mục TLB cho trang chứa địa chỉ. Nhận
            # con trỏ '*T' hoặc địa chỉ nguyên (usize).
            if len(e.args) != 1:
                self.err("invlpg(địa_chỉ) cần đúng 1 tham số", e)
            if e.args:
                at = self.infer(e.args[0])
                if not (at.kind in ("ptr", "unknown") or at.is_integer()):
                    self.err("invlpg: cần con trỏ hoặc địa chỉ nguyên, nhận "
                             f"'{self.tyname(at)}'", e)
            return T.VOID
        if name == "rdmsr":
            # rdmsr(msr): đọc Model-Specific Register -> u64 (edx:eax).
            if len(e.args) != 1:
                self.err("rdmsr(msr) cần đúng 1 tham số", e)
            if e.args:
                mt = self.infer(e.args[0])
                if not mt.is_integer() and mt.kind != "unknown":
                    self.err(f"rdmsr: số hiệu MSR phải là số nguyên, nhận "
                             f"'{self.tyname(mt)}'", e)
            return T.U64
        if name == "wrmsr":
            # wrmsr(msr, giá_trị): ghi Model-Specific Register (giá trị u64).
            if len(e.args) != 2:
                self.err("wrmsr(msr, giá_trị) cần đúng 2 tham số", e)
            for a in e.args:
                at = self.infer(a)
                if not at.is_integer() and at.kind != "unknown":
                    self.err(f"wrmsr: tham số phải là số nguyên, nhận "
                             f"'{self.tyname(at)}'", e)
            return T.VOID
        if name in ("memcpy", "memmove", "memset", "memcmp"):
            if len(e.args) != 3:
                self.err(f"{name}(dst, {'src' if name != 'memset' else 'byte'}, n) "
                         f"cần đúng 3 tham số", e)
            ts = [self.infer(a) for a in e.args]
            if e.args:
                dt = ts[0]
                if not (self._ptrlike(dt) or dt.kind in ("array", "unknown")):
                    self.err(f"{name}: tham số đầu phải là con trỏ/mảng, nhận "
                             f"'{self.tyname(dt)}'", e)
            return T.INT if name == "memcmp" else (ts[0] if ts else T.ptr_of(T.VOID))
        if name == "vol_read":
            if len(e.args) != 1:
                self.err("vol_read(ptr) cần đúng 1 tham số", e)
                return T.UNKNOWN
            pt = self.infer(e.args[0])
            if pt.kind == "ptr":
                return pt.elem
            if pt.kind == "unknown":
                return T.UNKNOWN
            self.err(f"vol_read cần một con trỏ '*T', nhận '{self.tyname(pt)}'", e)
        if name == "vol_write":
            if len(e.args) != 2:
                self.err("vol_write(ptr, val) cần đúng 2 tham số", e)
                return T.VOID
            pt = self.infer(e.args[0])
            vt = self.infer(e.args[1])
            if pt.kind == "ptr":
                if not self.assignable(pt.elem, vt):
                    self.err(
                        f"vol_write: giá trị kiểu '{self.tyname(vt)}' không gán được "
                        f"cho ô '{self.tyname(pt.elem)}'", e)
            elif pt.kind != "unknown":
                self.err(f"vol_write cần một con trỏ '*T', nhận '{self.tyname(pt)}'", e)
            return T.VOID
        if name in _OS_BIT_TO_INT:
            if len(e.args) != 1:
                self.err(f"{name}(x) cần đúng 1 tham số", e)
            if e.args:
                xt = self.infer(e.args[0])
                if not xt.is_integer() and xt.kind != "unknown":
                    self.err(f"{name}(x) cần số nguyên, nhận '{self.tyname(xt)}'", e)
            return T.INT
        if name in _OS_BIT_SAME:
            nargs = 1 if name == "bswap" else 2
            if len(e.args) != nargs:
                self.err(f"{name}(...) cần đúng {nargs} tham số", e)
            xt = self.infer(e.args[0]) if e.args else T.U64
            for a in e.args[1:]:
                self.infer(a)
            if not xt.is_integer() and xt.kind != "unknown":
                self.err(f"{name}: cần số nguyên, nhận '{self.tyname(xt)}'", e)
            return xt if xt.kind != "unknown" else T.U64
        if name in ("inb", "inw", "inl"):
            if len(e.args) != 1:
                self.err(f"{name}(port) cần đúng 1 tham số", e)
            if e.args:
                self.infer(e.args[0])
            return {"inb": T.U8, "inw": T.U16, "inl": T.U32}[name]
        if name in _OS_PORT_OUT:
            if len(e.args) != 2:
                self.err(f"{name}(port, val) cần đúng 2 tham số", e)
            for a in e.args:
                self.infer(a)
            return T.VOID
        if name == "static_assert":
            if len(e.args) not in (1, 2) or (
                    len(e.args) == 2 and not isinstance(e.args[1], A.StrLit)):
                self.err('static_assert(điều_kiện[, "thông điệp"]): cần một điều kiện '
                         "hằng và (tuỳ chọn) một chuỗi literal", e)
                return T.VOID
            self.infer(e.args[0])
            cv = self._fold_const_int(e.args[0])
            if cv is None and self._mentions_runtime_value(e.args[0]):
                self.err("static_assert cần một điều kiện HẰNG lúc biên dịch (literal, "
                         "const, sizeof/alignof, biến thể enum và phép toán giữa chúng) "
                         "— biểu thức này tham chiếu biến/lời gọi lúc chạy", e)
            elif cv is not None and cv == 0:
                msg = e.args[1].value if len(e.args) == 2 else "điều kiện sai"
                self.err(f"static_assert thất bại lúc biên dịch: {msg}", e)
            # codegen: phát hằng đã gấp (C không coi 'const int' là hằng); None ->
            # phát biểu thức gốc (chỉ còn sizeof/alignof kiểu -> C tự gấp được).
            e.const_value = cv
            return T.VOID

        # printf/panic/g_free và khác
        for a in e.args:
            self.infer(a)
        return T.VOID
