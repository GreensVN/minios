"""
Trình thông dịch THAM CHIẾU cho G-IR.

VÌ SAO CẦN
==========
Hai backend C hiện khớp nhau 106/106 — nhưng chúng **cùng đọc một IR**. Nếu
tầng hạ mã (`irgen.py`) hiểu sai ngữ nghĩa của G, cả hai sẽ sai GIỐNG HỆT nhau
và bộ so khớp vẫn báo xanh. Đó là điểm mù có thật.

Trình thông dịch này là **cách hiện thực hoá thứ ba, độc lập**: nó chạy IR trực
tiếp bằng Python, không qua C. So khớp đầu ra của nó với backend C phát hiện
đúng loại lỗi mà hai backend đồng thuận không thấy.

Nó cũng là **tiên đề (oracle) cho trình tối ưu**: một pass tối ưu đúng thì
không được đổi kết quả thông dịch.

PHẠM VI
=======
Đủ để chạy phần lớn chương trình test: số học, con trỏ/bộ nhớ mô phỏng, struct,
mảng, slice, chuỗi, in ấn, cấp phát, gọi hàm, mọi cấu trúc điều khiển.

CỐ Ý KHÔNG hỗ trợ (báo lỗi rõ ràng thay vì đoán):
  * `asm` (phụ thuộc kiến trúc thật);
  * intrinsic hệ điều hành (cổng I/O, MSR, thanh ghi điều khiển);
  * `extern fn` tới libc mà runtime không mô phỏng.

Bộ nhớ được mô hình hoá bằng các ô Python có địa chỉ giả (`Ptr`), nên
use-after-free và vượt biên bị BẮT thay vì trở thành hành vi không xác định —
một lợi ích phụ đáng kể so với chạy mã C.
"""

import sys

from . import ir as I
from . import types as T


class InterpError(Exception):
    """Lỗi của CHÍNH trình thông dịch (IR không hợp lệ / chưa hỗ trợ)."""


class GPanic(Exception):
    """Chương trình G panic (vượt biên, chia 0...) — tương ứng mã thoát 101."""

    def __init__(self, msg):
        super().__init__(msg)
        self.msg = msg


class Cell:
    """Một vùng nhớ có thể địa chỉ hoá: danh sách ô + cờ đã giải phóng."""
    __slots__ = ("data", "freed", "note")

    def __init__(self, n, note=""):
        self.data = [None] * n
        self.freed = False
        self.note = note


class Ptr:
    """Con trỏ = (vùng nhớ, chỉ số). Cho phép bắt lỗi thay vì UB."""
    __slots__ = ("cell", "idx")

    def __init__(self, cell, idx=0):
        self.cell = cell
        self.idx = idx

    def __add__(self, k):
        return Ptr(self.cell, self.idx + int(k))

    def check(self, what="truy cập"):
        if self.cell.freed:
            raise GPanic(f"{what} bộ nhớ đã giải phóng (use-after-free)")
        if not (0 <= self.idx < len(self.cell.data)):
            raise GPanic(f"{what} ngoài vùng nhớ "
                         f"(chỉ số {self.idx}, cỡ {len(self.cell.data)})")

    def load(self):
        self.check("đọc")
        return self.cell.data[self.idx]

    def store(self, v):
        self.check("ghi")
        self.cell.data[self.idx] = v

    def __repr__(self):
        return f"Ptr(+{self.idx})"

    def __eq__(self, o):
        if isinstance(o, Ptr):
            return self.cell is o.cell and self.idx == o.idx
        return NotImplemented if o is not None else False

    def __hash__(self):
        return hash((id(self.cell), self.idx))

    def __bool__(self):
        return True


class Slice:
    """slice<T> = (con trỏ, độ dài)."""
    __slots__ = ("ptr", "len")

    def __init__(self, ptr, ln):
        self.ptr = ptr
        self.len = int(ln)


class StructVal:
    """Giá trị struct — ngữ nghĩa GIÁ TRỊ, nên phải sao chép khi gán."""
    __slots__ = ("name", "fields")

    def __init__(self, name, fields=None):
        self.name = name
        self.fields = dict(fields or {})

    def copy(self):
        return StructVal(self.name,
                         {k: (v.copy() if isinstance(v, StructVal) else v)
                          for k, v in self.fields.items()})


