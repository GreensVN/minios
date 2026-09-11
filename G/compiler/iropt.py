"""
Trình tối ưu G-IR.

VÌ SAO Ở ĐÂY, KHÔNG PHẢI TRONG BACKEND
======================================
Tối ưu đặt trên IR thì **mọi backend** (C, LLVM, WASM) cùng hưởng. Đặt trong
backend C thì LLVM lại phải làm lại từ đầu — và mỗi lần làm lại là một cơ hội
sai khác.

Lưu ý thực tế: backend C hiện tại đưa mã cho `gcc -O2`, nên các pass dưới đây
KHÔNG nhằm đánh bại gcc. Chúng nhằm (a) làm IR nhỏ và dễ đọc hơn cho các pass
sau, (b) là hạ tầng sẵn sàng cho backend LLVM/WASM nơi không có ai dọn hộ.

TIÊU CHÍ ĐÚNG
=============
Một pass hợp lệ **không được đổi kết quả chạy**. `tests/run_opt_diff.sh` chạy
chương trình trước và sau tối ưu bằng trình thông dịch rồi so từng byte. Đó là
lý do trình thông dịch được viết TRƯỚC trình tối ưu.

CÁC PASS
========
  const-fold      : gấp phép toán trên hằng
  copy-prop       : lan truyền 'temp = temp'
  dce             : xoá lệnh có kết quả không ai dùng (giữ lệnh có TÁC DỤNG PHỤ)
  simplify-cfg    : gộp branch trên hằng, bỏ block không thể tới, nối block

Mỗi pass idempotent và chạy lặp tới điểm bất động (tối đa `MAX_ROUNDS`).
"""

from . import ir as I
from . import types as T

MAX_ROUNDS = 8

#: Lệnh có TÁC DỤNG PHỤ — không bao giờ được xoá dù kết quả không ai dùng.
_EFFECTFUL = {"store", "call", "callptr", "asm", "panic", "check",
              "intrinsic", "memcpy"}


class Stats:
    __slots__ = ("folded", "copies", "dead", "blocks", "branches", "mem")

    def __init__(self):
        self.folded = self.copies = self.dead = self.blocks = 0
        self.branches = self.mem = 0

    def total(self):
        return (self.folded + self.copies + self.dead + self.blocks
                + self.branches + self.mem)

    def __str__(self):
        return (f"gấp hằng {self.folded}, sao chép {self.copies}, "
                f"lệnh chết {self.dead}, block {self.blocks}, "
                f"nhánh {self.branches}, ô nhớ {self.mem}")


# ----------------------------------------------------------------------
def optimize(mod: I.Module, stats: Stats = None) -> Stats:
    st = stats or Stats()
    for f in mod.funcs:
        if f.is_extern or not f.blocks:
            continue
        for _ in range(MAX_ROUNDS):
            before = st.total()
            mem2reg(f, st)
            const_fold(f, st)
            copy_prop(f, st)
            simplify_cfg(f, st)
            dce(f, st)
            if st.total() == before:
                break
    return st


# ----------------------------------------------------------------------
def _is_const(v):
    return isinstance(v, I.Value) and v.kind == "const" and \
        isinstance(v.const, (int, bool)) and not isinstance(v.const, str)


def _cv(v):
    c = v.const
    return int(c) if isinstance(c, bool) else c


_FOLD_BIN = {
    "add": lambda a, b: a + b, "sub": lambda a, b: a - b,
    "mul": lambda a, b: a * b,
    "and": lambda a, b: a & b, "or": lambda a, b: a | b,
    "xor": lambda a, b: a ^ b,
}
_FOLD_CMP = {
    "eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
    "lt": lambda a, b: a < b, "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b, "ge": lambda a, b: a >= b,
}


def _wrap(v, ty):
    """Cắt về bề rộng kiểu — gấp hằng PHẢI khớp ngữ nghĩa wrap của C."""
    if ty is None or not isinstance(v, int) or isinstance(v, bool):
        return v
    if ty.kind not in ("int", "char"):
        return v
    bits = ty.bits or 32
    v &= (1 << bits) - 1
    if ty.signed and v >= (1 << (bits - 1)):
        v -= 1 << bits
    return v


