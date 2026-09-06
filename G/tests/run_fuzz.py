#!/usr/bin/env python3
"""
Fuzz đường ống trình biên dịch G: lexer → parser → checker → IR.

YÊU CẦU ĐƯỢC KIỂM
=================
Với BẤT KỲ đầu vào nào (kể cả rác), trình biên dịch phải:

  * báo lỗi có kiểm soát (LexError/ParseError/CheckError/GError), HOẶC
  * biên dịch thành công và IR sinh ra phải qua verifier;

và TUYỆT ĐỐI KHÔNG được:

  * ném exception Python không mong đợi (AttributeError, IndexError, KeyError,
    TypeError, RecursionError, ...) — đó là crash trình biên dịch;
  * treo vô hạn.

Sinh đầu vào theo hai hướng:
  1. ĐỘT BIẾN (mutation) từ ví dụ/ca test thật — tìm lỗi ở vùng mã sâu;
  2. NGẪU NHIÊN có cấu trúc từ token của G — tìm lỗi ở parser.

    python3 tests/run_fuzz.py            # 400 vòng, hạt giống ngẫu nhiên
    python3 tests/run_fuzz.py -n 5000    # chạy lâu hơn
    python3 tests/run_fuzz.py --seed 42  # tái lập
"""

import argparse
import os
import random
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from compiler.lexer import Lexer, LexError            # noqa: E402
from compiler.parser import Parser, ParseError        # noqa: E402
from compiler.checker import Checker, CheckError, CheckErrors  # noqa: E402
from compiler import irgen, irverify                  # noqa: E402
from compiler import target as _tgt                   # noqa: E402
from compiler.irgen import IRGenError                 # noqa: E402

#: Lỗi HỢP LỆ — trình biên dịch từ chối đầu vào một cách có kiểm soát.
EXPECTED = (LexError, ParseError, CheckError, CheckErrors, IRGenError,
            RecursionError)

TOKENS = [
    "fn", "let", "mut", "const", "return", "if", "else", "while", "loop",
    "for", "in", "match", "struct", "enum", "impl", "defer", "break",
    "continue", "as", "true", "false", "null", "sizeof", "import", "extern",
    "comptime", "asm", "step",
    "{", "}", "(", ")", "[", "]", ",", ";", ":", "::", ".", "..", "..=",
    "->", "=>", "=", "==", "!=", "<", ">", "<=", ">=", "+", "-", "*", "/",
    "%", "&", "|", "^", "~", "!", "&&", "||", "<<", ">>", "+=", "-=", "?",
    "main", "x", "y", "foo", "T", "P", "int", "i64", "u8", "f64", "bool",
    "str", "char", "void", "slice", "len", "<", ">",
    "alloc", "free", "realloc", "alloc_in", "free_in",
    "arena_allocator", "heap_allocator", "Allocator",
    "0", "1", "42", "0xFF", "0b101", "1.5", '"s"', "'c'", "{}", '"{}"',
]


def corpus():
    out = []
    for d in ("examples", "tests/cases", "tests/fail", "tests/freestanding"):
        p = os.path.join(ROOT, d)
        if not os.path.isdir(p):
            continue
        for fn in sorted(os.listdir(p)):
            if fn.endswith(".g"):
                try:
                    with open(os.path.join(p, fn), encoding="utf-8") as f:
                        out.append(f.read())
                except OSError:
                    pass
    return out


