#!/usr/bin/env bash
# Hạ TOÀN BỘ ví dụ + ca test sang G-IR rồi chạy trình kiểm bất biến IR.
#
# Đây là bằng chứng cho tuyên bố "G-IR biểu diễn được cả ngôn ngữ" — nếu một
# tính năng mới không hạ được, hoặc hạ ra CFG hỏng (thiếu terminator, nhảy tới
# nhãn không tồn tại, dùng temp chưa định nghĩa, block không thể tới...), bộ này
# đỏ ngay cả khi bộ test thường vẫn xanh.
#
#   bash tests/run_ir.sh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GC="$ROOT/gc"
GREEN="\033[32m"; RED="\033[1;31m"; RST="\033[0m"
strip_ansi() { sed -E 's/\x1b\[[0-9;]*m//g'; }

pass=0; fail=0
for src in "$ROOT"/examples/*.g "$ROOT"/tests/cases/*.g; do
    [ -e "$src" ] || continue
    name="$(basename "$src" .g)"
    out="$("$GC" "$src" --verify-ir 2>&1 | strip_ansi)"
    if echo "$out" | grep -q "IR hợp lệ"; then
        echo -e "${GREEN}PASS${RST}         $name"
        pass=$((pass+1))
    else
        echo -e "${RED}IR LỖI${RST}       $name"
        echo "$out" | head -4
        fail=$((fail+1))
    fi
done

# Chương trình freestanding cũng phải hạ được (không libc, có intrinsic OS).
for src in "$ROOT"/tests/freestanding/*.g "$ROOT"/examples/kernel/*.g; do
    [ -e "$src" ] || continue
    name="$(basename "$src" .g)"
    out="$("$GC" "$src" --verify-ir --freestanding 2>&1 | strip_ansi)"
    if echo "$out" | grep -q "IR hợp lệ"; then
        echo -e "${GREEN}PASS${RST}         $name (freestanding)"
        pass=$((pass+1))
    else
        echo -e "${RED}IR LỖI${RST}       $name (freestanding)"
        echo "$out" | head -4
        fail=$((fail+1))
    fi
done

echo "-------------------------"
echo -e "G-IR: ${GREEN}$pass hợp lệ${RST}, ${RED}$fail lỗi${RST}"
[ "$fail" -eq 0 ]