def mem2reg(f: I.Func, st: Stats):
    """Bỏ 'alloca' vô hướng chỉ dùng trong MỘT block, thay load/store bằng temp.

    IR sinh ra ở dạng địa chỉ (mọi biến là alloca + load/store) cho đơn giản và
    dễ verify. Phần lớn lệnh trong IR là load/store như vậy, nên đây là pass có
    tác động lớn nhất.

    CỐ Ý bảo thủ — chỉ xử lý alloca thoả TẤT CẢ:
      * kiểu vô hướng (không mảng/struct/slice);
      * chỉ xuất hiện trong load/store (không bị lấy địa chỉ, không truyền đi);
      * mọi lần dùng nằm trong CÙNG một block.
    Vượt ra ngoài các điều kiện này cần phân tích dominance + chèn phi; chưa
    làm, vì một pass sai còn tệ hơn không có pass."""
    # đếm cách dùng của từng alloca
    info = {}
    for b in f.blocks:
        for ins in b.instrs:
            if ins.op == "alloca" and ins.dst is not None:
                ty = ins.type.elem if ins.type is not None else None
                ok = ty is not None and ty.kind in (
                    "int", "float", "bool", "char", "enum", "str", "ptr")
                info[ins.dst.name] = {"ok": ok, "blocks": set(), "other": False}
    for b in f.blocks:
        for ins in b.instrs:
            for k, a in enumerate(ins.args):
                if not (isinstance(a, I.Value) and a.kind == "temp"):
                    continue
                d = info.get(a.name)
                if d is None:
                    continue
                if ins.op == "load" and k == 0:
                    d["blocks"].add(b.label)
                elif ins.op == "store" and k == 0:
                    d["blocks"].add(b.label)
                else:
                    d["other"] = True     # bị dùng theo cách khác -> bỏ qua
        if b.term is not None:
            for a in b.term.args:
                if isinstance(a, I.Value) and a.kind == "temp" \
                        and a.name in info:
                    info[a.name]["other"] = True

    promo = {n for n, d in info.items()
             if d["ok"] and not d["other"] and len(d["blocks"]) <= 1}
    # Loại các ô mà load/store dùng KIỂU KHÁC nhau: giá trị cất vào mang kiểu
    # nguồn, còn 'load' mang kiểu đích — chênh lệch đó chính là phép mở rộng
    # dấu/bề rộng mà backend sẽ sinh. Bỏ ô đi thì phép ấy biến mất
    # ('-w' với w: u32 in ra 4294967295 thay vì -1).
    if promo:
        slot_ty = {}
        for b in f.blocks:
            for ins in b.instrs:
                if ins.op == "alloca" and ins.dst is not None \
                        and ins.dst.name in promo:
                    slot_ty[ins.dst.name] = (ins.type.elem
                                             if ins.type is not None else None)
        bad = set()
        for b in f.blocks:
            for ins in b.instrs:
                if not ins.args or not isinstance(ins.args[0], I.Value):
                    continue
                nm = ins.args[0].name
                if ins.args[0].kind != "temp" or nm not in promo:
                    continue
                want = slot_ty.get(nm)
                if ins.op == "load" and not _same_type(ins.type, want):
                    bad.add(nm)
                elif ins.op == "store" and len(ins.args) > 1 \
                        and not _same_type(ins.args[1].type, want):
                    bad.add(nm)
        promo -= bad
    if not promo:
        return

    for b in f.blocks:
        cur = {}                       # tên alloca -> Value đang giữ
        out = []
        for ins in b.instrs:
            if ins.op == "alloca" and ins.dst is not None \
                    and ins.dst.name in promo:
                cur[ins.dst.name] = I.Value(
                    "const", const=0,
                    type=ins.type.elem if ins.type is not None else None)
                st.mem += 1
                continue
            if ins.op == "store" and ins.args and \
                    isinstance(ins.args[0], I.Value) and \
                    ins.args[0].kind == "temp" and ins.args[0].name in promo:
                cur[ins.args[0].name] = ins.args[1]
                st.mem += 1
                continue
            if (ins.op == "load" and ins.args
                    and isinstance(ins.args[0], I.Value)
                    and ins.args[0].kind == "temp"
                    and ins.args[0].name in promo and ins.dst is not None):
                have = cur.get(ins.args[0].name)
                # CHỈ thay khi kiểu KHỚP: 'load : i64' của một ô chứa giá trị
                # u32 mang theo phép mở rộng dấu mà backend sẽ sinh; bỏ ô nhớ
                # đi thì phép đó biến mất ('-w' với w:u32 in 4294967295 thay
                # vì -1).
                if have is not None:
                    _replace_uses(f, ins.dst.name, have)
                    st.mem += 1
                    continue
            out.append(ins)
        b.instrs = out


