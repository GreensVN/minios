"""
G Language - Định nghĩa các nút AST (Abstract Syntax Tree).
Các nút biểu thức sẽ được gắn thuộc tính `.gtype` (kiểu suy luận) trong giai đoạn check.
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------- Kiểu cú pháp (type annotation) ----------
@dataclass
class Type:
    name: str                      # int, f64, str, void, tên struct/enum...
    ptr: int = 0                   # số mức con trỏ (*)
    array: Optional[object] = None # nếu là mảng: số phần tử (int) hoặc None cho [ ]T
    line: int = 0
    col: int = 0


# ---------- Chương trình & khai báo cấp cao ----------
@dataclass
class Program:
    items: list = field(default_factory=list)
    imports: list = field(default_factory=list)


@dataclass
class Param:
    name: str
    type: Type


@dataclass
class Function:
    name: str
    params: list
    ret: Type
    body: list
    is_comptime: bool = False
    is_extern: bool = False
    recv: Optional[str] = None     # tên struct nếu là method (impl)
    line: int = 0
    col: int = 0


@dataclass
class StructDef:
    name: str
    fields: list        # list[Param]
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


@dataclass
class GlobalVar:
    name: str
    type: Optional[Type]
    value: object
    mutable: bool
    is_const: bool
    line: int = 0
    col: int = 0


# ---------- Câu lệnh ----------
@dataclass
class Let:
    name: str
    type: Optional[Type]
    value: object
    mutable: bool
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
    line: int = 0
    col: int = 0


@dataclass
class ForEach:             # for x in iterable { }   (mảng tĩnh hoặc str)
    var: str
    iterable: object
    body: list
    line: int = 0
    col: int = 0


@dataclass
class Match:
    subject: object
    arms: list              # list[(patterns_list | None, body_list)]
    line: int = 0
    col: int = 0


@dataclass
class Defer:
    stmt: object


@dataclass
class Asm:
    code: str
    volatile: bool = True


@dataclass
class Break:
    pass


@dataclass
class Continue:
    pass


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


@dataclass
class Ident:
    name: str
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


@dataclass
class StructLit:
    name: str
    fields: list            # list[(field_name, expr)]
    line: int = 0
    col: int = 0
