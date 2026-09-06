"""
G Language - Hệ thống kiểu (type system).
GType là biểu diễn kiểu đã được phân giải, dùng cho type-checker và codegen.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class GType:
    kind: str            # void bool int float char str ptr array slice struct enum func null unknown
    name: str = ""       # tên int (i32...) / struct / enum
    bits: int = 0
    signed: bool = True
    elem: object = None  # ptr/array: kiểu phần tử
    n: object = None     # array: số phần tử (int hoặc 'dyn')
    params: tuple = ()   # func
    ret: object = None   # func
    mutable_slice: bool = False   # slice: cho phép GHI qua nó?

    # ---------- thuộc tính ----------
    def is_numeric(self):
        return self.kind in ("int", "float", "char")

    def is_integer(self):
        return self.kind in ("int", "char")

    def is_pointerish(self):
        return self.kind in ("ptr", "str", "null")

    def is_slice(self):
        return self.kind == "slice"

    def __str__(self):
        if self.kind == "ptr":
            return "*" + str(self.elem)
        if self.kind == "array":
            sz = "" if self.n == "dyn" else str(self.n)
            return f"[{sz}]{self.elem}"
        if self.kind == "slice":
            return f"slice<{self.elem}>" if not self.mutable_slice \
                else f"mut slice<{self.elem}>"
        if self.kind in ("struct", "enum"):
            return self.name
        if self.kind in ("int", "float") and self.name:
            return self.name
        if self.kind == "func":
            ps = ", ".join(str(p) for p in self.params)
            r = str(self.ret) if self.ret is not None else "void"
            return f"fn({ps}) -> {r}"
        return self.kind


# ---------- kiểu nguyên thủy ----------
VOID = GType("void")
BOOL = GType("bool")
CHAR = GType("char", "char", 8, True)
STR = GType("str")
NULL = GType("null")
UNKNOWN = GType("unknown")

I8 = GType("int", "i8", 8, True)
I16 = GType("int", "i16", 16, True)
I32 = GType("int", "i32", 32, True)
I64 = GType("int", "i64", 64, True)
U8 = GType("int", "u8", 8, False)
U16 = GType("int", "u16", 16, False)
U32 = GType("int", "u32", 32, False)
U64 = GType("int", "u64", 64, False)
INT = GType("int", "int", 32, True)
# 'usize'/'isize' theo BỀ RỘNG CON TRỎ của target. Giá trị dưới đây là mặc định
# 64-bit; trên target 32-bit (vd wasm32) chúng được thay bằng bản 32-bit qua
# 'sized_primitives(ptr_bits)'. KHÔNG hardcode 64 ở nơi khác — dùng bảng đó.
USIZE = GType("int", "usize", 64, False)
ISIZE = GType("int", "isize", 64, True)
USIZE32 = GType("int", "usize", 32, False)
ISIZE32 = GType("int", "isize", 32, True)
F32 = GType("float", "f32", 32)
F64 = GType("float", "f64", 64)

PRIMITIVES = {
    "void": VOID, "bool": BOOL, "char": CHAR, "str": STR,
    "i8": I8, "i16": I16, "i32": I32, "i64": I64,
    "u8": U8, "u16": U16, "u32": U32, "u64": U64,
    "int": INT, "usize": USIZE, "isize": ISIZE,
    "f32": F32, "f64": F64, "float": F32, "double": F64,
}


def sized_primitives(ptr_bits: int) -> dict:
    """Bảng kiểu nguyên thuỷ cho một bề rộng con trỏ cụ thể.

    Chỉ 'usize'/'isize' phụ thuộc target; các kiểu bề rộng CỐ ĐỊNH (i32, u64...)
    giống nhau ở mọi nơi — đó là lý do chúng tồn tại."""
    if ptr_bits >= 64:
        return PRIMITIVES
    tbl = dict(PRIMITIVES)
    tbl["usize"] = USIZE32
    tbl["isize"] = ISIZE32
    return tbl


def int_bounds(ptr_bits: int) -> dict:
    """Biên giá trị hợp lệ của từng kiểu nguyên, theo bề rộng con trỏ."""
    b = {
        "i8": (-(1 << 7), (1 << 7) - 1),
        "i16": (-(1 << 15), (1 << 15) - 1),
        "i32": (-(1 << 31), (1 << 31) - 1),
        "int": (-(1 << 31), (1 << 31) - 1),
        "i64": (-(1 << 63), (1 << 63) - 1),
        "u8": (0, (1 << 8) - 1),
        "u16": (0, (1 << 16) - 1),
        "u32": (0, (1 << 32) - 1),
        "u64": (0, (1 << 64) - 1),
    }
    n = ptr_bits if ptr_bits in (32, 64) else 64
    b["isize"] = (-(1 << (n - 1)), (1 << (n - 1)) - 1)
    b["usize"] = (0, (1 << n) - 1)
    return b


def ptr_of(elem):
    return GType("ptr", elem=elem)


def array_of(elem, n):
    return GType("array", elem=elem, n=n)


def slice_of(elem, mutable=False):
    """slice<T> — con trỏ BÉO: (ptr, len). Khác '[]T' (con trỏ trần, mất độ dài)."""
    return GType("slice", elem=elem, mutable_slice=mutable)


# ---------- ánh xạ sang C ----------
_C_NAME = {
    "void": "void", "bool": "bool", "char": "char", "str": "const char*",
    "i8": "int8_t", "i16": "int16_t", "i32": "int32_t", "i64": "int64_t",
    "u8": "uint8_t", "u16": "uint16_t", "u32": "uint32_t", "u64": "uint64_t",
    "int": "int", "usize": "size_t", "isize": "ptrdiff_t",
    "f32": "float", "f64": "double",
}


def slice_c_name(elem: GType) -> str:
    """Tên struct C cho slice<T> — MỘT nguồn chân lý cho cả hai backend.

    Trước đây codegen và backend c-ir mỗi bên tự ghép tên với thứ tự thay thế
    khác nhau, nên 'slice<str>' ra 'GSlice_str' ở chỗ này và
    'GSlice_const_charp' ở chỗ kia — typedef không khớp lúc dùng."""
    base = c_type(elem)
    if base == "const char*":
        return "GSlice_str"
    ident = base.replace("*", "p").replace(" ", "_")
    return f"GSlice_{ident}"


def c_type(t: GType) -> str:
    if t.kind == "slice":
        return slice_c_name(t.elem)
    if t.kind == "ptr":
        return c_type(t.elem) + "*"
    if t.kind == "array":
        return c_type(t.elem) + "*"   # mảng động truyền như con trỏ
    if t.kind in ("struct", "enum"):
        return t.name
    if t.kind == "null":
        return "void*"
    if t.kind == "func":
        return "void*"     # con trỏ hàm dùng làm giá trị cỡ con trỏ (fallback)
    if t.kind == "unknown":
        return "int"
    if t.kind == "int":
        return _C_NAME.get(t.name, "int")
    if t.kind == "float":
        return _C_NAME.get(t.name, "double")
    return _C_NAME.get(t.kind, "int")


# ---------- chỉ thị printf theo kiểu ----------
def printf_spec(t: GType):
    """Trả về (specifier, is_bool). is_bool=True nghĩa là cần in true/false."""
    if t.kind == "bool":
        return "%s", True
    if t.kind == "char":
        return "%c", False
    if t.kind == "str":
        return "%s", False
    if t.kind == "float":
        return "%g", False
    if t.kind == "int":
        if not t.signed:
            return ("%llu", False) if t.bits >= 64 else ("%u", False)
        return ("%lld", False) if t.bits >= 64 else ("%d", False)
    if t.kind in ("ptr", "null"):
        # con trỏ tới char -> chuỗi
        if t.elem is not None and t.elem.kind == "char":
            return "%s", False
        return "%p", False
    if t.kind == "func":          # con trỏ hàm
        return "%p", False
    if t.kind == "enum":
        return "%d", False
    return "%d", False


def common_numeric(a: GType, b: GType) -> GType:
    """Kiểu kết quả của phép toán số học giữa a và b."""
    if a.kind == "float" or b.kind == "float":
        if a.kind == "float" and b.kind == "float":
            return a if a.bits >= b.bits else b
        return a if a.kind == "float" else b
    # cả hai nguyên: lấy bit lớn hơn
    if a.kind == "int" and b.kind == "int":
        return a if a.bits >= b.bits else b
    return a if a.kind == "int" else b
