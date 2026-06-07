"""
G Language - Driver: điều phối toàn bộ pipeline biên dịch.
  nguồn .g  ->  Lexer  ->  Parser  ->  (gộp module)  ->  Checker  ->  Codegen  ->  cc
"""

import os
import sys
import shutil
import subprocess
import tempfile

from .lexer import Lexer, LexError
from .parser import Parser, ParseError
from .checker import Checker, CheckError
from .codegen import Codegen, CodegenError
from . import ast_nodes as A

VERSION = "0.2.0"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUNTIME_DIR = os.path.join(ROOT, "runtime")
LIB_DIR = os.path.join(ROOT, "lib")


class GError(Exception):
    """Lỗi biên dịch có thông tin vị trí + file nguồn để chẩn đoán."""
    def __init__(self, filename, source, line, col, msg, phase):
        self.filename = filename
        self.source = source
        self.line = line
        self.col = col
        self.msg = msg
        self.phase = phase


# ---------- chẩn đoán lỗi đẹp ----------
def render_diag(filename, source, line, col, msg, phase):
    RED = "\033[1;31m"; BOLD = "\033[1m"; CYAN = "\033[36m"; RST = "\033[0m"
    head = f"{BOLD}{filename}:{line}:{col}:{RST} {RED}lỗi {phase}:{RST} {msg}"
    lines = (source or "").splitlines()
    body = ""
    if 1 <= line <= len(lines):
        src = lines[line - 1].replace("\t", " ")
        gutter = f"{line:>5}"
        body = (f"\n {CYAN}{gutter} |{RST} {src}"
                f"\n {CYAN}      |{RST} {' ' * max(0, col - 1)}{RED}^{RST}")
    return head + body


# ---------- nạp module (import) ----------
def resolve_import(imp, current_file, sources):
    cur_dir = os.path.dirname(os.path.abspath(current_file))
    candidates = []
    if imp.endswith(".g") or "/" in imp:
        candidates.append(os.path.join(cur_dir, imp))
    else:
        candidates.append(os.path.join(cur_dir, imp + ".g"))
        candidates.append(os.path.join(LIB_DIR, imp + ".g"))
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def parse_file(path, sources):
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    sources[os.path.abspath(path)] = (path, src)
    try:
        tokens = Lexer(src, path).tokenize()
    except LexError as e:
        raise GError(path, src, e.line, e.col, e.msg, "từ vựng")
    try:
        prog = Parser(tokens, path).parse()
    except ParseError as e:
        raise GError(path, src, e.line, e.col, e.msg, "cú pháp")
    return prog, tokens


def load_program(path, sources, visited):
    ap = os.path.abspath(path)
    if ap in visited:
        return []
    visited.add(ap)
    prog, _ = parse_file(path, sources)
    items = []
    for imp in prog.imports:
        ipath = resolve_import(imp, path, sources)
        if ipath is None:
            raise GError(path, sources[ap][1], 1, 1,
                         f"không tìm thấy module để import: '{imp}'", "module")
        items.extend(load_program(ipath, sources, visited))
    # Gắn file nguồn vào từng khai báo để chẩn đoán đa module đúng file/dòng.
    for it in prog.items:
        try:
            it.src_file = ap
        except Exception:
            pass
    items.extend(prog.items)
    return items


def build_program(main_path, sources):
    items = load_program(main_path, sources, set())
    return A.Program(items=items, imports=[])


# ---------- pipeline ----------
def has_main(prog):
    return any(isinstance(it, A.Function) and it.name == "main" and it.body is not None
               for it in prog.items)


def compile_to_c(main_path):
    """Trả về dict {c, has_main}. Báo lỗi đúng file nguồn (kể cả module import)."""
    sources = {}
    main_ap = os.path.abspath(main_path)
    prog = build_program(main_path, sources)
    main_src = sources[main_ap][1]
    try:
        Checker(prog).check()
    except CheckError as e:
        fpath, fsrc = sources.get(e.file or main_ap, (main_path, main_src))
        raise GError(fpath, fsrc, e.line, e.col, e.msg, "kiểu/ngữ nghĩa")
    try:
        c_code = Codegen(prog).generate()
    except CodegenError as e:
        raise GError(main_path, main_src, 0, 0, str(e), "sinh mã")
    return {"c": c_code, "has_main": has_main(prog)}


def dump_tokens(main_path):
    sources = {}
    _, tokens = parse_file(main_path, sources)
    for t in tokens:
        print(f"  {t.line:>4}:{t.col:<3} {t.kind:<6} {t.value!r}")


def dump_ast(main_path):
    sources = {}
    prog = build_program(main_path, sources)
    import pprint
    for it in prog.items:
        print(pprint_node(it))


def pprint_node(node, depth=0):
    import dataclasses
    pad = "  " * depth
    if dataclasses.is_dataclass(node):
        name = type(node).__name__
        parts = [f"{pad}{name}"]
        for f in dataclasses.fields(node):
            if f.name in ("line", "col"):
                continue
            val = getattr(node, f.name)
            parts.append(pprint_field(f.name, val, depth + 1))
        return "\n".join(parts)
    return f"{pad}{node!r}"


