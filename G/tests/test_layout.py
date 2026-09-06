#!/usr/bin/env python3
"""
Đối chiếu bố cục do G tự tính (`compiler/layout.py`) với bố cục THẬT do trình
biên dịch C tính.

Vì sao phải đối chiếu: `layout.py` là "nguồn chân lý thứ hai". Nó tồn tại để
backend tương lai (LLVM/WASM) và `static_assert` không phải nhờ C. Nhưng một
nguồn chân lý thứ hai chỉ có giá trị nếu nó KHỚP nguồn thứ nhất — nếu không, nó
tệ hơn là không có.

Cách kiểm: sinh một chương trình C in ra `sizeof`/`_Alignof`/`offsetof` của từng
struct, biên dịch & chạy, rồi so với con số G tính. Bất kỳ sai lệch nào là lỗi.

    python3 tests/test_layout.py
"""

import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from compiler.lexer import Lexer                      # noqa: E402
from compiler.parser import Parser                    # noqa: E402
from compiler.checker import Checker                  # noqa: E402
from compiler.codegen import Codegen                  # noqa: E402
from compiler import layout as L                      # noqa: E402
from compiler import target as TG                     # noqa: E402
from compiler import types as T                       # noqa: E402

RUNTIME = os.path.join(ROOT, "runtime")


def build(src, target=None):
    toks = Lexer(src, "<layout>").tokenize()
    prog = Parser(toks, "<layout>").parse()
    ck = Checker(prog, target=target)
    ck.check()
    return prog, ck


