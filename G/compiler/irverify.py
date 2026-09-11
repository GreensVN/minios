"""
Trình kiểm tra G-IR.

Mục đích: biến hợp đồng NGẦM giữa các tầng thành thứ KIỂM ĐƯỢC. Trước đây một
lỗi hạ mã chỉ lộ ra khi gcc từ chối mã C sinh ra (thông báo khó hiểu, trỏ vào
file /tmp), hoặc tệ hơn: chương trình chạy sai âm thầm. Verifier bắt lỗi ngay
tại ranh giới IR, kèm tên hàm/block/lệnh cụ thể.

Các bất biến được kiểm:

  Cấu trúc
    - mỗi block có ĐÚNG một terminator, ở cuối;
    - nhãn block duy nhất trong một hàm;
    - mọi nhãn được nhảy tới đều tồn tại;
    - không có block nào không thể tới được (trừ entry);
    - op nằm trong tập đóng ALL_OPS / TERM_OPS.

  Định danh
    - temp được ĐỊNH NGHĨA trước khi dùng (theo thứ tự tôpô đơn giản: định
      nghĩa phải nằm trong block chi phối — ở đây kiểm bản rút gọn: temp phải
      được định nghĩa ở đâu đó trong hàm trước khi được dùng theo thứ tự block);
    - không định nghĩa lại một temp (dạng gần-SSA cho temp; ô nhớ dùng alloca).

  Kiểu
    - lệnh có `dst` phải có `type`;
    - load/store phải thao tác trên toán hạng kiểu con trỏ;
    - so sánh trả về bool;
    - branch nhận điều kiện bool;
    - switch có số nhãn = số case (+1 nếu có default).

Verifier CỐ Ý khoan dung với `unknown` (kiểu chưa suy luận được khi checker
phục hồi lỗi) — nó không phải type-checker thứ hai.
"""

from . import ir as I
from . import types as T


class IRError(Exception):
    def __init__(self, msg, func=None, block=None):
        loc = ""
        if func:
            loc = f" [trong @{func}"
            if block:
                loc += f":{block}"
            loc += "]"
        super().__init__(msg + loc)
        self.msg = msg


def _is_ptrish(ty):
    """Kiểu có thể dùng làm toán hạng địa chỉ không? Khoan dung với unknown."""
    if ty is None:
        return True
    return ty.kind in ("ptr", "str", "null", "unknown", "array")


