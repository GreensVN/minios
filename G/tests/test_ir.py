#!/usr/bin/env python3
"""
Unit test cho G-IR: kiểm NGỮ NGHĨA của việc hạ mã, không chỉ tính hợp lệ.

`run_ir.sh` trả lời "IR có đúng cấu trúc không". File này trả lời câu khó hơn:
"IR có nói đúng điều ta muốn nói không" — ví dụ defer có thật sự chạy SAU khi
chốt giá trị trả về, match hằng có thành switch không, mảng có memcpy không.

Đây là những bất biến từng bị vi phạm trong C backend và chỉ lộ ra khi chương
trình chạy sai. Ở tầng IR chúng kiểm được tĩnh.

    python3 tests/test_ir.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.lexer import Lexer                      # noqa: E402
from compiler.parser import Parser                    # noqa: E402
from compiler.checker import Checker                  # noqa: E402
from compiler import irgen, irverify                  # noqa: E402
from compiler import ir as I                          # noqa: E402


def build(src, freestanding=False):
    """nguồn G -> ir.Module (đi qua lexer/parser/checker thật)."""
    toks = Lexer(src, "<test>").tokenize()
    prog = Parser(toks, "<test>").parse()
    Checker(prog, freestanding=freestanding).check()
    return irgen.IRGen(prog).generate()


def ops_of(fn):
    return [i.op for b in fn.blocks for i in b.instrs]


def terms_of(fn):
    return [b.term.op for b in fn.blocks if b.term is not None]


def instrs_of(fn):
    return [i for b in fn.blocks for i in b.instrs]


class TestValid(unittest.TestCase):
    """Mọi thứ hạ ra phải qua verifier."""

    def assertValid(self, mod):
        errs = irverify.verify(mod)
        self.assertEqual(errs, [], "\n".join(str(e) for e in errs))

    def test_empty_main(self):
        self.assertValid(build("fn main() -> int { return 0 }"))

    def test_all_control_flow(self):
        mod = build("""
            enum E { A, B, C }
            struct P { x: int, y: int }
            fn f(n: int) -> int {
                let mut t = 0
                if n > 0 { t += 1 } else { t -= 1 }
                while t < 3 { t += 1 }
                loop { t += 1 if t > 5 { break } }
                for i in 0..3 { t += i }
                for i in 0..=3 step 2 { t += i }
                let a: [3]int = [1, 2, 3]
                for x in a { t += x }
                match n { 0 => t = 0  1..=5 => t = 1  _ => t = 2 }
                let e = B
                match e { A => t += 1  B => t += 2  C => t += 3 }
                let p = P{x: 1, y: 2}
                t += p.x + p.y
                return t
            }
            fn main() -> int { return f(2) }
        """)
        self.assertValid(mod)

    def test_freestanding_kernel_shape(self):
        mod = build("""
            fn hang() { cli() loop { halt() } }
            fn kmain() { outb(0x20, 0x20) hang() }
        """, freestanding=True)
        self.assertValid(mod)


class TestDeferSemantics(unittest.TestCase):
    """Defer là nơi ngữ nghĩa dễ sai nhất — kiểm kỹ."""

    def test_return_value_snapshot_before_defer(self):
        """'defer n = 999; return n + 1' phải CHỐT giá trị trước khi chạy defer.

        Trong IR: lệnh cuối trước 'ret' phải là store của defer, và toán hạng
        của 'ret' phải được tính TRƯỚC store đó.
        """
        mod = build("""
            let mut n: int = 0
            fn f() -> int { defer n = 999 return n + 1 }
            fn main() -> int { return f() }
        """)
        self.assertEqual(irverify.verify(mod), [])
        f = mod.func("f")
        blk = [b for b in f.blocks if b.term and b.term.op == "ret"][0]
        ret_val = blk.term.args[0]
        idx_def = {i.dst.name: k for k, i in enumerate(blk.instrs)
                   if i.dst is not None}
        # giá trị trả về phải được định nghĩa trong block này
        self.assertIn(ret_val.name, idx_def)
        # ... và store của defer (@n) phải nằm SAU khi nó được tính
        stores = [k for k, i in enumerate(blk.instrs)
                  if i.op == "store" and i.args[0].kind == "global"
                  and i.args[0].name == "n"]
        self.assertTrue(stores, "không thấy store vào global n (defer)")
        self.assertLess(idx_def[ret_val.name], stores[0],
                        "defer chạy TRƯỚC khi chốt giá trị trả về")

    def test_defer_lifo(self):
        """Nhiều defer chạy theo thứ tự ngược (LIFO)."""
        mod = build("""
            fn f() { defer println("1") defer println("2") println("body") }
            fn main() -> int { f() return 0 }
        """)
        self.assertEqual(irverify.verify(mod), [])
        names = [i.extra.get("arg0") or (i.args[0].const if i.args else None)
                 for i in instrs_of(mod.func("f")) if i.op == "intrinsic"]
        self.assertEqual(names, ["body", "2", "1"])

    def test_defer_runs_on_every_exit(self):
        """Defer phải được nhân bản ở MỌI điểm thoát, không chỉ điểm cuối."""
        mod = build("""
            fn f(n: int) -> int {
                defer println("d")
                if n > 0 { return 1 }
                return 2
            }
            fn main() -> int { return f(1) }
        """)
        self.assertEqual(irverify.verify(mod), [])
        f = mod.func("f")
        n_ret = sum(1 for b in f.blocks if b.term and b.term.op == "ret")
        n_defer = sum(1 for i in instrs_of(f)
                      if i.op == "intrinsic" and i.extra.get("name") == "println")
        self.assertEqual(n_ret, 2)
        self.assertEqual(n_defer, 2, "defer không được nhân bản ở mọi lối ra")

    def test_defer_flushed_on_break(self):
        mod = build("""
            fn f() -> int {
                let mut n = 0
                loop { defer n += 1  if n >= 0 { break } }
                return n
            }
            fn main() -> int { return f() }
        """)
        self.assertEqual(irverify.verify(mod), [])


class TestLoweringChoices(unittest.TestCase):
    """Các quyết định hạ mã cụ thể phải nhìn thấy được trong IR."""

    def test_const_match_becomes_switch(self):
        mod = build("""
            fn f(n: int) -> int {
                match n { 0 => return 1  1 => return 2  _ => return 3 }
            }
            fn main() -> int { return f(0) }
        """)
        self.assertEqual(irverify.verify(mod), [])
        self.assertIn("switch", terms_of(mod.func("f")))

    def test_guarded_match_uses_branches(self):
        """Có guard thì KHÔNG dùng switch được (guard phải chạy lúc chạy)."""
        mod = build("""
            fn f(n: int) -> int {
                match n { 0 if n > 5 => return 1  _ => return 3 }
            }
            fn main() -> int { return f(0) }
        """)
        self.assertEqual(irverify.verify(mod), [])
        t = terms_of(mod.func("f"))
        self.assertNotIn("switch", t)
        self.assertIn("branch", t)

    def test_array_copy_uses_memcpy(self):
        """'let b = a' trên mảng phải SAO CHÉP (memcpy), không chia sẻ con trỏ."""
        mod = build("""
            fn main() -> int {
                let a: [3]int = [1, 2, 3]
                let b = a
                return b[0]
            }
        """)
        self.assertEqual(irverify.verify(mod), [])
        self.assertIn("memcpy", ops_of(mod.func("main")))

    def test_bounds_check_emitted(self):
        """Chỉ số mảng tĩnh sinh lệnh 'check' kind=bounds."""
        mod = build("""
            fn main() -> int {
                let a: [3]int = [1, 2, 3]
                let i = 1
                return a[i]
            }
        """)
        checks = [i for i in instrs_of(mod.func("main"))
                  if i.op == "check" and i.extra.get("kind") == "bounds"]
        self.assertTrue(checks, "thiếu kiểm biên mảng trong IR")

    def test_div_zero_check_emitted(self):
        mod = build("""
            fn f(a: int, b: int) -> int { return a / b }
            fn main() -> int { return f(6, 3) }
        """)
        checks = [i for i in instrs_of(mod.func("f"))
                  if i.op == "check" and i.extra.get("kind") == "divzero"]
        self.assertTrue(checks, "thiếu kiểm chia 0 trong IR")

    def test_short_circuit_is_real_branch(self):
        """'&&' phải đoản mạch thật (rẽ nhánh), không tính cả hai vế."""
        mod = build("""
            fn side() -> bool { println("x") return true }
            fn main() -> int {
                let b = false && side()
                return 0
            }
        """)
        self.assertEqual(irverify.verify(mod), [])
        self.assertIn("branch", terms_of(mod.func("main")))

    def test_for_mut_writes_through_element_address(self):
        """'for mut x in a' ghi thẳng vào phần tử, không sửa bản sao."""
        mod = build("""
            fn main() -> int {
                let mut a: [3]int = [1, 2, 3]
                for mut x in a { x += 1 }
                return a[0]
            }
        """)
        self.assertEqual(irverify.verify(mod), [])
        f = mod.func("main")
        self.assertIn("elemaddr", ops_of(f))
        # biến lặp KHÔNG được cấp alloca riêng (đó mới là bản sao)
        allocas = [i for i in instrs_of(f)
                   if i.op == "alloca" and i.extra.get("name") == "x"]
        self.assertEqual(allocas, [], "'for mut x' tạo bản sao thay vì ghi xuyên")

    def test_infinite_loop_has_no_exit_block(self):
        """'loop { }' không break: không được tạo block thoát chết."""
        mod = build("""
            fn hang() { loop { halt() } }
            fn kmain() { hang() }
        """, freestanding=True)
        self.assertEqual(irverify.verify(mod), [])
        labels = [b.label for b in mod.func("hang").blocks]
        self.assertFalse([l for l in labels if l.startswith("lend")],
                         "vòng lặp vô hạn vẫn sinh block thoát")


class TestSlices(unittest.TestCase):
    """slice<T> phải mang theo độ dài xuống tận IR."""

    def test_array_to_slice_is_explicit(self):
        """Chuyển ngầm mảng->slice phải HIỆN trong IR (makeslice), không ẩn."""
        mod = build("""
            fn f(xs: slice<int>) -> int { return xs[0] }
            fn main() -> int {
                let a: [3]int = [1, 2, 3]
                return f(a)
            }
        """)
        self.assertEqual(irverify.verify(mod), [])
        names = [i.extra.get("name") for i in instrs_of(mod.func("main"))
                 if i.op == "intrinsic"]
        self.assertIn("makeslice", names)

    def test_slice_expr_lowers_to_makeslice(self):
        mod = build("""
            fn f(xs: slice<int>) -> int { return xs[0] }
            fn main() -> int {
                let a: [4]int = [1, 2, 3, 4]
                return f(a[1..3])
            }
        """)
        self.assertEqual(irverify.verify(mod), [])
        names = [i.extra.get("name") for i in instrs_of(mod.func("main"))
                 if i.op == "intrinsic"]
        self.assertIn("makeslice", names)

    def test_mut_slice_type_carries_mutability(self):
        mod = build("""
            fn fill(xs: mut slice<int>) { xs[0] = 1 }
            fn main() -> int {
                let mut a: [2]int = [0, 0]
                fill(a)
                return a[0]
            }
        """)
        self.assertEqual(irverify.verify(mod), [])
        p = mod.func("fill").params[0]
        self.assertEqual(p.type.kind, "slice")
        self.assertTrue(p.type.mutable_slice)

    def test_slice_works_freestanding(self):
        mod = build("""
            fn sum(xs: slice<u32>) -> u32 {
                let mut s: u32 = 0
                for i in 0..len(xs) { s += xs[i] }
                return s
            }
            fn kmain() {
                let regs: [2]u32 = [1, 2]
                outb(0x80, sum(regs) as u8)
            }
        """, freestanding=True)
        self.assertEqual(irverify.verify(mod), [])


class TestVerifierCatchesBugs(unittest.TestCase):
    """Verifier phải THẬT SỰ bắt lỗi — nếu không nó chỉ là trang trí."""

    def _mod_with(self, blocks, ret=None):
        f = I.Func("bad", [], ret, blocks=blocks)
        m = I.Module()
        m.funcs.append(f)
        return m

    def test_missing_terminator(self):
        b = I.Block("entry", instrs=[], term=None)
        errs = irverify.verify(self._mod_with([b]))
        self.assertTrue(any("terminator" in e.msg for e in errs))

    def test_jump_to_unknown_label(self):
        b = I.Block("entry", term=I.Term("jump", labels=["nope"]))
        errs = irverify.verify(self._mod_with([b]))
        self.assertTrue(any("không tồn tại" in e.msg for e in errs))

    def test_use_before_def(self):
        t = I.temp("x", None)
        b = I.Block("entry",
                    instrs=[I.Instr("neg", dst=I.temp("y", None),
                                    args=[t], type=None)],
                    term=I.Term("ret"))
        errs = irverify.verify(self._mod_with([b]))
        self.assertTrue(any("trước khi định nghĩa" in e.msg for e in errs))

    def test_redefined_temp(self):
        d = I.temp("x", None)
        from compiler import types as T
        b = I.Block("entry", instrs=[
            I.Instr("alloca", dst=d, type=T.GType("ptr")),
            I.Instr("alloca", dst=d, type=T.GType("ptr")),
        ], term=I.Term("ret"))
        errs = irverify.verify(self._mod_with([b]))
        self.assertTrue(any("định nghĩa lại" in e.msg for e in errs))

    def test_unreachable_block(self):
        b1 = I.Block("entry", term=I.Term("ret"))
        b2 = I.Block("orphan", term=I.Term("ret"))
        errs = irverify.verify(self._mod_with([b1, b2]))
        self.assertTrue(any("không thể tới" in e.msg for e in errs))

    def test_bad_op_rejected(self):
        b = I.Block("entry",
                    instrs=[I.Instr("frobnicate", args=[])],
                    term=I.Term("ret"))
        errs = irverify.verify(self._mod_with([b]))
        self.assertTrue(any("op không hợp lệ" in e.msg for e in errs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