def c_layout(src, struct_names):
    """Bố cục THẬT theo trình biên dịch C: {tên: (size, align, {trường: off})}."""
    prog, ck = build(src)
    c_code = Codegen(prog).generate()
    lines = []
    for sname in struct_names:
        fields = ck.struct_order[sname]
        lines.append(f'    printf("%s %zu %zu", "{sname}", '
                     f'sizeof({sname}), _Alignof({sname}));')
        for f in fields:
            lines.append(f'    printf(" %s=%zu", "{f}", '
                         f'(size_t)offsetof({sname}, {f}));')
        lines.append('    printf("\\n");')
    probe = (c_code
             + "\n#include <stddef.h>\n"
             + "int _layout_probe(void) {\n" + "\n".join(lines)
             + "\n    return 0;\n}\n")
    # thay main của người dùng bằng probe
    probe = probe.replace("int main(void) {", "int _unused_main(void) {", 1)
    probe += "\nint main(void) { return _layout_probe(); }\n"

    with tempfile.TemporaryDirectory() as d:
        cf = os.path.join(d, "p.c")
        exe = os.path.join(d, "p")
        with open(cf, "w", encoding="utf-8") as f:
            f.write(probe)
        r = subprocess.run(["cc", "-std=gnu11", "-I", RUNTIME, "-w",
                            cf, "-o", exe, "-lm"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise AssertionError("không biên dịch được probe C:\n" + r.stderr)
        out = subprocess.run([exe], capture_output=True, text=True).stdout

    res = {}
    for line in out.strip().splitlines():
        parts = line.split()
        name, size, align = parts[0], int(parts[1]), int(parts[2])
        offs = {}
        for p in parts[3:]:
            k, v = p.split("=")
            offs[k] = int(v)
        res[name] = (size, align, offs)
    return res


def g_layout(src, target=None):
    _, ck = build(src, target)
    lay = L.from_checker(ck)
    return ck, lay


class TestAgainstC(unittest.TestCase):
    """Số G tính phải KHỚP số C tính, trên chính máy này."""

    def _check(self, src, names):
        want = c_layout(src, names)
        _, lay = g_layout(src)
        for n in names:
            wsz, wal, woff = want[n]
            self.assertEqual(lay.size_of(T.GType("struct", name=n)), wsz,
                             f"sizeof({n})")
            self.assertEqual(lay.align_of(T.GType("struct", name=n)), wal,
                             f"alignof({n})")
            got = {f: o for f, o, _ in lay.offsets_of(n)}
            self.assertEqual(got, woff, f"offset trong {n}")

    def test_scalars_and_padding(self):
        self._check("""
            struct A { a: u8, b: u32 }
            struct B { a: u8, b: u8, c: u16 }
            struct C { a: u64, b: u8 }
            struct D { a: f32, b: f64, c: u8 }
            struct E { a: bool, b: char, c: i16, d: i64 }
            fn main() -> int { return 0 }
        """, ["A", "B", "C", "D", "E"])

    def test_nested_and_arrays(self):
        self._check("""
            struct Inner { x: u16, y: u8 }
            struct Outer { a: u8, i: Inner, b: u32 }
            struct Arr { a: u8, xs: [3]u32, b: u8 }
            struct Multi { m: [2][3]u16 }
            fn main() -> int { return 0 }
        """, ["Inner", "Outer", "Arr", "Multi"])

    def test_pointers_and_str(self):
        self._check("""
            struct P { a: u8, p: *u32, b: u8 }
            struct S { s: str, n: usize }
            struct FP { f: fn(int) -> int, a: u8 }
            fn main() -> int { return 0 }
        """, ["P", "S", "FP"])

    def test_packed_and_aligned(self):
        self._check("""
            @packed struct Pk { a: u8, b: u32, c: u16 }
            @align(16) struct Al { a: u8, b: u32 }
            @packed struct Hdr { magic: u16, len: u32, flags: u8 }
            fn main() -> int { return 0 }
        """, ["Pk", "Al", "Hdr"])

    def test_enum_field(self):
        self._check("""
            enum Color { Red, Green, Blue }
            struct WithEnum { a: u8, c: Color, b: u8 }
            fn main() -> int { return 0 }
        """, ["WithEnum"])

    def test_slice_field(self):
        self._check("""
            struct WithSlice { a: u8, s: slice<int> }
            fn main() -> int { return 0 }
        """, ["WithSlice"])


class TestTargetDependent(unittest.TestCase):
    """Bố cục phải ĐỔI theo bề rộng con trỏ của target."""

    SRC = """
        struct P { p: *u32, n: usize }
        struct S { s: slice<int> }
        fn main() -> int { return 0 }
    """

    def test_64bit(self):
        _, lay = g_layout(self.SRC, TG.TARGETS["x86_64-linux"])
        self.assertEqual(lay.size_of(T.GType("struct", name="P")), 16)
        self.assertEqual(lay.size_of(T.GType("struct", name="S")), 16)

    def test_32bit(self):
        _, lay = g_layout(self.SRC, TG.TARGETS["wasm32"])
        # con trỏ 4 byte + usize 4 byte -> 8; slice = 2 từ máy -> 8
        self.assertEqual(lay.size_of(T.GType("struct", name="P")), 8)
        self.assertEqual(lay.size_of(T.GType("struct", name="S")), 8)

    def test_usize_width_follows_target(self):
        _, ck64 = build("fn main() -> int { return 0 }",
                        TG.TARGETS["x86_64-linux"])
        _, ck32 = build("fn main() -> int { return 0 }", TG.TARGETS["wasm32"])
        self.assertEqual(ck64.primitives["usize"].bits, 64)
        self.assertEqual(ck32.primitives["usize"].bits, 32)
        self.assertEqual(ck64.int_bounds["usize"][1], (1 << 64) - 1)
        self.assertEqual(ck32.int_bounds["usize"][1], (1 << 32) - 1)


class TestErrors(unittest.TestCase):
    def test_recursive_struct_by_value(self):
        lay = L.Layout(TG.TARGETS["x86_64-linux"],
                       {"N": [("v", T.I32), ("next", T.GType("struct", name="N"))]})
        with self.assertRaises(L.LayoutError):
            lay.size_of(T.GType("struct", name="N"))

    def test_unknown_struct(self):
        lay = L.Layout(TG.TARGETS["x86_64-linux"], {})
        with self.assertRaises(L.LayoutError):
            lay.size_of(T.GType("struct", name="Nope"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