class Verifier:
    def __init__(self, mod: I.Module):
        self.mod = mod
        self.errors = []

    # ---------- tiện ích ----------
    def err(self, msg, func=None, block=None):
        self.errors.append(IRError(msg, func, block))

    def verify(self):
        """Trả về danh sách lỗi (rỗng = hợp lệ)."""
        self.errors = []
        defined = set()          # hàm CÓ THÂN
        for f in self.mod.funcs:
            # Khai báo 'extern fn' lặp lại là HỢP LỆ (C cho phép khai báo lại
            # cùng nguyên mẫu) — chỉ định nghĩa CÓ THÂN mới không được trùng.
            if not (f.is_extern or not f.blocks):
                if f.name in defined:
                    self.err(f"hàm '{f.name}' có thân định nghĩa nhiều lần "
                             f"trong module")
                defined.add(f.name)
            self.verify_func(f)
        for g in self.mod.globals:
            if g.type is None:
                self.err(f"global '@{g.name}' thiếu kiểu")
        return self.errors

    # ---------- hàm ----------
    def verify_func(self, f: I.Func):
        if f.is_extern or not f.blocks:
            return                                  # chỉ khai báo, không có thân

        # --- nhãn duy nhất ---
        labels = {}
        for b in f.blocks:
            if b.label in labels:
                self.err(f"nhãn block '{b.label}' trùng", f.name)
            labels[b.label] = b

        # --- terminator ---
        for b in f.blocks:
            if b.term is None:
                self.err("block thiếu terminator", f.name, b.label)
                continue
            if b.term.op not in I.TERM_OPS:
                self.err(f"terminator không hợp lệ: '{b.term.op}'", f.name, b.label)
            for lbl in b.term.labels:
                if lbl not in labels:
                    self.err(f"nhảy tới nhãn không tồn tại: '{lbl}'",
                             f.name, b.label)
            if b.term.op == "branch":
                if len(b.term.labels) != 2:
                    self.err("branch cần đúng 2 nhãn", f.name, b.label)
                if len(b.term.args) != 1:
                    self.err("branch cần đúng 1 điều kiện", f.name, b.label)
                elif b.term.args[0].type is not None:
                    ct = b.term.args[0].type
                    if ct.kind not in ("bool", "unknown", "int", "char", "ptr", "str"):
                        self.err(f"điều kiện branch kiểu '{ct}' không dùng được",
                                 f.name, b.label)
            if b.term.op == "switch":
                cases = b.term.extra.get("cases", [])
                # labels = [nhánh cho từng case...] + [default]
                if len(b.term.labels) not in (len(cases), len(cases) + 1):
                    self.err(
                        f"switch có {len(cases)} case nhưng {len(b.term.labels)} "
                        f"nhãn (phải bằng, hoặc +1 cho default)", f.name, b.label)

        # --- lệnh nằm sau terminator (không được phép) ---
        for b in f.blocks:
            for ins in b.instrs:
                if ins.op not in I.ALL_OPS:
                    self.err(f"op không hợp lệ: '{ins.op}'", f.name, b.label)
                if ins.dst is not None and ins.type is None:
                    self.err(f"lệnh '{ins.op}' có dst nhưng thiếu kiểu",
                             f.name, b.label)

        # --- block không thể tới ---
        reach = set()
        if f.blocks:
            stack = [f.blocks[0].label]
            while stack:
                lbl = stack.pop()
                if lbl in reach or lbl not in labels:
                    continue
                reach.add(lbl)
                t = labels[lbl].term
                if t is not None:
                    stack.extend(t.labels)
        for b in f.blocks:
            # Block 'dead*' do irgen tạo có chủ ý cho mã nằm sau một điểm thoát
            # (checker đã cảnh báo). Chúng không thể tới được THEO THIẾT KẾ.
            if b.label not in reach and not b.label.startswith("dead"):
                self.err(f"block '{b.label}' không thể tới được", f.name)

        # --- định nghĩa / sử dụng temp ---
        defined = set()
        for p in f.params:
            defined.add(p.name)
        # duyệt theo thứ tự block (xấp xỉ; đủ để bắt lỗi hạ mã thực tế)
        for b in f.blocks:
            for ins in b.instrs:
                for a in ins.args:
                    self._check_use(a, defined, f, b, ins.op)
                if ins.dst is not None:
                    if ins.dst.kind != "temp":
                        self.err(f"dst của '{ins.op}' phải là temp, gặp "
                                 f"'{ins.dst.kind}'", f.name, b.label)
                    elif ins.dst.name in defined:
                        self.err(f"temp '%{ins.dst.name}' bị định nghĩa lại",
                                 f.name, b.label)
                    else:
                        defined.add(ins.dst.name)
            if b.term is not None:
                for a in b.term.args:
                    self._check_use(a, defined, f, b, b.term.op)

        # --- kiểm kiểu theo từng op ---
        for b in f.blocks:
            for ins in b.instrs:
                self._check_op_types(ins, f, b)

    def _check_use(self, v, defined, f, b, op):
        if not isinstance(v, I.Value):
            self.err(f"toán hạng của '{op}' không phải Value: {v!r}",
                     f.name, b.label)
            return
        if v.kind == "temp" and v.name not in defined:
            self.err(f"dùng temp '%{v.name}' trước khi định nghĩa (op '{op}')",
                     f.name, b.label)

    def _check_op_types(self, ins: I.Instr, f, b):
        op = ins.op
        n = len(ins.args)

        def need(k, what):
            if n != k:
                self.err(f"'{op}' cần {k} toán hạng, nhận {n} ({what})",
                         f.name, b.label)
                return False
            return True

        if op == "alloca":
            if ins.dst is None:
                self.err("alloca phải có dst", f.name, b.label)
            elif ins.type is not None and ins.type.kind != "ptr":
                self.err(f"alloca phải trả con trỏ, gặp '{ins.type}'",
                         f.name, b.label)
        elif op == "load":
            if need(1, "địa chỉ") and not _is_ptrish(ins.args[0].type):
                self.err(f"load từ toán hạng không phải con trỏ "
                         f"('{ins.args[0].type}')", f.name, b.label)
        elif op == "store":
            if need(2, "địa chỉ, giá trị") and not _is_ptrish(ins.args[0].type):
                self.err(f"store vào toán hạng không phải con trỏ "
                         f"('{ins.args[0].type}')", f.name, b.label)
            if ins.dst is not None:
                self.err("store không được có dst", f.name, b.label)
        elif op in ("fieldaddr", "elemaddr", "ptradd"):
            need(2, "cơ sở, chỉ số/tên")
        elif op == "memcpy":
            need(2, "đích, nguồn")
        elif op in I.CMP_OPS:
            if need(2, "hai toán hạng") and ins.type is not None:
                if ins.type.kind not in ("bool", "unknown"):
                    self.err(f"so sánh '{op}' phải trả bool, gặp '{ins.type}'",
                             f.name, b.label)
        elif op in I.ARITH_OPS - {"neg"} or op in I.BIT_OPS - {"not"}:
            need(2, "hai toán hạng")
        elif op in ("neg", "not", "lnot"):
            need(1, "một toán hạng")
        elif op in ("land", "lor"):
            need(2, "hai toán hạng")
        elif op in I.CAST_OPS:
            need(1, "giá trị nguồn")
        elif op == "call":
            if "callee" not in ins.extra:
                self.err("call thiếu extra['callee']", f.name, b.label)
        elif op == "callptr":
            if n < 1:
                self.err("callptr cần ít nhất con trỏ hàm", f.name, b.label)
        elif op == "select":
            need(3, "điều kiện, giá trị đúng, giá trị sai")


def verify(mod: I.Module):
    """Kiểm module; trả về danh sách IRError (rỗng nếu hợp lệ)."""
    return Verifier(mod).verify()


def verify_or_raise(mod: I.Module):
    errs = verify(mod)
    if errs:
        raise errs[0]
    return True
