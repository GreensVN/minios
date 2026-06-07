#!/usr/bin/env bash
# Bộ test tự động cho ngôn ngữ G.
# Biên dịch & chạy từng ví dụ, so sánh stdout với tests/expected/<tên>.txt
# Dùng:  ./tests/run_tests.sh            (chạy test)
#        ./tests/run_tests.sh --bless    (cập nhật kết quả mong đợi)

set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GC="$ROOT/gc"
EXPECTED="$ROOT/tests/expected"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$EXPECTED"

GREEN='\033[32m'; RED='\033[1;31m'; YEL='\033[33m'; RST='\033[0m'
pass=0; fail=0; bless=0
[ "${1:-}" = "--bless" ] && bless=1

run_one() {
    local src="$1"
    local name; name="$(basename "$src" .g)"
    local bin="$TMP/$name"
    local got="$TMP/$name.out"
    local exp="$EXPECTED/$name.txt"

    if ! "$GC" "$src" -o "$bin" >"$TMP/$name.cc" 2>&1; then
        echo -e "${RED}BIÊN DỊCH LỖI${RST}  $name"
        cat "$TMP/$name.cc"
        fail=$((fail+1)); return
    fi
    "$bin" >"$got" 2>&1

    if [ "$bless" = "1" ]; then
        cp "$got" "$exp"
        echo -e "${YEL}BLESS${RST}        $name"
        return
    fi
    if [ ! -f "$exp" ]; then
        echo -e "${YEL}THIẾU KQ${RST}     $name (chạy --bless để tạo)"
        fail=$((fail+1)); return
    fi
    if diff -q "$exp" "$got" >/dev/null; then
        echo -e "${GREEN}PASS${RST}         $name"
        pass=$((pass+1))
    else
        echo -e "${RED}FAIL${RST}         $name"
        diff "$exp" "$got" | head -20
        fail=$((fail+1))
    fi
}

# Test "phải lỗi": chương trình BẮT BUỘC trượt type-check (--check) và in ra một
# thông điệp khớp mẫu mong đợi (dòng đầu của tests/fail/<tên>.txt). Khoá lại các
# chẩn đoán lỗi để không bị thoái lui.
# Xoá mã màu ANSI để so khớp ổn định (không phụ thuộc màu/đường dẫn tuyệt đối).
strip_ansi() { sed -E 's/\x1b\[[0-9;]*m//g'; }

run_fail() {
    local src="$1"
    local name; name="$(basename "$src" .g)"
    local exp="$ROOT/tests/fail/$name.txt"
    local got; got="$("$GC" "$src" --check 2>&1 | strip_ansi)"
    if echo "$got" | grep -q "không phát hiện lỗi"; then
        echo -e "${RED}PHẢI LỖI NHƯNG OK${RST}  $name"
        fail=$((fail+1)); return
    fi
    if [ "$bless" = "1" ]; then
        mkdir -p "$ROOT/tests/fail"
        # Lưu phần thông điệp sau 'lỗi ...:' — bỏ đường dẫn/dòng/cột để di động.
        echo "$got" | grep -oE 'lỗi [^:]+: .*' | head -1 > "$exp"
        echo -e "${YEL}BLESS${RST}        $name (fail)"; return
    fi
    if [ ! -f "$exp" ]; then
        echo -e "${YEL}THIẾU KQ${RST}     $name (fail) (chạy --bless để tạo)"
        fail=$((fail+1)); return
    fi
    local want; want="$(cat "$exp")"
    if echo "$got" | grep -qF "$want"; then
        echo -e "${GREEN}PASS${RST}         $name (fail)"
        pass=$((pass+1))
    else
        echo -e "${RED}FAIL${RST}         $name (fail)"
        echo "  mong đợi chứa: $want"
        echo "  thực tế:       $(echo "$got" | head -1)"
        fail=$((fail+1))
    fi
}

echo "=== Bộ test ngôn ngữ G ==="
for src in "$ROOT"/examples/*.g "$ROOT"/tests/cases/*.g; do
    [ -e "$src" ] || continue
    run_one "$src"
done
for src in "$ROOT"/tests/fail/*.g; do
    [ -e "$src" ] || continue
    run_fail "$src"
done

echo "-------------------------"
if [ "$bless" = "1" ]; then
    echo "Đã cập nhật kết quả mong đợi."
else
    echo -e "Kết quả: ${GREEN}$pass pass${RST}, ${RED}$fail fail${RST}"
fi
[ "$fail" -eq 0 ]