class _Ret(Exception):
    def __init__(self, v):
        self.value = v


class Interp:
    """Chạy một `ir.Module`. `run()` trả về mã thoát của `main`."""

    MAX_STEPS = 20_000_000

    def __init__(self, mod: I.Module, out=None, err=None):
        self.mod = mod
        self.out = out if out is not None else sys.stdout
        self.err = err if err is not None else sys.stderr
        self.funcs = {f.name: f for f in mod.funcs}
        self.structs = {s.name: s for s in mod.structs}
        self.enums = {e.name: dict(e.variants) for e in mod.enums}
        self.globals = {}
        self.steps = 0
        self._depth = 0

    # ------------------------------------------------------------------
    def run(self, entry="main"):
        for g in self.mod.globals:
            self.globals[g.name] = Cell(1, f"global {g.name}")
            self.globals[g.name].data[0] = self._init_value(g)
        ctor = self.funcs.get("_g_init_globals")
        if ctor is not None and ctor.blocks:
            self.call(ctor, [])
        fn = self.funcs.get(entry)
        if fn is None or not fn.blocks:
            raise InterpError(f"không tìm thấy hàm '{entry}' có thân")
        r = self.call(fn, [])
        return int(r) if isinstance(r, (int, bool)) else 0

    def _init_value(self, g):
        if isinstance(g.init, list):
            c = Cell(len(g.init), f"arr {g.name}")
            for i, v in enumerate(g.init):
                c.data[i] = self._const(v)
            return Ptr(c, 0)
        if g.init is not None:
            return self._const(g.init)
        return self._zero(g.type)

    def _zero(self, ty):
        if ty is None:
            return 0
        if ty.kind == "array" and isinstance(ty.n, int):
            return Ptr(self._flat_array(ty), 0)
        if ty.kind == "struct":
            st = self.structs.get(ty.name)
            sv = StructVal(ty.name)
            if st:
                for fn, ft in st.fields:
                    sv.fields[fn] = self._zero(ft)
            return sv
        if ty.kind == "slice":
            return Slice(Ptr(Cell(0, "empty"), 0), 0)
        if ty.kind == "float":
            return 0.0
        if ty.kind == "bool":
            return False
        if ty.kind == "str":
            return ""
        if ty.kind in ("ptr", "null", "func"):
            return None
        return 0

    @staticmethod
    def _flat_len(ty):
        """Tổng số phần tử VÔ HƯỚNG của một kiểu mảng (bố cục phẳng)."""
        n = 1
        cur = ty
        while cur is not None and cur.kind == "array" and isinstance(cur.n, int):
            n *= cur.n
            cur = cur.elem
        return n

    def _flat_array(self, ty):
        """Một ô duy nhất chứa toàn bộ phần tử của mảng (kể cả nhiều chiều)."""
        n = self._flat_len(ty)
        base = ty
        while base is not None and base.kind == "array":
            base = base.elem
        c = Cell(n, "arr")
        for i in range(n):
            c.data[i] = self._zero(base)
        return c

    def _const(self, v: I.Value):
        if v.kind == "strlit":
            return v.const
        c = v.const
        if c is None:
            return None
        if isinstance(c, str) and v.type is not None and v.type.kind == "char":
            return c
        if v.type is not None and v.type.kind == "float":
            return float(c)
        return c

    # ------------------------------------------------------------------
    def call(self, fn: I.Func, args):
        if self._depth > 400:
            raise GPanic("tràn ngăn xếp (đệ quy quá sâu)")
        env = {}
        for p, a in zip(fn.params, args):
            env[p.name] = a
        blocks = {b.label: b for b in fn.blocks}
        cur = fn.blocks[0]
        self._depth += 1
        try:
            while True:
                for ins in cur.instrs:
                    self.steps += 1
                    if self.steps > self.MAX_STEPS:
                        raise GPanic("vượt giới hạn bước thực thi "
                                     "(có thể lặp vô hạn)")
                    self.exec_instr(ins, env, fn)
                t = cur.term
                if t is None:
                    raise InterpError(f"block '{cur.label}' thiếu terminator")
                if t.op == "ret":
                    return self.val(t.args[0], env) if t.args else None
                if t.op == "jump":
                    cur = blocks[t.labels[0]]
                    continue
                if t.op == "branch":
                    c = self.val(t.args[0], env)
                    cur = blocks[t.labels[0] if self._truthy(c) else t.labels[1]]
                    continue
                if t.op == "switch":
                    v = self.val(t.args[0], env)
                    cases = t.extra.get("cases", [])
                    tgt = None
                    for cv, lbl in zip(cases, t.labels):
                        if self._eqv(v, cv):
                            tgt = lbl
                            break
                    if tgt is None:
                        if len(t.labels) > len(cases):
                            tgt = t.labels[-1]
                        else:
                            raise InterpError("switch không khớp và không có "
                                              "nhánh mặc định")
                    cur = blocks[tgt]
                    continue
                if t.op == "unreach":
                    raise InterpError(
                        f"tới được lệnh 'unreach' trong @{fn.name} — hàm "
                        f"non-void không trả giá trị?")
                raise InterpError(f"terminator chưa hỗ trợ: {t.op}")
        except _Ret as r:
            return r.value
        finally:
            self._depth -= 1

    @staticmethod
    def _truthy(v):
        if isinstance(v, Ptr):
            return True
        if v is None:
            return False
        if isinstance(v, str):
            return True
        return bool(v)

    @staticmethod
    def _eqv(a, b):
        if isinstance(a, str) and len(a) == 1 and isinstance(b, int):
            return ord(a) == b
        if isinstance(a, bool):
            return int(a) == b
        return a == b

    def val(self, v, env):
        if not isinstance(v, I.Value):
            raise InterpError(f"toán hạng không phải Value: {v!r}")
        if v.kind == "temp":
            if v.name not in env:
                raise InterpError(f"temp '%{v.name}' chưa có giá trị")
            return env[v.name]
        if v.kind == "global":
            g = self.globals.get(v.name)
            if g is None:
                raise InterpError(f"global '@{v.name}' chưa khởi tạo")
            return Ptr(g, 0)
        if v.kind == "func":
            return self.funcs.get(v.name) or v.name
        if v.kind == "undef":
            return self._zero(v.type)
        return self._const(v)

    # ------------------------------------------------------------------
    _BIN = {
        "add": lambda a, b: a + b, "sub": lambda a, b: a - b,
        "mul": lambda a, b: a * b,
        "and": lambda a, b: a & b, "or": lambda a, b: a | b,
        "xor": lambda a, b: a ^ b,
        "shl": lambda a, b: a << b, "shr": lambda a, b: a >> b,
    }
    _CMP = {
        "eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
        "lt": lambda a, b: a < b, "le": lambda a, b: a <= b,
        "gt": lambda a, b: a > b, "ge": lambda a, b: a >= b,
    }

    def exec_instr(self, ins: I.Instr, env, fn):
        op = ins.op
        d = ins.dst.name if ins.dst is not None else None

        if op == "alloca":
            # 'alloca : *T' cấp một Ô chứa T rồi trả CON TRỎ tới ô đó. Với
            # T = [N]U, ô chứa chính N phần tử (mảng là bố cục phẳng trong C),
            # nên con trỏ trỏ thẳng vào phần tử đầu — khớp cách 'elemaddr'
            # cộng chỉ số.
            inner = ins.type.elem if ins.type is not None else None
            if inner is not None and inner.kind == "array" \
                    and isinstance(inner.n, int):
                # Mảng là bố cục PHẲNG như trong C: một ô duy nhất gồm TỔNG số
                # phần tử. Nhờ vậy 'elemaddr' luôn là phép cộng offset đơn giản,
                # khớp đúng những gì IR mô tả ('elemaddr %v, i : *[3]int' cho
                # hàng, rồi '+ j' cho phần tử).
                env[d] = Ptr(self._flat_array(inner), 0)
            else:
                c = Cell(1, ins.extra.get("name", ""))
                c.data[0] = self._zero(inner)
                env[d] = Ptr(c, 0)
            return
        if op == "load":
            p = self.val(ins.args[0], env)
            lt = ins.type
            if (isinstance(p, Ptr) and lt is not None and lt.kind == "array"
                    and isinstance(lt.n, int)):
                # 'load : [N]T' — mảng PHÂN RÃ thành con trỏ, không phải đọc ô.
                env[ins.dst.name] = p
                return
            if isinstance(p, Ptr):
                v = p.load()
            elif isinstance(p, (StructVal, Slice)):
                v = p
            else:
                raise GPanic("giải tham chiếu con trỏ null")
            env[d] = v.copy() if isinstance(v, StructVal) else v
            return
        if op == "store":
            p = self.val(ins.args[0], env)
            v = self.val(ins.args[1], env)
            if not isinstance(p, Ptr):
                raise GPanic("ghi qua con trỏ null")
            # 'store <ô mảng>, <con trỏ mảng>': trong C mảng nằm TẠI CHỖ, không
            # có "ô chứa con trỏ". Sao chép nội dung thay vì cất con trỏ, nếu
            # không lần đọc sau sẽ lấy ra Ptr chứ không phải phần tử.
            pt = ins.args[0].type
            if (isinstance(v, Ptr) and pt is not None and pt.kind == "ptr"
                    and pt.elem is not None and pt.elem.kind == "array"):
                self._copy_into(p, v)
                return
            p.store(v.copy() if isinstance(v, StructVal) else v)
            return
        if op == "memcpy":
            dst = self.val(ins.args[0], env)
            src = self.val(ins.args[1], env)
            self._copy_into(dst, src)
            return
        if op == "elemaddr":
            # Mảng có bố cục PHẲNG như C: một ô liên tục cho mọi phần tử.
            #   'elemaddr p, i : *T'     -> p + i          (phần tử)
            #   'elemaddr p, i : *[N]T'  -> p + i*N        (HÀNG của mảng 2D)
            # Nhờ vậy 'elemaddr' hai lần trên [2][3]int đi đúng vị trí, và
            # không cần đoán theo giá trị trong ô.
            base = self.val(ins.args[0], env)
            idx = int(self._num(self.val(ins.args[1], env)))
            if ins.extra.get("on") == "slice":
                if not isinstance(base, Slice):
                    raise InterpError("elemaddr on=slice nhưng cơ sở không "
                                      "phải slice")
                env[d] = base.ptr + idx
                return
            # Trường MẢNG của struct: ô trường giữ Ptr tới vùng mảng.
            if isinstance(base, _FieldPtr):
                inner = base.load()
                if isinstance(inner, Ptr):
                    base = inner
            rt = ins.type
            if (rt is not None and rt.kind == "ptr" and rt.elem is not None
                    and rt.elem.kind == "array" and isinstance(rt.elem.n, int)):
                idx *= self._flat_len(rt.elem)
            if isinstance(base, Slice):
                env[d] = base.ptr + idx
                return
            if isinstance(base, Ptr):
                env[d] = base + idx
                return
            raise GPanic("lập chỉ số trên con trỏ null")
        if op == "fieldaddr":
            base = self.val(ins.args[0], env)
            fname = ins.extra.get("field") or ins.args[1].const
            sv = base.load() if isinstance(base, Ptr) else base
            if not isinstance(sv, StructVal):
                raise GPanic("truy cập trường trên giá trị không phải struct")
            env[d] = _FieldPtr(sv, fname)
            return
        if op == "ptradd":
            env[d] = self.val(ins.args[0], env) + int(self.val(ins.args[1], env))
            return
        if op in self._BIN:
            a = self.val(ins.args[0], env)
            b = self.val(ins.args[1], env)
            # SỐ HỌC CON TRỎ: 'p + i' / 'p - i' hạ thành 'add'/'sub' thường.
            if op in ("add", "sub") and (isinstance(a, Ptr) or isinstance(b, Ptr)):
                if isinstance(a, Ptr) and isinstance(b, Ptr):
                    if op != "sub":
                        raise InterpError("cộng hai con trỏ")
                    env[d] = a.idx - b.idx
                    return
                p, k = (a, self._num(b)) if isinstance(a, Ptr) else (b, self._num(a))
                env[d] = p + (int(k) if op == "add" else -int(k))
                return
            env[d] = self._wrap(self._BIN[op](self._num(a), self._num(b)),
                                ins.type)
            return
        if op in ("div", "mod"):
            a = self._num(self.val(ins.args[0], env))
            b = self._num(self.val(ins.args[1], env))
            if b == 0:
                raise GPanic("chia cho 0")
            if isinstance(a, float) or isinstance(b, float):
                r = (a / b) if op == "div" else (a - b * int(a / b))
            else:
                q = abs(a) // abs(b)
                if (a < 0) != (b < 0):
                    q = -q
                r = q if op == "div" else a - q * b
            env[d] = self._wrap(r, ins.type)
            return
        if op in self._CMP:
            a = self.val(ins.args[0], env)
            b = self.val(ins.args[1], env)
            env[d] = bool(self._CMP[op](self._ord(a), self._ord(b)))
            return
        if op == "neg":
            env[d] = self._wrap(-self._num(self.val(ins.args[0], env)), ins.type)
            return
        if op == "not":
            env[d] = self._wrap(~int(self.val(ins.args[0], env)), ins.type)
            return
        if op == "lnot":
            env[d] = not self._truthy(self.val(ins.args[0], env))
            return
        if op in ("land", "lor"):
            a = self._truthy(self.val(ins.args[0], env))
            b = self._truthy(self.val(ins.args[1], env))
            env[d] = (a and b) if op == "land" else (a or b)
            return
        if op == "select":
            c = self._truthy(self.val(ins.args[0], env))
            env[d] = self.val(ins.args[1] if c else ins.args[2], env)
            return
        if op in ("cast", "bitcast"):
            env[d] = self._cast(self.val(ins.args[0], env), ins.type,
                                ins.extra.get("to_c"))
            return
        if op == "call":
            env[d] = self.do_call(ins, env)
            return
        if op == "callptr":
            f = self.val(ins.args[0], env)
            args = [self.val(a, env) for a in ins.args[1:]]
            if isinstance(f, I.Func):
                env[d] = self.call(f, args)
                return
            if isinstance(f, str) and f in self.funcs:
                env[d] = self.call(self.funcs[f], args)
                return
            raise GPanic("gọi qua con trỏ hàm null")
        if op == "check":
            self.do_check(ins, env)
            return
        if op == "intrinsic":
            r = self.do_intrinsic(ins, env)
            if d is not None:
                env[d] = r
            return
        if op == "panic":
            raise GPanic(str(self.val(ins.args[0], env)) if ins.args else "panic")
        if op == "asm":
            raise InterpError(
                "trình thông dịch không chạy được 'asm' (phụ thuộc kiến trúc "
                "thật) — bỏ qua ca này")
        raise InterpError(f"lệnh chưa hỗ trợ: '{op}'")

    # ------------------------------------------------------------------
    @staticmethod
    def _num(v):
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, str) and len(v) == 1:
            return ord(v)
        if v is None:
            return 0
        return v

    @staticmethod
    def _ord(v):
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, Ptr):
            return (id(v.cell), v.idx)
        if v is None:
            return (0, 0)
        return v

    @staticmethod
    def _wrap(v, ty):
        """Cắt về đúng bề rộng/dấu của kiểu — C wrap chứ không phải số nguyên lớn."""
        if ty is None or not isinstance(v, int) or isinstance(v, bool):
            return v
        if ty.kind == "float":
            return float(v)
        if ty.kind not in ("int", "char"):
            return v
        bits = ty.bits or 32
        v &= (1 << bits) - 1
        if ty.signed and v >= (1 << (bits - 1)):
            v -= 1 << bits
        return v

    def _cast(self, v, ty, to_c=None):
        if ty is None:
            return v
        if ty.kind == "float":
            return float(self._num(v))
        if ty.kind == "bool":
            return self._truthy(v)
        if ty.kind == "char":
            n = self._num(v)
            return chr(int(n) & 0xFF) if not isinstance(n, str) else n
        if ty.kind in ("int", "enum"):
            n = self._num(v)
            return self._wrap(int(n), ty if ty.kind == "int" else T.I32)
        return v

    def _copy_into(self, dst, src):
        """memcpy: sao chép NỘI DUNG (mảng/struct), KHÔNG chia sẻ con trỏ.

        Mảng nhiều chiều: ô chứa con trỏ hàng — phải sao chép SÂU, nếu không
        'let b = a' sẽ khiến b và a dùng chung hàng (đúng lỗi mà ngữ nghĩa giá
        trị của G cấm)."""
        if isinstance(dst, Ptr) and isinstance(src, Ptr):
            n = min(len(dst.cell.data) - dst.idx, len(src.cell.data) - src.idx)
            for i in range(n):
                dst.cell.data[dst.idx + i] = _deep_copy(
                    src.cell.data[src.idx + i])
            return
        if isinstance(dst, Ptr):
            dst.store(src.copy() if isinstance(src, StructVal) else src)

    def do_check(self, ins, env):
        kind = ins.extra.get("kind")
        where = f"{ins.line}:{ins.col}"
        if kind == "bounds":
            i = int(self.val(ins.args[0], env))
            n = int(self.val(ins.args[1], env))
            if not (0 <= i < n):
                raise GPanic(f"chỉ số {i} vượt biên mảng cỡ {n} tại {where}")
        elif kind == "slice_bounds":
            i = int(self.val(ins.args[0], env))
            s = self.val(ins.args[1], env)
            n = s.len if isinstance(s, Slice) else 0
            if not (0 <= i < n):
                raise GPanic(f"chỉ số {i} vượt biên mảng cỡ {n} tại {where}")
        elif kind == "divzero":
            if self._num(self.val(ins.args[0], env)) == 0:
                raise GPanic(f"chia cho 0 tại {where}")
        elif kind == "null":
            if self.val(ins.args[0], env) is None:
                raise GPanic(f"giải tham chiếu con trỏ null tại {where}")

    # ------------------------------------------------------------------
    def do_call(self, ins, env):
        callee = ins.extra.get("callee")
        args = [self.val(a, env) for a in ins.args]
        if ins.extra.get("is_print"):
            stream = self.err if ins.extra.get("stream") == "stderr" else self.out
            stream.write(_format(args[0], args[1:]))
            return None
        f = self.funcs.get(callee)
        if f is not None and f.blocks:
            return self.call(f, args)
        return self._runtime(callee, args, ins)

    def _runtime(self, name, a, ins):
        """Mô phỏng các hàm runtime C mà IR gọi tới."""
        if name == "g_str_eq":
            return _s(a[0]) == _s(a[1])
        if name == "g_str_len_i":
            return len(_s(a[0]).encode("utf-8"))
        if name == "g_str_slice":
            s = _s(a[0]).encode("utf-8")
            lo, hi = max(0, int(a[1])), min(len(s), int(a[2]))
            if hi < lo:
                hi = lo
            return s[lo:hi].decode("utf-8", "replace")
        if name == "g_print_raw":
            self.out.write(_s(a[0]))
            return None
        if name == "g_bin_str":
            v, bits = int(a[0]), int(a[1])
            if bits > 0:
                v &= (1 << bits) - 1
                return format(v, f"0{bits}b")
            return format(v & ((1 << 64) - 1) if v < 0 else v, "b")
        if name == "g_str_at_c":
            s = _s(a[0]).encode("utf-8")
            i = int(a[1])
            if not (0 <= i < len(s)):
                raise GPanic(f"chỉ số {i} vượt biên chuỗi dài {len(s)} "
                             f"tại {ins.line}:{ins.col}")
            return chr(s[i])
        if name and name.startswith("_g_enum_") and name.endswith("_name"):
            en = name[len("_g_enum_"):-len("_name")]
            for k, v in self.enums.get(en, {}).items():
                if v == self._num(a[0]):
                    return k
            return "?"
        if name and name.startswith("_g_eq_"):
            return _deep_eq(a[0], a[1])
        if name == "g_str_upper":
            return _s(a[0]).upper()
        if name == "g_str_lower":
            return _s(a[0]).lower()
        if name == "g_str_trim":
            return _s(a[0]).strip()
        if name == "g_str_concat":
            return _s(a[0]) + _s(a[1])
        if name == "g_str_dup":
            return _s(a[0])
        if name == "g_str_is_empty":
            return len(_s(a[0])) == 0
        if name == "g_str_contains":
            return _s(a[1]) in _s(a[0])
        if name == "g_str_starts_with":
            return _s(a[0]).startswith(_s(a[1]))
        if name == "g_str_ends_with":
            return _s(a[0]).endswith(_s(a[1]))
        if name == "g_str_rev":
            return _s(a[0])[::-1]
        if name == "strlen":
            return len(_s(a[0]).encode("utf-8"))
        if name == "strcmp":
            x, y = _s(a[0]), _s(a[1])
            return (x > y) - (x < y)
        if name in ("g_center", "g_fmt1"):
            raise InterpError(f"chưa mô phỏng '{name}'")
        raise InterpError(f"gọi hàm ngoài chưa mô phỏng: '{name}'")

    def do_intrinsic_alias(self, name, a, ins):
        """'g_alloc/g_realloc/g_free' — bí danh cũ, cùng ngữ nghĩa allocator."""
        if name == "g_free":
            p = a[-1]
            if isinstance(p, Ptr):
                if p.cell.freed:
                    raise GPanic("giải phóng hai lần (double free)")
                p.cell.freed = True
            return None
        n = int(self._num(a[-1]))
        c = Cell(max(0, n), "heap")
        elem = ins.type.elem if ins.type is not None else None
        for i in range(len(c.data)):
            c.data[i] = self._zero(elem)
        if name == "g_realloc" and isinstance(a[0], Ptr):
            for i in range(min(n, len(a[0].cell.data))):
                c.data[i] = a[0].cell.data[i]
        return Ptr(c, 0)

    def _bitop(self, name, a, ins):
        bits = _bits_of(ins)
        v = int(self._num(a[0])) & ((1 << bits) - 1)
        if name == "popcount":
            return bin(v).count("1")
        if name == "clz":
            return bits if v == 0 else bits - v.bit_length()
        if name == "ctz":
            return bits if v == 0 else (v & -v).bit_length() - 1
        if name == "bswap":
            nb = bits // 8
            return int.from_bytes(v.to_bytes(nb, "big"), "little")
        k = int(self._num(a[1])) % bits
        if name == "rotl":
            return ((v << k) | (v >> (bits - k))) & ((1 << bits) - 1) if k else v
        return ((v >> k) | (v << (bits - k))) & ((1 << bits) - 1) if k else v

    def do_intrinsic(self, ins, env):
        name = ins.extra.get("name")
        a = [self.val(x, env) for x in ins.args]
        if name == "makeslice":
            base, lo, hi = a[0], int(a[1]), int(a[2])
            if isinstance(base, Slice):
                base, cap = base.ptr, base.len
            else:
                cap = len(base.cell.data) - base.idx if isinstance(base, Ptr) else 0
            lo = max(0, min(lo, cap))
            hi = max(lo, min(hi, cap))
            return Slice(base + lo, hi - lo)
        if name == "len":
            v = a[0]
            return v.len if isinstance(v, Slice) else len(_s(v))
        if name == "slice_ptr":
            return a[0].ptr
        if name == "alloc":
            n = int(a[-1]) if not ins.extra.get("with_alloc") else int(a[-1])
            c = Cell(max(0, n), "heap")
            for i in range(len(c.data)):
                c.data[i] = self._zero(ins.type.elem if ins.type else None)
            return Ptr(c, 0)
        if name == "realloc":
            p, n = a[-2], int(a[-1])
            c = Cell(max(0, n), "heap")
            if isinstance(p, Ptr):
                for i in range(min(n, len(p.cell.data))):
                    c.data[i] = p.cell.data[i]
            return Ptr(c, 0)
        if name == "free":
            p = a[-1]
            if isinstance(p, Ptr):
                if p.cell.freed:
                    raise GPanic("giải phóng hai lần (double free)")
                p.cell.freed = True
            return None
        if name in ("heap_allocator", "arena_allocator"):
            return StructVal("Allocator", {"ctx": None})
        if name == "format":
            return _format(a[0], a[1:])
        if name == "print_slice":
            return _show_slice(a[0])
        if name == "str_at_checked":
            return self._runtime("g_str_at_c", a, ins)
        if name in ("g_alloc", "g_realloc", "g_free"):
            # Bí danh cũ của alloc/realloc/free.
            return self.do_intrinsic_alias(name, a, ins)
        if name in ("popcount", "clz", "ctz", "bswap", "rotl", "rotr"):
            return self._bitop(name, a, ins)
        if name in ("min", "max", "abs", "clamp"):
            n = [self._num(x) for x in a]
            if name == "abs":
                return abs(n[0])
            if name == "min":
                return min(n[0], n[1])
            if name == "max":
                return max(n[0], n[1])
            return max(n[1], min(n[0], n[2]))
        if name in ("sizeof", "alignof"):
            raise InterpError(f"'{name}' chưa gấp được thành hằng")
        if name in ("memcpy", "memmove", "memset", "memcmp"):
            raise InterpError(f"chưa mô phỏng '{name}'")
        raise InterpError(f"intrinsic chưa mô phỏng: '{name}'")


