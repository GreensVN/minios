"""
G Language - Driver: điều phối toàn bộ pipeline biên dịch.
  nguồn .g  ->  Lexer  ->  Parser  ->  (gộp module)  ->  Checker  ->  Codegen  ->  cc
"""

import os
import re
import sys
import shutil
import subprocess
import tempfile

from .lexer import Lexer, LexError
from .parser import Parser, ParseError
from .checker import Checker, CheckError, CheckErrors
from .codegen import Codegen, CodegenError
from . import ast_nodes as A

VERSION = "0.24.0"

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
def render_diag(filename, source, line, col, msg, phase, kind="lỗi"):
    RED = "\033[1;31m"; BOLD = "\033[1m"; CYAN = "\033[36m"; RST = "\033[0m"
    if kind != "lỗi":
        RED = "\033[1;33m"        # cảnh báo: vàng
    head = f"{BOLD}{filename}:{line}:{col}:{RST} {RED}{kind} {phase}:{RST} {msg}"
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
        # (tên, dòng, cột) — dạng chuỗi trần vẫn được chấp nhận để tương thích.
        imp, iline, icol = imp if isinstance(imp, tuple) else (imp, 1, 1)
        ipath = resolve_import(imp, path, sources)
        if ipath is None:
            raise GError(path, sources[ap][1], iline, icol,
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


def compile_to_c(main_path, freestanding=False, no_warnings=False,
                 warnings_as_errors=False, target=None):
    """Trả về dict {c, has_main}. Báo lỗi đúng file nguồn (kể cả module import)."""
    sources = {}
    main_ap = os.path.abspath(main_path)
    prog = build_program(main_path, sources)
    main_src = sources[main_ap][1]
    def _to_gerror(e):
        fpath, fsrc = sources.get(e.file or main_ap, (main_path, main_src))
        return GError(fpath, fsrc, e.line, e.col, e.msg, "kiểu/ngữ nghĩa")
    ck = Checker(prog, freestanding=freestanding, target=target)
    try:
        ck.check()
    except CheckErrors as e:
        errs = [_to_gerror(x) for x in e.errors]
        first = errs[0]
        first.more = errs[1:]
        raise first
    except CheckError as e:
        raise _to_gerror(e)
    # Cảnh báo (không chặn biên dịch): in sau khi checker chạy xong sạch.
    if ck.warnings and not no_warnings:
        for msg, wline, wcol, wfile in ck.warnings:
            wpath, wsrc = sources.get(wfile or main_ap, (main_path, main_src))
            kind = "lỗi" if warnings_as_errors else "cảnh báo"
            print(render_diag(wpath, wsrc, wline, wcol, msg, "kiểu/ngữ nghĩa",
                              kind=kind), file=sys.stderr)
        if warnings_as_errors:
            n = len(ck.warnings)
            print(f"gc: \033[1;31m{n} cảnh báo bị coi là lỗi\033[0m (-W)",
                  file=sys.stderr)
            sys.exit(1)
    try:
        c_code = Codegen(prog).generate()
    except CodegenError as e:
        raise GError(main_path, main_src, 0, 0, str(e), "sinh mã")
    return {"c": c_code, "has_main": has_main(prog), "prog": prog}


def build_ir(main_path, freestanding=False, target=None, optimize=False):
    """Chạy tới hết checker rồi HẠ sang G-IR. Trả về (ir.Module, prog).

    Tách riêng khỏi compile_to_c: đường sinh mã C mặc định KHÔNG đi qua IR trong
    giai đoạn chuyển đổi (xem ARCHITECTURE.md §3), nên hai đường độc lập nhau.
    """
    from .irgen import IRGen, IRGenError
    sources = {}
    main_ap = os.path.abspath(main_path)
    prog = build_program(main_path, sources)
    main_src = sources[main_ap][1]

    def _to_gerror(e):
        fpath, fsrc = sources.get(e.file or main_ap, (main_path, main_src))
        return GError(fpath, fsrc, e.line, e.col, e.msg, "kiểu/ngữ nghĩa")

    ck = Checker(prog, freestanding=freestanding, target=target)
    try:
        ck.check()
    except CheckErrors as e:
        errs = [_to_gerror(x) for x in e.errors]
        first = errs[0]
        first.more = errs[1:]
        raise first
    except CheckError as e:
        raise _to_gerror(e)

    try:
        mod = IRGen(prog, module_name=os.path.basename(main_path),
                    enum_values=ck.enums, target=ck.target).generate()
    except IRGenError as e:
        raise GError(main_path, main_src, 0, 0, str(e), "hạ mã IR")
    if optimize:
        from . import iropt
        iropt.optimize(mod)
    return mod, prog


def _target_names():
    from . import target as _t
    return _t.available()


def list_targets():
    from . import target as _t
    cur = _t.default_target()
    print("Target khả dụng (★ = mặc định trên máy này):")
    for name in _t.available():
        tg = _t.TARGETS[name]
        mark = "★" if tg.name == cur.name else " "
        caps = ", ".join(sorted(tg.caps)) or "(không có năng lực phần cứng thô)"
        print(f" {mark} {name:<16} {tg.arch:<9} {tg.ptr_bits}-bit  {caps}")
    return 0


def _backend_names():
    from . import backend as B
    return B.available()


def build_llvm(args, extra, llvm_ir, prog, tgt):
    """Dịch LLVM IR -> object -> chương trình chạy được.

    Runtime của G là header C toàn 'static inline', nên object LLVM cần một
    shim C nhỏ cung cấp các ký hiệu mà mã sinh ra tham chiếu (g_panic,
    g_bounds_fail, g_get_stream...)."""
    if args.emit_c or args.output and args.output.endswith(".ll"):
        out = args.output or "out.ll"
        with open(out, "w") as f:
            f.write(llvm_ir)
        print(f"gc: đã ghi LLVM IR vào {out}")
        return 0
    try:
        import llvmlite.binding as llvm
    except ImportError:
        print("gc: \033[1;31mlỗi\033[0m: backend llvm cần gói 'llvmlite' "
              "(pip install llvmlite)", file=sys.stderr)
        return 1
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    try:
        mod = llvm.parse_assembly(llvm_ir)
        mod.verify()
    except RuntimeError as e:
        print("gc: \033[1;31mLLVM IR không hợp lệ\033[0m (lỗi nội bộ của G):",
              file=sys.stderr)
        print(str(e)[:2000], file=sys.stderr)
        return 1
    # reloc='pic' + codemodel='default': object mặc định của llvmlite dùng
    # relocation tuyệt đối, khiến linker cảnh báo/ từ chối khi tạo PIE.
    tm = llvm.Target.from_default_triple().create_target_machine(
        reloc="pic", codemodel="default")
    with tempfile.TemporaryDirectory() as d:
        obj = os.path.join(d, "g.o")
        with open(obj, "wb") as f:
            f.write(tm.emit_object(mod))
        if args.emit_asm:
            out = args.output or "out.s"
            with open(out, "w") as f:
                f.write(tm.emit_assembly(mod))
            print(f"gc: đã xuất assembly -> {out}")
            return 0
        shim = os.path.join(d, "shim.c")
        with open(shim, "w") as f:
            f.write(_LLVM_SHIM)
        if args.compile_obj:
            out = args.output or "out.o"
            shutil.copy(obj, out)
            print(f"gc: đã tạo đối tượng -> {out}")
            return 0
        out = args.output or "a.out"
        cc = find_cc(args.cc)
        cmd = [cc, obj, shim, "-I", RUNTIME_DIR, "-o", out, "-lm", "-w"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print("gc: \033[1;31mlỗi liên kết\033[0m (backend llvm):",
                  file=sys.stderr)
            print(r.stderr[:2000], file=sys.stderr)
            return 1
        print(f"gc: \033[32mđã biên dịch\033[0m -> {out}")
        if args.run:
            return subprocess.run([os.path.abspath(out)]).returncode
    return 0


#: Shim C cho backend LLVM: runtime của G là header 'static inline' nên object
#: LLVM không thấy được. Vài hàm ngoài-dòng ở đây là đủ.
_LLVM_SHIM = """
#include "g_runtime.h"
void* g_get_stream(int which) { return which ? (void*)stderr : (void*)stdout; }
/* Runtime của G toàn 'static inline' -> object LLVM không thấy. Xuất ra
   ngoài dòng những thứ mã sinh ra tham chiếu. */
int g_ll_popcount(unsigned long long v) { return __builtin_popcountll(v); }
int g_ll_clz(unsigned long long v) { return v ? __builtin_clzll(v) : 64; }
int g_ll_ctz(unsigned long long v) { return v ? __builtin_ctzll(v) : 64; }
unsigned long long g_ll_bswap(unsigned long long v) { return __builtin_bswap64(v); }
unsigned long long g_ll_rotl(unsigned long long v, unsigned n) { return g_rotl64(v, n); }
unsigned long long g_ll_rotr(unsigned long long v, unsigned n) { return g_rotr64(v, n); }
void* g_ll_calloc(unsigned long long n) { return calloc((size_t)n, 1); }
void  g_ll_free(void* p) { free(p); }
"""


def run_interp(main_path, freestanding=False, target=None, opt=False):
    """Chạy chương trình bằng trình thông dịch IR (hiện thực THAM CHIẾU)."""
    from . import interp as _in
    mod, _ = build_ir(main_path, freestanding, target, opt)
    try:
        return _in.run(mod)
    except _in.GPanic as e:
        print(f"\033[1;31mG panic:\033[0m {e.msg}", file=sys.stderr)
        return 101
    except _in.InterpError as e:
        print(f"gc: \033[1;33mthông dịch:\033[0m {e}", file=sys.stderr)
        return 3


def emit_ir(main_path, freestanding=False, target=None, opt=False):
    mod, _ = build_ir(main_path, freestanding, target, opt)
    print(str(mod))
    return 0


def verify_ir(main_path, freestanding=False, target=None, opt=False):
    from . import irverify
    mod, _ = build_ir(main_path, freestanding, target, opt)
    errs = irverify.verify(mod)
    if errs:
        for e in errs[:20]:
            print(f"gc: \033[1;31mIR không hợp lệ:\033[0m {e}", file=sys.stderr)
        if len(errs) > 20:
            print(f"gc: ... và {len(errs) - 20} lỗi IR nữa", file=sys.stderr)
        return 1
    nf = len(mod.funcs)
    nb = sum(len(f.blocks) for f in mod.funcs)
    ni = sum(len(b.instrs) for f in mod.funcs for b in f.blocks)
    print(f"gc: \033[32mIR hợp lệ\033[0m — {nf} hàm, {nb} block, {ni} lệnh")
    return 0


def dump_tokens(main_path):
    sources = {}
    _, tokens = parse_file(main_path, sources)
    for t in tokens:
        print(f"  {t.line:>4}:{t.col:<3} {t.kind:<6} {t.value!r}")


def dump_ast(main_path):
    sources = {}
    prog = build_program(main_path, sources)
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


def _cc_common_flags(args):
    """Cờ cc dùng chung cho mọi chế độ biên dịch native (exe/obj/asm)."""
    flags = [f"-O{args.O}", "-I", RUNTIME_DIR, "-std=gnu11", "-w"]
    if args.no_checks:
        flags.append("-DG_NO_CHECKS")   # tắt kiểm tra biên mảng/chia 0 lúc chạy
    if args.freestanding:
        # Không phụ thuộc libc/môi trường lưu trữ — dùng cho kernel/firmware.
        # Tắt bảo vệ stack & PIC vì kernel tự quản lý mọi thứ; bật runtime
        # freestanding (memcpy/memset tự cài, panic = dừng CPU).
        flags += ["-ffreestanding", "-fno-stack-protector", "-fno-pic",
                  "-DG_FREESTANDING"]
    # Cross-compile: chỉ thêm '--target=' khi target KHÁC máy hiện tại (gcc bản
    # thường không hiểu cờ này; clang thì có). Người dùng vẫn có thể chỉ định
    # trình biên dịch chéo qua '--cc'.
    tgt = getattr(args, "_target", None)
    if tgt is not None:
        from . import target as _t
        if tgt.name != _t.default_target().name and tgt.triple:
            flags.append(f"--target={tgt.triple}")
    return flags


def build_native(args, extra, result):
    """Biên dịch mã C đã sinh ra: file thực thi (mặc định), file đối tượng .o
    (-c, để ghép với bootloader/linker script), hoặc assembly .s (-S).
    Trả về mã thoát."""
    c_code = result["c"]
    mode = "obj" if args.compile_obj else ("asm" if args.emit_asm else "exe")

    # Chỉ chế độ 'exe' HOSTED mới bắt buộc có 'main' (cần điểm vào để liên kết).
    # Freestanding/đối tượng/asm: điểm vào do người dùng/linker quyết định.
    if mode == "exe" and not args.freestanding and not result["has_main"]:
        print("gc: \033[1;31mlỗi:\033[0m không tìm thấy hàm 'main' "
              "(cần 'fn main() -> int { ... }' để tạo file thực thi; hoặc dùng "
              "'-c' để xuất file đối tượng, hoặc '--freestanding' cho kernel)",
              file=sys.stderr)
        return 1

    base = os.path.splitext(os.path.basename(args.input))[0]
    out_dir = os.path.dirname(os.path.abspath(args.input)) or "."
    default_ext = {"obj": ".o", "asm": ".s", "exe": ""}[mode]
    out_path = args.output or os.path.join(out_dir, base + default_ext)

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

    cmd = [cc, c_path, "-o", out_path] + _cc_common_flags(args)
    if mode == "obj":
        cmd.append("-c")
    elif mode == "asm":
        cmd.append("-S")
    cmd += extra
    if mode == "exe":
        # Liên kết: freestanding bỏ libc; hosted cần libm cho lib/std (toán f64).
        cmd += ["-nostdlib"] if args.freestanding else ["-lm"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        if not keep and os.path.exists(c_path):
            os.unlink(c_path)

    if proc.returncode != 0:
        # 'extern fn' khai báo hàm libc với chữ ký lệch header (vd 'srand(int)'
        # thay vì 'u32', 'puts(*char)' thay vì 'str') -> gcc 'conflicting types'.
        # Đây là lỗi của mã G, không phải lỗi nội bộ — giải thích cho rõ.
        m = re.search(r"conflicting types for [‘'](\w+)[’']", proc.stderr)
        if m:
            print(f"gc: \033[31mlỗi\033[0m: 'extern fn {m.group(1)}' có chữ ký khác "
                  f"với khai báo trong header thư viện C — sửa kiểu tham số/kiểu "
                  f"trả về cho khớp (xem 'note: previous declaration' bên dưới; "
                  f"'str' = const char*, 'u32' = unsigned int, 'usize' = size_t):",
                  file=sys.stderr)
        elif ("--target=" in proc.stderr
              or "unrecognized command-line option" in proc.stderr):
            # Cross-compile thất bại vì TOOLCHAIN, không phải lỗi của G.
            tg = getattr(args, "_target", None)
            triple = getattr(tg, "triple", "?") if tg else "?"
            print(f"gc: \033[31mlỗi\033[0m: trình biên dịch C '{cc}' không "
                  f"biên dịch chéo được sang '{tg}'.\n"
                  f"    Cần một toolchain cho {triple}, ví dụ:\n"
                  f"      gc ... --target={tg} --cc={triple}-gcc\n"
                  f"      gc ... --target={tg} --cc=clang\n"
                  f"    (gcc bản thường không hiểu '--target='; clang thì có.)",
                  file=sys.stderr)
            print(proc.stderr, file=sys.stderr)
            return 1
        else:
            print("gc: lỗi biên dịch C backend (đây thường là lỗi nội bộ của G):",
                  file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return 1

    label = {"obj": "đã tạo đối tượng", "asm": "đã xuất assembly",
             "exe": "đã biên dịch"}[mode]
    print(f"gc: \033[32m{label}\033[0m -> {out_path}"
          + (f"  (giữ {c_path})" if keep else ""))

    if args.run and mode == "exe" and not args.freestanding:
        print(f"gc: chạy {out_path}\n" + "-" * 44)
        sys.stdout.flush()
        rc = subprocess.run([out_path]).returncode
        print("-" * 44 + f"\ngc: chương trình kết thúc với mã {rc}")
        return rc
    return 0


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="gc", description="Trình biên dịch ngôn ngữ G")
    # nargs="?" để '--list-targets' / '--version' dùng được mà không cần file.
    ap.add_argument("input", nargs="?", help="file nguồn .g")
    ap.add_argument("-o", "--output", help="tên file thực thi đầu ra")
    ap.add_argument("--emit-c", action="store_true", help="xuất mã C, không biên dịch")
    ap.add_argument("--keep-c", action="store_true", help="giữ lại file .c trung gian")
    ap.add_argument("-r", "--run", action="store_true", help="biên dịch rồi chạy")
    ap.add_argument("--check", action="store_true", help="chỉ kiểm tra kiểu, không sinh mã")
    ap.add_argument("--tokens", action="store_true", help="in danh sách token")
    ap.add_argument("--ast", action="store_true", help="in cây cú pháp AST")
    ap.add_argument("--cc", default=None, help="trình biên dịch C (mặc định tự dò)")
    ap.add_argument("-w", "--no-warnings", action="store_true",
                    help="tắt cảnh báo (vd biến khai báo mà không dùng)")
    ap.add_argument("-W", "--warnings-as-errors", action="store_true",
                    help="coi cảnh báo là lỗi (dừng biên dịch)")
    ap.add_argument("--freestanding", action="store_true",
                    help="chế độ không libc (kernel/firmware): -ffreestanding "
                         "-nostdlib, không cần 'main', runtime tự cài memcpy/panic")
    ap.add_argument("-c", "--compile-obj", action="store_true",
                    help="biên dịch thành file đối tượng .o (không liên kết) — "
                         "để ghép với bootloader/linker script")
    ap.add_argument("-S", "--emit-asm", action="store_true",
                    help="xuất mã assembly .s của chương trình")
    ap.add_argument("-O", default="2", help="mức tối ưu (0,1,2,3,s,g), mặc định 2")
    ap.add_argument("--no-checks", action="store_true",
                    help="tắt kiểm tra lúc chạy (biên mảng tĩnh, chia cho 0) — "
                         "nhanh hơn, nhưng lỗi trở thành hành vi không xác định")
    ap.add_argument("--target", default=None,
                    help="kiến trúc đích: " + ", ".join(_target_names())
                         + " (mặc định: máy hiện tại)")
    ap.add_argument("--list-targets", action="store_true",
                    help="liệt kê target và năng lực phần cứng của chúng")
    ap.add_argument("--opt-ir", action="store_true",
                    help="chạy các pass tối ưu trên G-IR trước khi sinh mã")
    ap.add_argument("--interp", action="store_true",
                    help="chạy chương trình bằng trình thông dịch G-IR "
                         "(hiện thực tham chiếu, không qua C)")
    ap.add_argument("--emit-ir", action="store_true",
                    help="xuất G-IR dạng văn bản (biểu diễn trung gian)")
    ap.add_argument("--verify-ir", action="store_true",
                    help="hạ sang G-IR rồi chạy trình kiểm bất biến IR")
    ap.add_argument("--backend", default="c",
                    help="backend sinh mã: " + ", ".join(_backend_names()))
    ap.add_argument("--debug", action="store_true",
                    help="in traceback đầy đủ khi gặp lỗi nội bộ")
    ap.add_argument("--version", action="version", version=f"gc (ngôn ngữ G) {VERSION}")
    args, extra = ap.parse_known_args(argv)

    if args.list_targets:
        return list_targets()

    if not args.input:
        ap.print_usage(sys.stderr)
        print("gc: thiếu file nguồn .g", file=sys.stderr)
        return 1

    # Phân giải target một lần rồi truyền xuống checker/backend.
    from . import target as _t
    try:
        tgt = _t.get(args.target)
    except KeyError:
        print(f"gc: target không tồn tại: '{args.target}' — có: "
              f"{', '.join(_t.available())}", file=sys.stderr)
        return 1

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
        # Backend phải tồn tại — trước đây '--backend=nope' bị bỏ qua âm thầm.
        from . import backend as _B
        try:
            _B.get(args.backend)
        except _B.BackendError as e:
            print(f"gc: {e}", file=sys.stderr)
            return 1
        if args.backend == "ir":
            return emit_ir(args.input, args.freestanding, tgt, args.opt_ir)
        if _B.get(args.backend).consumes == "ir":
            # Backend đọc-từ-IR: chạy checker -> hạ IR -> verify -> sinh mã.
            from . import irverify
            mod, prog = build_ir(args.input, args.freestanding, tgt,
                                 args.opt_ir)
            errs = irverify.verify(mod)
            if errs:
                print(f"gc: \033[1;31mIR không hợp lệ:\033[0m {errs[0]}",
                      file=sys.stderr)
                return 1
            try:
                code = _B.get(args.backend).emit(mod)
            except _B.BackendError as e:
                print(f"gc: \033[1;31mlỗi backend {args.backend}:\033[0m {e}",
                      file=sys.stderr)
                return 1
            # Backend LLVM: mã sinh ra là LLVM IR, không phải C. Dịch sang
            # object bằng llvmlite rồi để linker hệ thống ghép với runtime.
            if args.backend == "llvm":
                return build_llvm(args, extra, code, prog, tgt)
            result = {"c": code, "has_main": has_main(prog), "prog": prog}
            args._target = tgt
            if args.emit_c:
                if args.output:
                    with open(args.output, "w") as f:
                        f.write(code)
                    print(f"gc: đã ghi mã C vào {args.output}")
                else:
                    print(code)
                return 0
            return build_native(args, extra, result)
        if args.interp:
            return run_interp(args.input, args.freestanding, tgt, args.opt_ir)
        if args.emit_ir:
            return emit_ir(args.input, args.freestanding, tgt, args.opt_ir)
        if args.verify_ir:
            return verify_ir(args.input, args.freestanding, tgt, args.opt_ir)
        if args.check:
            compile_to_c(args.input, args.freestanding, args.no_warnings,
                         args.warnings_as_errors, tgt)  # chạy tới hết checker
            print(f"gc: \033[32mOK\033[0m — không phát hiện lỗi kiểu trong {args.input}")
            return 0
        result = compile_to_c(args.input, args.freestanding, args.no_warnings,
                              args.warnings_as_errors, tgt)
    except GError as e:
        print(render_diag(e.filename, e.source, e.line, e.col, e.msg, e.phase),
              file=sys.stderr)
        more = getattr(e, "more", [])
        for x in more:
            print(render_diag(x.filename, x.source, x.line, x.col, x.msg, x.phase),
                  file=sys.stderr)
        if more:
            n = len(more) + 1
            tail = (" (dừng sau %d lỗi)" % n) if n >= CheckErrors.MAX else ""
            print(f"gc: \033[1;31m{n} lỗi\033[0m{tail}", file=sys.stderr)
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

    args._target = tgt
    return build_native(args, extra, result)