def pprint_field(name, val, depth):
    import dataclasses
    pad = "  " * depth
    if dataclasses.is_dataclass(val):
        return f"{pad}{name}:\n" + pprint_node(val, depth + 1)
    if isinstance(val, list):
        if not val:
            return f"{pad}{name}: []"
        out = [f"{pad}{name}:"]
        for v in val:
            if dataclasses.is_dataclass(v):
                out.append(pprint_node(v, depth + 1))
            else:
                out.append(f"{'  ' * (depth + 1)}{v!r}")
        return "\n".join(out)
    return f"{pad}{name}: {val!r}"


def find_cc(preferred=None):
    order = [preferred] if preferred else []
    order += ["cc", "gcc", "clang"]
    for cc in order:
        if cc and shutil.which(cc):
            return cc
    return "cc"


def build_executable(args, extra, result):
    """Biên dịch mã C đã sinh ra file thực thi qua cc; trả về mã thoát."""
    c_code = result["c"]
    if not result["has_main"]:
        print("gc: \033[1;31mlỗi:\033[0m không tìm thấy hàm 'main' "
              "(cần 'fn main() -> int { ... }' để tạo file thực thi)",
              file=sys.stderr)
        return 1

    base = os.path.splitext(os.path.basename(args.input))[0]
    out_dir = os.path.dirname(os.path.abspath(args.input)) or "."
    out_path = args.output or os.path.join(out_dir, base)

    cc = find_cc(args.cc)
    if args.keep_c:
        c_path = os.path.join(out_dir, base + ".c")
        with open(c_path, "w") as f:
            f.write(c_code)
        keep = True
    else:
        tf = tempfile.NamedTemporaryFile("w", suffix=".c", delete=False)
        tf.write(c_code); tf.close()
        c_path = tf.name
        keep = False

    cmd = [cc, c_path, "-o", out_path, f"-O{args.O}", "-I", RUNTIME_DIR,
           "-std=gnu11", "-lm", "-w"] + extra
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        if not keep and os.path.exists(c_path):
            os.unlink(c_path)

    if proc.returncode != 0:
        print("gc: lỗi biên dịch C backend (đây thường là lỗi nội bộ của G):",
              file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return 1

    print(f"gc: \033[32mđã biên dịch\033[0m -> {out_path}"
          + (f"  (giữ {c_path})" if keep else ""))

    if args.run:
        print(f"gc: chạy {out_path}\n" + "-" * 44)
        sys.stdout.flush()
        rc = subprocess.run([out_path]).returncode
        print("-" * 44 + f"\ngc: chương trình kết thúc với mã {rc}")
        return rc
    return 0


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="gc", description="Trình biên dịch ngôn ngữ G")
    ap.add_argument("input", help="file nguồn .g")
    ap.add_argument("-o", "--output", help="tên file thực thi đầu ra")
    ap.add_argument("--emit-c", action="store_true", help="xuất mã C, không biên dịch")
    ap.add_argument("--keep-c", action="store_true", help="giữ lại file .c trung gian")
    ap.add_argument("-r", "--run", action="store_true", help="biên dịch rồi chạy")
    ap.add_argument("--check", action="store_true", help="chỉ kiểm tra kiểu, không sinh mã")
    ap.add_argument("--tokens", action="store_true", help="in danh sách token")
    ap.add_argument("--ast", action="store_true", help="in cây cú pháp AST")
    ap.add_argument("--cc", default=None, help="trình biên dịch C (mặc định tự dò)")
    ap.add_argument("-O", default="2", help="mức tối ưu (0,1,2,3,s,g), mặc định 2")
    ap.add_argument("--debug", action="store_true",
                    help="in traceback đầy đủ khi gặp lỗi nội bộ")
    ap.add_argument("--version", action="version", version=f"gc (ngôn ngữ G) {VERSION}")
    args, extra = ap.parse_known_args(argv)

    if not os.path.exists(args.input):
        print(f"gc: không tìm thấy file: {args.input}", file=sys.stderr)
        return 1
    if args.O not in ("0", "1", "2", "3", "s", "g", "z", "fast"):
        print(f"gc: mức tối ưu không hợp lệ: -O{args.O} (dùng 0,1,2,3,s,g)",
              file=sys.stderr)
        return 1

    try:
        if args.tokens:
            dump_tokens(args.input)
            return 0
        if args.ast:
            dump_ast(args.input)
            return 0
        if args.check:
            compile_to_c(args.input)  # chạy tới hết checker
            print(f"gc: \033[32mOK\033[0m — không phát hiện lỗi kiểu trong {args.input}")
            return 0
        result = compile_to_c(args.input)
    except GError as e:
        print(render_diag(e.filename, e.source, e.line, e.col, e.msg, e.phase),
              file=sys.stderr)
        return 1
    except RecursionError:
        print("gc: \033[1;31mlỗi:\033[0m đệ quy quá sâu khi biên dịch "
              "(biểu thức/cấu trúc lồng quá phức tạp?)", file=sys.stderr)
        return 2
    except Exception as e:  # lỗi nội bộ không lường trước -> không xả traceback thô
        if args.debug:
            raise
        print(f"gc: \033[1;31mlỗi nội bộ trình biên dịch:\033[0m {type(e).__name__}: {e}",
              file=sys.stderr)
        print("    (chạy lại với --debug để xem traceback; đây là bug của G, "
              "vui lòng báo cáo)", file=sys.stderr)
        return 2

    if args.emit_c:
        if args.output:
            with open(args.output, "w") as f:
                f.write(result["c"])
            print(f"gc: đã ghi mã C vào {args.output}")
        else:
            print(result["c"])
        return 0

    return build_executable(args, extra, result)