def const_fold(f: I.Func, st: Stats):
    """Gấp phép toán mà MỌI toán hạng đều là hằng."""
    for b in f.blocks:
        for k, ins in enumerate(b.instrs):
            if ins.dst is None or len(ins.args) < 1:
                continue
            if not all(_is_const(a) for a in ins.args):
                continue
            op = ins.op
            try:
                if op in _FOLD_BIN:
                    r = _FOLD_BIN[op](_cv(ins.args[0]), _cv(ins.args[1]))
                    nv = I.Value("const", const=_wrap(r, ins.type),
                                 type=ins.type)
                elif op in _FOLD_CMP:
                    r = _FOLD_CMP[op](_cv(ins.args[0]), _cv(ins.args[1]))
                    nv = I.Value("const", const=bool(r), type=T.BOOL)
                elif op in ("div", "mod"):
                    a, d = _cv(ins.args[0]), _cv(ins.args[1])
                    if d == 0:
                        continue          # chia 0: để runtime panic, ĐỪNG gấp
                    q = abs(a) // abs(d)
                    if (a < 0) != (d < 0):
                        q = -q
                    r = q if op == "div" else a - q * d
                    nv = I.Value("const", const=_wrap(r, ins.type),
                                 type=ins.type)
                elif op in ("shl", "shr"):
                    a, k2 = _cv(ins.args[0]), _cv(ins.args[1])
                    if k2 < 0 or k2 > 63:
                        continue
                    r = (a << k2) if op == "shl" else (a >> k2)
                    nv = I.Value("const", const=_wrap(r, ins.type),
                                 type=ins.type)
                elif op == "neg":
                    nv = I.Value("const", const=_wrap(-_cv(ins.args[0]),
                                                      ins.type), type=ins.type)
                elif op == "lnot":
                    nv = I.Value("const", const=not _cv(ins.args[0]),
                                 type=T.BOOL)
                elif op in ("land", "lor"):
                    a, c = bool(_cv(ins.args[0])), bool(_cv(ins.args[1]))
                    nv = I.Value("const", const=(a and c) if op == "land"
                                 else (a or c), type=T.BOOL)
                else:
                    continue
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            _replace_uses(f, ins.dst.name, nv)
            b.instrs[k] = I.Instr("__nop", line=ins.line, col=ins.col)
            st.folded += 1


def copy_prop(f: I.Func, st: Stats):
    """Lan truyền 'x = select(true, a, b)' và các phép gán tầm thường."""
    for b in f.blocks:
        for k, ins in enumerate(b.instrs):
            if ins.dst is None:
                continue
            repl = None
            if ins.op == "select" and _is_const(ins.args[0]):
                repl = ins.args[1] if _cv(ins.args[0]) else ins.args[2]
            elif ins.op == "cast" and ins.type is not None \
                    and ins.args[0].type is not None \
                    and _same_type(ins.type, ins.args[0].type):
                repl = ins.args[0]        # ép kiểu về CHÍNH kiểu đó
            if repl is None:
                continue
            _replace_uses(f, ins.dst.name, repl)
            b.instrs[k] = I.Instr("__nop", line=ins.line, col=ins.col)
            st.copies += 1


