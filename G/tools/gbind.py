#!/usr/bin/env python3
"""
gbind — sinh khai báo 'extern fn' của G từ header C.

VÌ SAO LÀ CÔNG CỤ RIÊNG, KHÔNG PHẢI TÍNH NĂNG CỦA COMPILER
==========================================================
Đây chính là ranh giới G-Core / G-Ext: **core không được biết** về hệ sinh thái
nào cả. Nếu nhét bộ sinh binding vào compiler thì mai lại phải nhét Python, rồi
CUDA, rồi JNI... và core phình ra mãi. Ở dạng công cụ ngoài, nó dùng đúng những
gì compiler đã công khai (`extern fn`, `@link`, `@symbol`) và có thể thay bằng
bộ sinh khác cho hệ sinh thái khác mà **không đụng vào compiler**.

CÁCH DÙNG
=========
    python3 tools/gbind.py /usr/include/zlib.h --link z > zlib.g
    python3 tools/gbind.py my.h --prefix my_ --module my

GIỚI HẠN — CỐ Ý
===============
Đây là bộ phân tích C **theo dòng, thực dụng**, không phải trình biên dịch C.
Nó xử lý các khai báo hàm phẳng (dạng phổ biến nhất trong header) và **BỎ QUA
có báo cáo** những gì không chắc: macro, hàm biến-đối-số, con trỏ hàm lồng,
kiểu chưa biết. Sinh ra một binding SAI nguy hiểm hơn nhiều so với bỏ sót một
hàm — nên khi nghi ngờ, nó bỏ qua và ghi lý do vào phần chú thích.
"""

import argparse
import re
import sys

#: Kiểu C -> kiểu G. Chỉ những ánh xạ CHẮC CHẮN; còn lại bỏ qua.
_TYPES = {
    "void": "void",
    "char": "char", "signed char": "i8", "unsigned char": "u8",
    "short": "i16", "short int": "i16", "unsigned short": "u16",
    "int": "int", "signed": "int", "signed int": "int",
    "unsigned": "u32", "unsigned int": "u32",
    "long": "i64", "long int": "i64", "unsigned long": "u64",
    "long long": "i64", "unsigned long long": "u64",
    "float": "f32", "double": "f64",
    "size_t": "usize", "ssize_t": "isize", "ptrdiff_t": "isize",
    "int8_t": "i8", "int16_t": "i16", "int32_t": "i32", "int64_t": "i64",
    "uint8_t": "u8", "uint16_t": "u16", "uint32_t": "u32", "uint64_t": "u64",
    "bool": "bool", "_Bool": "bool",
    "intptr_t": "isize", "uintptr_t": "usize",
}

_SKIP_QUALS = ("const", "volatile", "restrict", "register", "extern",
               "static", "inline", "__restrict", "__restrict__", "struct",
               "enum", "union")


def c_to_g(ctype: str):
    """Kiểu C -> kiểu G, hoặc None nếu không chắc chắn."""
    t = ctype.strip()
    t = re.sub(r"\b__attribute__\s*\(\([^)]*\)\)", " ", t)
    stars = t.count("*")
    t = t.replace("*", " ")
    words = [w for w in t.split() if w not in _SKIP_QUALS]
    if not words:
        return None
    base = " ".join(words)
    # 'char*' là chuỗi trong G (ánh xạ tự nhiên nhất cho API C).
    if stars == 1 and base in ("char",):
        return "str"
    g = _TYPES.get(base)
    if g is None:
        return None
    if stars:
        if g == "void":
            g = "u8"          # 'void*' -> '*u8' (G không có con trỏ void)
        return "*" * stars + g
    return g


_FN = re.compile(
    r"^\s*(?P<ret>[A-Za-z_][\w \t\*]*?)\s*"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<args>[^;{)]*)\)\s*;",
    re.M)