def _bits_of(ins):
    return int(ins.extra.get("bits", 32) or 32)


class _FieldPtr(Ptr):
    """Con trỏ tới một TRƯỜNG của struct (đọc/ghi xuyên vào struct gốc)."""
    __slots__ = ("sv", "field", "cell", "idx")

    def __init__(self, sv, field):
        self.sv = sv
        self.field = field
        # Ô giả để các đường dùng chung (.cell/.idx) không phải đặc biệt hoá.
        self.cell = Cell(0, "field")
        self.idx = 0

    def load(self):
        return self.sv.fields.get(self.field)

    def store(self, v):
        self.sv.fields[self.field] = v

    def check(self, what="truy cập"):
        return

    def __add__(self, k):
        if int(k) == 0:
            return self
        raise GPanic("cộng con trỏ trên trường struct")

    def __repr__(self):
        return f"FieldPtr({self.field})"


def _deep_copy(v):
    """Sao chép SÂU một giá trị (struct/mảng lồng) — ngữ nghĩa giá trị của G."""
    if isinstance(v, StructVal):
        return v.copy()
    if isinstance(v, Ptr) and not isinstance(v, _FieldPtr):
        c = Cell(len(v.cell.data), v.cell.note)
        for i, x in enumerate(v.cell.data):
            c.data[i] = _deep_copy(x)
        return Ptr(c, v.idx)
    return v