def mutate(src, rng):
    """Đột biến một nguồn hợp lệ theo cách thô bạo nhưng hay lộ bug."""
    if not src:
        return src
    kind = rng.randrange(9)
    n = len(src)
    if kind == 0:                                   # cắt đuôi (EOF đột ngột)
        return src[:rng.randrange(1, n)]
    if kind == 1:                                   # xoá một đoạn
        i = rng.randrange(n)
        j = min(n, i + rng.randrange(1, 40))
        return src[:i] + src[j:]
    if kind == 2:                                   # chèn token ngẫu nhiên
        i = rng.randrange(n)
        return src[:i] + " " + rng.choice(TOKENS) + " " + src[i:]
    if kind == 3:                                   # đổi một ký tự
        i = rng.randrange(n)
        return src[:i] + rng.choice("{}()[]<>;:,.*&|!=+-/%\"'") + src[i + 1:]
    if kind == 4:                                   # nhân đôi một dòng
        lines = src.splitlines()
        if not lines:
            return src
        i = rng.randrange(len(lines))
        lines.insert(i, lines[i])
        return "\n".join(lines)
    if kind == 5:                                   # xoá mọi dấu đóng
        return src.replace(rng.choice(["}", ")", "]", '"']), "", 1)
    if kind == 6:                                   # lồng sâu (bắt đệ quy vô hạn)
        depth = rng.randrange(50, 400)
        return "fn main() -> int { return " + "(" * depth + "1" + ")" * depth + " }"
    if kind == 7:                                   # chèn đoạn dùng slice
        frag = rng.choice([
            "fn _f(xs: slice<int>) -> int { return xs[0] }",
            "fn _g(xs: mut slice<int>) { xs[0] = 1 }",
            "fn _h() -> int { let a: [3]int = [1,2,3] return len(a[0..2]) }",
            "fn _i(xs: slice<slice<int>>) -> int { return 0 }",
            "fn _j() -> int { let a: [2]int = [1,2] let s = a[..] return s[9] }",
            "fn _k() -> int { let p = alloc(int, 4) free(p) return 0 }",
            "fn _l() -> int { let mut b: [64]u8 = [0; 64] "
            "let a = arena_allocator(b) let p = alloc_in(a, int, 2) return p[0] }",
            "fn _m(a: Allocator) -> *int { return alloc_in(a, int, 1) }",
        ])
        return src + "\n" + frag + "\n"
    lines = src.splitlines()                        # trộn thứ tự dòng
    rng.shuffle(lines)
    return "\n".join(lines)


def random_src(rng):
    n = rng.randrange(1, 60)
    return " ".join(rng.choice(TOKENS) for _ in range(n))


def run_one(src, freestanding=False, target=None):
    """Chạy hết đường ống. Trả về (ok, mô_tả_sự_cố_hoặc_None)."""
    try:
        toks = Lexer(src, "<fuzz>").tokenize()
        prog = Parser(toks, "<fuzz>").parse()
        Checker(prog, freestanding=freestanding, target=target).check()
        mod = irgen.IRGen(prog).generate()
        errs = irverify.verify(mod)
        if errs:
            return False, "IR không hợp lệ: " + str(errs[0])
        return True, None
    except EXPECTED:
        return True, None                    # từ chối có kiểm soát — hợp lệ
    except SystemExit:
        return False, "gọi sys.exit() giữa đường ống"
    except Exception:                        # noqa: BLE001 — chính là thứ cần bắt
        return False, traceback.format_exc(limit=6)


def main():
    ap = argparse.ArgumentParser(description="Fuzz trình biên dịch G")
    ap.add_argument("-n", "--iterations", type=int, default=400)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    seed = args.seed if args.seed is not None else random.randrange(1 << 30)
    rng = random.Random(seed)
    base = corpus()
    if not base:
        print("fuzz: không tìm thấy corpus", file=sys.stderr)
        return 1

    sys.setrecursionlimit(6000)
    crashes = []
    for k in range(args.iterations):
        if rng.random() < 0.75:
            src = mutate(rng.choice(base), rng)
        else:
            src = random_src(rng)
        # Xoay vòng qua các target để lớp năng lực cũng bị fuzz.
        tg = _tgt.TARGETS[rng.choice(_tgt.available())]
        ok, why = run_one(src, freestanding=(rng.random() < 0.15), target=tg)
        if not ok:
            crashes.append((src, why))
            if len(crashes) >= 5:
                break
        if not args.quiet and (k + 1) % 100 == 0:
            print(f"  ... {k + 1}/{args.iterations}", file=sys.stderr)

    print("-------------------------")
    if crashes:
        print(f"fuzz: \033[1;31m{len(crashes)} CRASH\033[0m (seed={seed})")
        for src, why in crashes[:3]:
            print("=" * 60)
            print("--- nguồn gây crash ---")
            print(src[:600])
            print("--- lỗi ---")
            print(why)
        return 1
    print(f"fuzz: \033[32m{args.iterations} vòng, 0 crash\033[0m (seed={seed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
