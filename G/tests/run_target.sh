#!/usr/bin/env bash
# Kiểm LỚP TARGET/HAL: intrinsic đặc thù kiến trúc phải bị TỪ CHỐI trên target
# không có năng lực tương ứng, và vẫn CHẤP NHẬN trên target có.
#
# Vì sao cần bộ riêng: đây là lỗi "âm thầm" nguy hiểm nhất từng có trong G —
# 'outb(0x3F8, c)' trên aarch64 biên dịch sạch rồi hạ thành no-op, tạo ra một
# driver chết lặng. Bộ test thường không thấy được vì nó chỉ chạy trên x86.
#
# Mỗi ca: tests/target/<tên>.g với dòng đầu là chỉ thị:
#     //! reject <target> <chuỗi con phải có trong thông báo lỗi>
#     //! accept <target>
#
#   bash tests/run_target.sh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GC="$ROOT/gc"
GREEN="\033[32m"; RED="\033[1;31m"; RST="\033[0m"
strip_ansi() { sed -E 's/\x1b\[[0-9;]*m//g'; }

pass=0; fail=0
for src in "$ROOT"/tests/target/*.g; do
    [ -e "$src" ] || continue
    name="$(basename "$src" .g)"
    # Mỗi dòng '//!' là một khẳng định độc lập trên cùng file nguồn.
    while IFS= read -r line; do
        case "$line" in "//!"*) ;; *) continue ;; esac
        set -- $line                       # //! verb target [phần còn lại]
        verb="$2"; tgt="$3"; shift 3
        want="$*"
        out="$("$GC" "$src" --target="$tgt" --check 2>&1 | strip_ansi)"
        if [ "$verb" = "accept" ]; then
            if echo "$out" | grep -q "không phát hiện lỗi"; then
                echo -e "${GREEN}PASS${RST}         $name accept $tgt"
                pass=$((pass+1))
            else
                echo -e "${RED}FAIL${RST}         $name accept $tgt (bị từ chối)"
                echo "$out" | head -2
                fail=$((fail+1))
            fi
        else
            if echo "$out" | grep -q "không phát hiện lỗi"; then
                echo -e "${RED}PHẢI LỖI NHƯNG OK${RST}  $name reject $tgt"
                fail=$((fail+1))
            elif [ -n "$want" ] && ! echo "$out" | grep -qF "$want"; then
                echo -e "${RED}FAIL${RST}         $name reject $tgt (sai thông báo)"
                echo "  mong đợi chứa: $want"
                echo "  thực tế:       $(echo "$out" | head -1)"
                fail=$((fail+1))
            else
                echo -e "${GREEN}PASS${RST}         $name reject $tgt"
                pass=$((pass+1))
            fi
        fi
    done < "$src"
done

echo "-------------------------"
echo -e "Target: ${GREEN}$pass pass${RST}, ${RED}$fail fail${RST}"
[ "$fail" -eq 0 ]
