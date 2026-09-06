"""
G Language - Định nghĩa các nút AST (Abstract Syntax Tree).
Các nút biểu thức sẽ được gắn thuộc tính `.gtype` (kiểu suy luận) trong giai đoạn check.
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------- Kiểu cú pháp (type annotation) ----------
@dataclass
class Type:
    name: str
    #: Đối số kiểu của một kiểu generic ('Pair<int, str>'). Rỗng = không generic.
    type_args: Optional[list] = None                      # int, f64, str, void, tên struct/enum...; "fn" nếu là kiểu hàm
    ptr: int = 0                   # số mức con trỏ NGOÀI (*[N]T: con trỏ tới mảng)
    array: Optional[object] = None # mảng 1 chiều: số phần tử (int/biểu thức hằng) / "dyn" cho []T
    dims: Optional[list] = None    # mảng nhiều chiều: [d0, d1, ...] (mỗi d là int/biểu thức/"dyn")
    elem_ptr: int = 0              # con trỏ trên PHẦN TỬ ([N]*T: mảng các con trỏ)
    resolved: Optional[object] = None    # GType do checker phân giải (irgen dùng lại)
    slice_elem: Optional[object] = None  # slice<T>: kiểu phần tử T
    slice_mut: bool = False        # 'mut slice<T>': cho phép ghi qua slice
    is_fn: bool = False            # True nếu là kiểu con trỏ hàm: fn(P...) -> R
    fn_params: Optional[list] = None  # list[Type] tham số của kiểu hàm
    fn_ret: Optional[object] = None   # Type trả về của kiểu hàm (None = void)
    line: int = 0
    col: int = 0


# ---------- Chương trình & khai báo cấp cao ----------
@dataclass
class Program:
    items: list = field(default_factory=list)
    imports: list = field(default_factory=list)


@dataclass
class Attr:                     # @name | @name(arg, ...)  — thuộc tính C/ABI
    name: str
    args: list = field(default_factory=list)   # list[expr]
    line: int = 0
    col: int = 0


@dataclass
class Param:
    name: str
    type: Type
    mutable: bool = False


@dataclass
class Function:
    name: str
    params: list
    ret: Type
    body: list
    #: Tham số KIỂU của hàm generic: ['T', 'U']. Rỗng = hàm thường.
    type_params: list = field(default_factory=list)
    #: Ràng buộc trait cho từng tham số kiểu: {'T': ['Ord', 'Show']}.
    type_bounds: dict = field(default_factory=dict)
    is_comptime: bool = False
    is_extern: bool = False
    recv: Optional[str] = None     # tên struct nếu là method (impl)
    attrs: list = field(default_factory=list)   # list[Attr]
    line: int = 0
    col: int = 0


@dataclass
class StructDef:
    name: str
    fields: list        # list[Param]
    attrs: list = field(default_factory=list)   # list[Attr]
    line: int = 0
    col: int = 0


@dataclass
class EnumDef:
    name: str
    variants: list      # list[(tên, giá_trị_hoặc_None)]
    line: int = 0
    col: int = 0


@dataclass
class Impl:
    struct: str
    methods: list       # list[Function]
    line: int = 0
    col: int = 0
    #: 'impl Trait for Struct' -> tên trait; None = impl thường.
    trait: Optional[str] = None


@dataclass
class TraitDef:
    """'trait Eq { fn eq(self, o: Self) -> bool }'

    Trait của G là RÀNG BUỘC LÚC BIÊN DỊCH cho generic, không phải đối tượng
    động: không có vtable, không boxing. Xem docs/TRAITS.md."""
    name: str
    methods: list = field(default_factory=list)   # list[Function] (không thân)
    line: int = 0
    col: int = 0


@dataclass
class GlobalVar:
    name: str
    type: Optional[Type]
    value: object
    mutable: bool
    is_const: bool
    is_extern: bool = False     # 'extern let/const': ký hiệu định nghĩa nơi khác
                                # (assembly/linker script) — chỉ khai báo, không cấp
    attrs: list = field(default_factory=list)   # list[Attr]
    line: int = 0
    col: int = 0


# ---------- Câu lệnh ----------
@dataclass
class Let:
    name: str
    type: Optional[Type]
    value: object
    mutable: bool
    c_name: str = ""        # tên C duy nhất (do checker cấp, hỗ trợ shadowing)
    is_const: bool = False  # khai báo bằng 'const' (hằng biên dịch, dùng làm cỡ mảng)
    line: int = 0
    col: int = 0


@dataclass
class Return:
    value: object
    line: int = 0
    col: int = 0


@dataclass
class If:
    cond: object
    then: list
    els: Optional[list]
    line: int = 0
    col: int = 0


@dataclass
class While:
    cond: object
    body: list
    line: int = 0
    col: int = 0


@dataclass
class Loop:                 # vòng lặp vô hạn (Rust)
    body: list
    line: int = 0
    col: int = 0


@dataclass
class For:                  # for i in a..b { } | a..=b | step N
    var: str
    start: object
    end: object
    body: list
    inclusive: bool = False
    step: object = None
    c_name: str = ""
    line: int = 0
    col: int = 0


@dataclass
class ForEach:             # for x in iterable { }   (mảng tĩnh hoặc str)
    var: str
    iterable: object
    body: list
    mutable: bool = False  # for mut x in ... : cho phép sửa biến lặp
    c_name: str = ""
    line: int = 0
    col: int = 0


@dataclass
class Match:
    subject: object
    arms: list              # list[(patterns_list | None, body_list)]
    line: int = 0
    col: int = 0


@dataclass
class RangePat:            # pattern khoảng trong match: lo..hi | lo..=hi
    lo: object
    hi: object
    inclusive: bool = False
    line: int = 0
    col: int = 0


@dataclass
class Defer:
    stmt: object


@dataclass
class Asm:
    code: str
    outputs: list = field(default_factory=list)   # list[(constraint:str, expr)]
    inputs: list = field(default_factory=list)     # list[(constraint:str, expr)]
    clobbers: list = field(default_factory=list)   # list[str]
    volatile: bool = True
    extended: bool = False     # True nếu có toán hạng (asm mở rộng kiểu GCC)
    line: int = 0
    col: int = 0


@dataclass
class Block:                # khối lệnh trần { ... } (tạo scope mới)
    body: list
    line: int = 0
    col: int = 0


@dataclass
class Break:
    line: int = 0
    col: int = 0


@dataclass
class Continue:
    line: int = 0
    col: int = 0


@dataclass
class ExprStmt:
    expr: object


@dataclass
class Assign:
    target: object
    op: str
    value: object
    line: int = 0
    col: int = 0


# ---------- Biểu thức ----------
@dataclass
class IntLit:
    value: str
    line: int = 0
    col: int = 0


@dataclass
class FloatLit:
    value: str
    line: int = 0
    col: int = 0


@dataclass
class StrLit:
    value: str
    line: int = 0
    col: int = 0


@dataclass
class CharLit:
    value: str
    line: int = 0
    col: int = 0


@dataclass
class BoolLit:
    value: bool
    line: int = 0
    col: int = 0


@dataclass
class NullLit:
    line: int = 0
    col: int = 0


@dataclass
class ArrayLit:
    elements: list
    line: int = 0
    col: int = 0
    repeat: object = None   # '[v; N]': biểu thức đếm N (hằng) — elements = [v]


@dataclass
class Ident:
    name: str
    c_name: str = ""        # tên C đã phân giải (hỗ trợ shadowing); rỗng = dùng name
    line: int = 0
    col: int = 0


@dataclass
class Binary:
    op: str
    left: object
    right: object
    line: int = 0
    col: int = 0


@dataclass
class Unary:
    op: str
    operand: object
    line: int = 0
    col: int = 0


@dataclass
class Ternary:
    cond: object
    then: object
    els: object
    line: int = 0
    col: int = 0


@dataclass
class Call:
    func: object
    args: list
    line: int = 0
    col: int = 0
    #: Đối số kiểu tường minh tại nơi gọi: 'f<int>(x)'. None = tự suy.
    type_args: Optional[list] = None


@dataclass
class MethodCall:           # sinh ra trong giai đoạn check: recv.method(args)
    receiver: object
    method: str
    args: list
    struct: str = ""
    line: int = 0
    col: int = 0


@dataclass
class Index:
    base: object
    index: object
    line: int = 0
    col: int = 0


@dataclass
class FieldAccess:
    base: object
    field: str
    line: int = 0
    col: int = 0


@dataclass
class Cast:
    expr: object
    type: Type
    line: int = 0
    col: int = 0


@dataclass
class SizeOf:
    type: Type
    line: int = 0
    col: int = 0
    align: bool = False     # True nếu là 'alignof' (sinh _Alignof thay vì sizeof)


@dataclass
class SizeOfExpr:          # sizeof(biểu_thức) — lấy kích thước theo kiểu suy luận
    expr: object
    line: int = 0
    col: int = 0


@dataclass
class StructLit:
    name: str
    fields: list            # list[(field_name, expr)]
    line: int = 0
    col: int = 0

@dataclass
class IfExpr:              # 'if c { a } else { b }' ở vị trí BIỂU THỨC
    cond: object
    then: object           # biểu thức giá trị của nhánh then
    els: object            # biểu thức giá trị của nhánh else (bắt buộc)
    line: int = 0
    col: int = 0


@dataclass
class MatchExpr:           # 'match x { p => v, ... }' ở vị trí BIỂU THỨC
    subject: object
    arms: list             # list[(patterns_list | None, guard | None, value_expr)]
    line: int = 0
    col: int = 0


@dataclass
class Multi:
    """Nhiều câu lệnh sinh ra từ MỘT câu lệnh nguồn (vd destructuring), phẳng
    vào block cha — KHÔNG tạo scope mới như A.Block."""
    stmts: list
    line: int = 0
    col: int = 0


@dataclass
class Slice:
    """'s[lo..hi]' / 's[lo..=hi]' — lát cắt CHUỖI. lo/hi có thể None (khuyết)."""
    base: object
    lo: object
    hi: object
    inclusive: bool = False
    line: int = 0
    col: int = 0
