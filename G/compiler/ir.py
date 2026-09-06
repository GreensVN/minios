"""
G-IR — biểu diễn trung gian của trình biên dịch G.

VÌ SAO CẦN IR
=============
Trước đây checker "nói chuyện" với codegen bằng cách gắn ~37 thuộc tính động lên
node AST (`e.gtype`, `e.by_ref_elem`, `e.arr_copy_from`, ...) và codegen đọc lại
bằng `getattr`. Hợp đồng đó không được kiểm tra ở đâu cả: một backend thứ hai
quên đọc một thuộc tính sẽ sinh mã SAI ÂM THẦM (vì `getattr` có giá trị mặc
định). G-IR biến hợp đồng ngầm đó thành DỮ LIỆU TƯỜNG MINH mà verifier soi được.

HÌNH DẠNG
=========
Three-address code trên đồ thị luồng điều khiển (CFG) gồm các basic block:

    Module
      └── Func
            └── Block (nhãn)
                  ├── [Instr, ...]     ← không chứa rẽ nhánh
                  └── Terminator       ← đúng MỘT, ở cuối

Mọi cấu trúc điều khiển cấp cao (if/while/for/match/defer) được HẠ HẲN thành
jump/branch/switch — IR không giữ dạng cây. Nhờ vậy backend LLVM/WASM sau này
tiêu thụ trực tiếp được, mà không cần hiểu cú pháp G.

Biến cục bộ ở dạng ĐỊA CHỈ (`Alloca` + `Load`/`Store`), chưa phải SSA. Đây là
lựa chọn có chủ ý: đơn giản, dễ verify, và việc nâng lên SSA (mem2reg) là một
pass tối ưu độc lập thêm sau — không cần đúng ngay từ đầu.

Kiểu dùng lại `types.GType` nguyên vẹn (không tạo hệ kiểu thứ hai) để tránh
trôi lệch giữa checker và IR.
"""

from dataclasses import dataclass, field
from typing import Optional

from . import types as T


# ======================================================================
# Giá trị (toán hạng)
# ======================================================================

@dataclass(frozen=True)
class Value:
    """Toán hạng của một lệnh IR. Bất biến để so sánh/hash được."""
    kind: str            # temp | const | global | func | undef | strlit
    name: str = ""       # tên temp/global/func
    const: object = None # giá trị hằng (int/float/bool/str/None cho null)
    type: object = None  # GType

    def __str__(self):
        if self.kind == "temp":
            return f"%{self.name}"
        if self.kind == "global":
            return f"@{self.name}"
        if self.kind == "func":
            return f"@{self.name}"
        if self.kind == "strlit":
            s = self.const
            if len(s) > 24:
                s = s[:24] + "..."
            return '"' + s.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"') + '"'
        if self.kind == "undef":
            return "undef"
        if self.const is None:
            return "null"
        if self.const is True:
            return "true"
        if self.const is False:
            return "false"
        return str(self.const)


def temp(name: str, ty) -> Value:
    return Value("temp", name=name, type=ty)


def const_int(v: int, ty=None) -> Value:
    return Value("const", const=int(v), type=ty or T.I32)


def const_bool(v: bool) -> Value:
    return Value("const", const=bool(v), type=T.BOOL)


def const_float(v, ty=None) -> Value:
    return Value("const", const=v, type=ty or T.F64)


def const_str(s: str) -> Value:
    return Value("strlit", const=s, type=T.STR)


def const_null(ty=None) -> Value:
    return Value("const", const=None, type=ty or T.NULL)


def undef(ty) -> Value:
    return Value("undef", type=ty)


# ======================================================================
# Lệnh (không rẽ nhánh)
# ======================================================================

@dataclass
class Instr:
    """Một lệnh three-address.

    `op` quyết định ý nghĩa của `args`/`extra`; `dst` là temp nhận kết quả
    (None với lệnh chỉ có tác dụng phụ, vd Store).

    Tập op (đóng — verifier từ chối op lạ):

      bộ nhớ      alloca load store fieldaddr elemaddr ptradd memcpy
      số học      add sub mul div mod neg
      bit         and or xor shl shr not
      so sánh     eq ne lt le gt ge
      logic       land lor lnot
      ép kiểu     cast bitcast
      lời gọi     call callptr
      khác        select phi asm intrinsic panic check
    """
    op: str
    dst: Optional[Value] = None
    args: list = field(default_factory=list)
    type: object = None          # kiểu kết quả (GType)
    extra: dict = field(default_factory=dict)
    line: int = 0
    col: int = 0

    def __str__(self):
        a = ", ".join(str(x) for x in self.args)
        ex = ""
        if self.extra:
            # chỉ in các khoá ngắn gọn, bỏ những thứ dài dòng
            parts = []
            for k, v in self.extra.items():
                if k in ("body", "outputs", "inputs", "clobbers"):
                    continue
                parts.append(f"{k}={v}")
            if parts:
                ex = " {" + ", ".join(parts) + "}"
        head = f"{self.dst} = " if self.dst is not None else ""
        ty = f" : {self.type}" if self.type is not None and self.dst is not None else ""
        return f"{head}{self.op} {a}{ex}{ty}".rstrip()


# ======================================================================
# Terminator (kết thúc block)
# ======================================================================