def _same_type(a, b):
    if a is None or b is None:
        return False
    return (a.kind == b.kind and a.name == b.name and a.bits == b.bits
            and a.signed == b.signed)


def dce(f: I.Func, st: Stats):
    """Xoá lệnh có kết quả KHÔNG AI DÙNG và không có tác dụng phụ."""
    used = set()
    for b in f.blocks:
        for ins in b.instrs:
            for a in ins.args:
                if isinstance(a, I.Value) and a.kind == "temp":
                    used.add(a.name)
        if b.term is not None:
            for a in b.term.args:
                if isinstance(a, I.Value) and a.kind == "temp":
                    used.add(a.name)
    for b in f.blocks:
        keep = []
        for ins in b.instrs:
            if ins.op == "__nop":
                continue
            if (ins.dst is not None and ins.dst.name not in used
                    and ins.op not in _EFFECTFUL and ins.op != "alloca"):
                st.dead += 1
                continue
            keep.append(ins)
        b.instrs = keep


def simplify_cfg(f: I.Func, st: Stats):
    """Đơn giản hoá đồ thị luồng: nhánh hằng, block không tới, nối block."""
    labels = {b.label: b for b in f.blocks}

    # 1) 'branch <hằng>' -> 'jump'
    for b in f.blocks:
        t = b.term
        if t is not None and t.op == "branch" and _is_const(t.args[0]):
            tgt = t.labels[0] if _cv(t.args[0]) else t.labels[1]
            b.term = I.Term("jump", labels=[tgt], line=t.line, col=t.col)
            st.branches += 1
        elif (t is not None and t.op == "branch"
              and t.labels[0] == t.labels[1]):
            b.term = I.Term("jump", labels=[t.labels[0]], line=t.line,
                            col=t.col)
            st.branches += 1

    # 2) bỏ block KHÔNG THỂ TỚI (trừ entry)
    reach = set()
    stack = [f.blocks[0].label] if f.blocks else []
    while stack:
        lb = stack.pop()
        if lb in reach or lb not in labels:
            continue
        reach.add(lb)
        if labels[lb].term is not None:
            stack.extend(labels[lb].term.labels)
    if len(reach) < len(f.blocks):
        st.blocks += len(f.blocks) - len(reach)
        f.blocks = [b for b in f.blocks if b.label in reach]
        labels = {b.label: b for b in f.blocks}

    # 3) NỐI block: A kết thúc bằng 'jump B' và B chỉ có MỘT nguồn vào.
    preds = {}
    for b in f.blocks:
        if b.term is not None:
            for lb in b.term.labels:
                preds.setdefault(lb, set()).add(b.label)
    merged = True
    while merged:
        merged = False
        for b in list(f.blocks):
            t = b.term
            if t is None or t.op != "jump":
                continue
            tgt = labels.get(t.labels[0])
            if tgt is None or tgt is b or tgt.label == f.blocks[0].label:
                continue
            if preds.get(tgt.label) != {b.label}:
                continue
            b.instrs.extend(tgt.instrs)
            b.term = tgt.term
            f.blocks = [x for x in f.blocks if x is not tgt]
            labels.pop(tgt.label, None)
            # cập nhật preds cho các đích của block vừa gộp
            preds = {}
            for x in f.blocks:
                if x.term is not None:
                    for lb in x.term.labels:
                        preds.setdefault(lb, set()).add(x.label)
            st.blocks += 1
            merged = True
            break


def _replace_uses(f: I.Func, name, newv):
    for b in f.blocks:
        for ins in b.instrs:
            ins.args = [newv if (isinstance(a, I.Value) and a.kind == "temp"
                                 and a.name == name) else a
                        for a in ins.args]
        if b.term is not None:
            b.term.args = [newv if (isinstance(a, I.Value) and a.kind == "temp"
                                    and a.name == name) else a
                           for a in b.term.args]