def parse_header(text):
    """Trả về (danh sách binding, danh sách bị bỏ qua kèm lý do)."""
    # bỏ chú thích và chỉ thị tiền xử lý (không phải bộ tiền xử lý thật)
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    text = re.sub(r"^\s*#.*?(?<!\\)$", " ", text, flags=re.M)

    out, skipped = [], []
    for m in _FN.finditer(text):
        name = m.group("name")
        rett = m.group("ret").strip()
        argt = m.group("args").strip()
        if name in ("if", "for", "while", "switch", "return", "sizeof"):
            continue
        if "..." in argt:
            skipped.append((name, "hàm biến-đối-số"))
            continue
        if "(" in argt:
            skipped.append((name, "có con trỏ hàm trong tham số"))
            continue
        gret = c_to_g(rett) if rett else None
        if gret is None:
            skipped.append((name, f"kiểu trả về chưa ánh xạ: '{rett}'"))
            continue
        params, bad = [], None
        if argt and argt.replace(" ", "") not in ("void", ""):
            for i, raw in enumerate(argt.split(",")):
                raw = raw.strip()
                if not raw:
                    continue
                pm = re.match(r"^(?P<ty>.*?)(?P<nm>[A-Za-z_]\w*)?"
                              r"(?P<arr>\s*\[\s*\d*\s*\])?$", raw)
                ty = (pm.group("ty") or "").strip() if pm else raw
                nm = (pm.group("nm") or "") if pm else ""
                if pm and pm.group("arr"):
                    ty += "*"
                if not ty:
                    ty, nm = raw, ""
                g = c_to_g(ty)
                if g is None:
                    bad = f"tham số {i + 1} chưa ánh xạ: '{raw}'"
                    break
                if not nm or nm in _SKIP_QUALS or c_to_g(nm) is not None:
                    nm = f"a{i}"
                params.append(f"{nm}: {g}")
        if bad:
            skipped.append((name, bad))
            continue
        out.append((name, params, gret))
    return out, skipped


def main():
    ap = argparse.ArgumentParser(
        description="Sinh khai báo 'extern fn' của G từ header C")
    ap.add_argument("header", help="đường dẫn tới file .h")
    ap.add_argument("--link", help="tên thư viện -> thêm '@link(\"...\")'")
    ap.add_argument("--prefix", default="",
                    help="chỉ lấy hàm có tiền tố này")
    ap.add_argument("--strip-prefix", action="store_true",
                    help="bỏ tiền tố khỏi tên G (dùng '@symbol' giữ tên thật)")
    ap.add_argument("-o", "--output", help="ghi ra file (mặc định: stdout)")
    args = ap.parse_args()

    try:
        with open(args.header, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        print(f"gbind: không đọc được '{args.header}': {e}", file=sys.stderr)
        return 1

    fns, skipped = parse_header(text)
    if args.prefix:
        fns = [f for f in fns if f[0].startswith(args.prefix)]

    lines = [
        f"// Sinh tự động bởi tools/gbind.py từ '{args.header}'",
        "// KIỂM LẠI trước khi dùng: gbind là bộ phân tích thực dụng, không",
        "// phải trình biên dịch C. Chữ ký sai sẽ hỏng ABI lúc chạy.",
        "",
    ]
    tag = f'@link("{args.link}") ' if args.link else ""
    for name, params, ret in fns:
        gname = name
        sym = ""
        if args.strip_prefix and args.prefix and name.startswith(args.prefix):
            gname = name[len(args.prefix):] or name
            if gname != name:
                sym = f'@symbol("{name}") '
        r = "" if ret == "void" else f" -> {ret}"
        lines.append(f"{tag}{sym}extern fn {gname}({', '.join(params)}){r}")

    if skipped:
        lines += ["", f"// BỎ QUA {len(skipped)} khai báo (không chắc chắn):"]
        for n, why in skipped[:40]:
            lines.append(f"//   {n}: {why}")
        if len(skipped) > 40:
            lines.append(f"//   ... và {len(skipped) - 40} khai báo nữa")

    text_out = "\n".join(lines) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text_out)
        print(f"gbind: {len(fns)} hàm -> {args.output} "
              f"({len(skipped)} bỏ qua)", file=sys.stderr)
    else:
        sys.stdout.write(text_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