@dataclass
class Term:
    """Lệnh kết thúc một basic block. Đúng một cái ở cuối mỗi block.

      ret     args=[val] hoặc []        trả về
      jump    labels=[L]                nhảy vô điều kiện
      branch  args=[cond] labels=[T,F]  rẽ nhánh hai chiều
      switch  args=[val] labels=[...]   nhiều nhánh; extra['cases']=[hằng,...]
                                        labels[-1] là nhánh mặc định
      unreach                           không thể tới (sau panic/vòng vô hạn)
    """
    op: str
    args: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    line: int = 0
    col: int = 0

    def __str__(self):
        if self.op == "ret":
            return "ret" + (f" {self.args[0]}" if self.args else "")
        if self.op == "jump":
            return f"jump {self.labels[0]}"
        if self.op == "branch":
            return f"branch {self.args[0]} ? {self.labels[0]} : {self.labels[1]}"
        if self.op == "switch":
            cases = self.extra.get("cases", [])
            arms = ", ".join(f"{c} => {l}"
                             for c, l in zip(cases, self.labels))
            dflt = self.labels[-1] if len(self.labels) > len(cases) else "-"
            return f"switch {self.args[0]} [{arms}] default {dflt}"
        return self.op


# ======================================================================
# Block / Func / Module
# ======================================================================

@dataclass
class Block:
    label: str
    instrs: list = field(default_factory=list)
    term: Optional[Term] = None

    def __str__(self):
        out = [f"  {self.label}:"]
        for i in self.instrs:
            out.append(f"    {i}")
        out.append(f"    {self.term if self.term else '<THIẾU TERMINATOR>'}")
        return "\n".join(out)


@dataclass
class Param:
    name: str
    type: object
    mutable: bool = False


@dataclass
class Func:
    name: str
    params: list = field(default_factory=list)     # [Param]
    ret: object = None                             # GType
    blocks: list = field(default_factory=list)     # [Block]
    is_extern: bool = False
    attrs: list = field(default_factory=list)
    src_file: Optional[str] = None

    @property
    def entry(self):
        return self.blocks[0] if self.blocks else None

    def __str__(self):
        ps = ", ".join(f"{'mut ' if p.mutable else ''}{p.name}: {p.type}"
                       for p in self.params)
        sig = f"fn @{self.name}({ps}) -> {self.ret}"
        if self.is_extern or not self.blocks:
            return f"{sig}  ; extern"
        return sig + " {\n" + "\n".join(str(b) for b in self.blocks) + "\n}"


@dataclass
class Global:
    name: str
    type: object
    init: object = None        # Value | list[Value] | None
    is_const: bool = False
    is_extern: bool = False
    mutable: bool = True

    def __str__(self):
        q = "const" if self.is_const else "global"
        if self.is_extern:
            return f"extern {q} @{self.name} : {self.type}"
        init = ""
        if self.init is not None:
            init = " = " + (f"[{', '.join(str(x) for x in self.init)}]"
                            if isinstance(self.init, list) else str(self.init))
        return f"{q} @{self.name} : {self.type}{init}"


@dataclass
class StructLayout:
    """Bố cục struct — backend cần để tính offset; ABI test cần để khoá lại."""
    name: str
    fields: list = field(default_factory=list)     # [(tên, GType)]
    packed: bool = False
    align: int = 0

    def __str__(self):
        fs = ", ".join(f"{n}: {t}" for n, t in self.fields)
        mod = " packed" if self.packed else ""
        return f"struct %{self.name}{mod} {{ {fs} }}"


@dataclass
class EnumLayout:
    name: str
    variants: list = field(default_factory=list)   # [(tên, giá trị int)]

    def __str__(self):
        vs = ", ".join(f"{n} = {v}" for n, v in self.variants)
        return f"enum %{self.name} {{ {vs} }}"


@dataclass
class Module:
    name: str = "main"
    structs: list = field(default_factory=list)
    enums: list = field(default_factory=list)
    globals: list = field(default_factory=list)
    funcs: list = field(default_factory=list)

    def func(self, name):
        for f in self.funcs:
            if f.name == name:
                return f
        return None

    def __str__(self):
        parts = [f"; G-IR module {self.name}"]
        for s in self.structs:
            parts.append(str(s))
        for e in self.enums:
            parts.append(str(e))
        if self.structs or self.enums:
            parts.append("")
        for g in self.globals:
            parts.append(str(g))
        if self.globals:
            parts.append("")
        for f in self.funcs:
            parts.append(str(f))
            parts.append("")
        return "\n".join(parts)


# ======================================================================
# Tập op hợp lệ (verifier dùng)
# ======================================================================

MEM_OPS = {"alloca", "load", "store", "fieldaddr", "elemaddr", "ptradd", "memcpy"}
ARITH_OPS = {"add", "sub", "mul", "div", "mod", "neg"}
BIT_OPS = {"and", "or", "xor", "shl", "shr", "not"}
CMP_OPS = {"eq", "ne", "lt", "le", "gt", "ge"}
LOGIC_OPS = {"land", "lor", "lnot"}
CAST_OPS = {"cast", "bitcast"}
CALL_OPS = {"call", "callptr"}
MISC_OPS = {"select", "phi", "asm", "intrinsic", "panic", "check"}

ALL_OPS = (MEM_OPS | ARITH_OPS | BIT_OPS | CMP_OPS | LOGIC_OPS
           | CAST_OPS | CALL_OPS | MISC_OPS)

TERM_OPS = {"ret", "jump", "branch", "switch", "unreach"}