def _s(v):
    return "" if v is None else (v if isinstance(v, str) else str(v))


def _deep_eq(a, b):
    if isinstance(a, StructVal) and isinstance(b, StructVal):
        return all(_deep_eq(a.fields.get(k), b.fields.get(k))
                   for k in a.fields)
    return a == b


def _show_slice(sl, cap=8):
    if not isinstance(sl, Slice):
        return "[]"
    out = []
    for i in range(min(sl.len, cap)):
        out.append(_fmt_one(sl.ptr.cell.data[sl.ptr.idx + i]))
    tail = f", ... ({sl.len} phần tử)" if sl.len > cap else ""
    return "[" + ", ".join(out) + tail + "]"


def _fmt_one(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return _fmt_g(v)
    return _s(v)


def _fmt_g(x):
    """Bắt chước '%g' của C (mặc định 6 chữ số có nghĩa)."""
    r = f"{x:.6g}"
    return r


def _format(fmt, args):
    """Thực thi một chuỗi định dạng printf mà irgen đã dựng."""
    out = []
    ai = 0
    i = 0
    f = _s(fmt)
    n = len(f)
    while i < n:
        ch = f[i]
        if ch != "%":
            out.append(ch)
            i += 1
            continue
        if i + 1 < n and f[i + 1] == "%":
            out.append("%")
            i += 2
            continue
        j = i + 1
        while j < n and f[j] not in "diouxXeEfgGcsp":
            j += 1
        if j >= n:
            out.append(f[i:])
            break
        spec = f[i:j + 1]
        conv = f[j]
        v = args[ai] if ai < len(args) else 0
        ai += 1
        out.append(_apply_spec(spec, conv, v))
        i = j + 1
    return "".join(out)


def _apply_spec(spec, conv, v):
    body = spec[1:-1].replace("ll", "").replace("l", "").replace("z", "")
    if conv == "s":
        s = _s(v)
        return f"%{body}s" % s if body else s
    if conv == "c":
        c = v if isinstance(v, str) else chr(int(v) & 0xFF)
        return f"%{body}c" % c if body else c
    if conv == "p":
        return "0x0" if v is None else "0x1"
    num = v
    if isinstance(num, bool):
        num = int(num)
    if isinstance(num, str) and len(num) == 1:
        num = ord(num)
    if conv in "dioxXu":
        num = int(num or 0)
        if conv == "u" and num < 0:
            num += 1 << 64
        pyc = {"d": "d", "i": "d", "o": "o", "x": "x", "X": "X", "u": "d"}[conv]
        return f"%{body}{pyc}" % num
    num = float(num or 0)
    return f"%{body}{conv}" % num


def run(mod: I.Module, out=None, err=None, entry="main"):
    return Interp(mod, out, err).run(entry)
