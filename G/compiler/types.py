"""
G Language - Hệ thống kiểu (type system).
GType là biểu diễn kiểu đã được phân giải, dùng cho type-checker và codegen.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GType:
    kind: str            # void bool int float char str ptr array struct enum func null unknown
    name: str = ""       # tên int (i32...) / struct / enum
    bits: int = 0
    signed: bool = True
    elem: object = None  # ptr/array: kiểu phần tử
    n: object = None     # array: số phần tử (int hoặc 'dyn')
    params: tuple = ()   # func
    ret: object = None   # func

    # ---------- thuộc tính ----------
    def is_numeric(self):
        return self.kind in ("int", "float", "char")

    def is_integer(self):
        return self.kind in ("int", "char")

    def is_pointerish(self):
        return self.kind in ("ptr", "str", "null")

    def __str__(self):
        if self.kind == "ptr":
            return "*" + str(self.elem)
        if self.kind == "array":
            sz = "" if self.n == "dyn" else str(self.n)
            return f"[{sz}]{self.elem}"
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
USIZE = GType("int", "usize", 64, False)
ISIZE = GType("int", "isize", 64, True)
F32 = GType("float", "f32", 32)
F64 = GType("float", "f64", 64)

PRIMITIVES = {
    "void": VOID, "bool": BOOL, "char": CHAR, "str": STR,
    "i8": I8, "i16": I16, "i32": I32, "i64": I64,
    "u8": U8, "u16": U16, "u32": U32, "u64": U64,
    "int": INT, "usize": USIZE, "isize": ISIZE,
    "f32": F32, "f64": F64, "float": F32, "double": F64,
}


def ptr_of(elem):
    return GType("ptr", elem=elem)


def array_of(elem, n):
    return GType("array", elem=elem, n=n)


# ---------- ánh xạ sang C ----------
_C_NAME = {
    "void": "void", "bool": "bool", "char": "char", "str": "const char*",
    "i8": "int8_t", "i16": "int16_t", "i32": "int32_t", "i64": "int64_t",
    "u8": "uint8_t", "u16": "uint16_t", "u32": "uint32_t", "u64": "uint64_t",
    "int": "int", "usize": "size_t", "isize": "ptrdiff_t",
    "f32": "float", "f64": "double",
}


def c_type(t: GType) -> str:
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
