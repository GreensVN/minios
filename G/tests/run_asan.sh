#!/usr/bin/env bash
# Chạy MỌI ví dụ/ca test qua AddressSanitizer + UndefinedBehaviorSanitizer trên
# mã C sinh ra. Bắt các lỗi mà bộ test thường không thấy: đọc/ghi ngoài biên,
# use-after-free, tràn số nguyên có dấu, con trỏ lệch căn...
#
#   bash tests/run_asan.sh          # bỏ qua rò rỉ (mặc định)
#   LEAKS=1 bash tests/run_asan.sh  # kiểm cả rò rỉ bộ nhớ
#
# Rò rỉ bị TẮT mặc định vì chuỗi heap (format/lát cắt/method str) phải g_free
# thủ công — nhiều ví dụ cố ý không giải phóng cho ngắn gọn.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GC="$ROOT/gc"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
GREEN="\033[32m"; RED="\033[1;31m"; RST="\033[0m"
: "${LEAKS:=0}"
export ASAN_OPTIONS="detect_leaks=$LEAKS"
ok=0; bad=0
for src in "$ROOT"/examples/*.g "$ROOT"/tests/cases/*.g; do
    [ -e "$src" ] || continue
    name="$(basename "$src" .g)"
    "$GC" "$src" --emit-c -o "$TMP/$name.c" >/dev/null 2>&1 || continue
    gcc -std=gnu11 -I "$ROOT/runtime" -fsanitize=address,undefined \
        -fno-omit-frame-pointer -g -O0 -w \
        "$TMP/$name.c" -o "$TMP/$name" -lm 2>/dev/null || continue
    infile="$ROOT/tests/input/$name.txt"
    if [ -f "$infile" ]; then out="$("$TMP/$name" <"$infile" 2>&1)"
    else out="$("$TMP/$name" </dev/null 2>&1)"; fi
    if echo "$out" | grep -qE "AddressSanitizer|runtime error:|LeakSanitizer"; then
        echo -e "${RED}SANITIZER${RST}    $name"
        echo "$out" | grep -E "AddressSanitizer|runtime error:|SUMMARY" | head -3
        bad=$((bad+1))
    else
        echo -e "${GREEN}PASS${RST}         $name"
        ok=$((ok+1))
    fi
done
echo "-------------------------"
echo -e "Sanitizer: ${GREEN}$ok sạch${RST}, ${RED}$bad có vấn đề${RST} (rò rỉ: $([ "$LEAKS" = 1 ] && echo bật || echo tắt))"
[ "$bad" -eq 0 ]
