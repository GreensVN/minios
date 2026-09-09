#!/usr/bin/env bash
# Kiểm TRÌNH TỐI ƯU IR: chạy mỗi chương trình TRƯỚC và SAU khi tối ưu, rồi so
# từng byte đầu ra + mã thoát.
#
# Đây là định nghĩa "pass đúng": một phép biến đổi hợp lệ KHÔNG ĐƯỢC đổi kết
# quả chạy. Trình thông dịch được viết trước trình tối ưu chính vì lý do này —
# nó là tiên đề (oracle) rẻ và độc lập với backend C.
#
# Cũng kiểm bằng backend C (mã đã tối ưu vẫn phải biên dịch và chạy đúng), vì
# một pass có thể sinh IR mà trình thông dịch chấp nhận nhưng backend thì không.
#
#   bash tests/run_opt_diff.sh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GC="$ROOT/gc"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
GREEN="\033[32m"; RED="\033[1;31m"; YEL="\033[33m"; RST="\033[0m"
strip_ansi() { sed -E 's/\x1b\[[0-9;]*m//g'; }

same=0; diff_n=0; unsup=0
for src in "$ROOT"/examples/*.g "$ROOT"/tests/cases/*.g; do
    [ -e "$src" ] || continue
    name="$(basename "$src" .g)"
    infile="$ROOT/tests/input/$name.txt"
    IN=/dev/null; [ -f "$infile" ] && IN="$infile"

    "$GC" "$src" --interp <"$IN" >"$TMP/$name.a" 2>"$TMP/$name.ae"
    a_rc=$?
    if [ "$a_rc" = "3" ]; then unsup=$((unsup+1)); continue; fi

    "$GC" "$src" --interp --opt-ir <"$IN" >"$TMP/$name.b" 2>"$TMP/$name.be"
    b_rc=$?
    cat "$TMP/$name.ae" >> "$TMP/$name.a"
    cat "$TMP/$name.be" >> "$TMP/$name.b"

    if [ "$a_rc" != "$b_rc" ]; then
        echo -e "${RED}KHÁC MÃ THOÁT${RST}  $name (gốc=$a_rc, tối ưu=$b_rc)"
        diff_n=$((diff_n+1)); continue
    fi
    if ! diff -q <(strip_ansi <"$TMP/$name.a") \
                 <(strip_ansi <"$TMP/$name.b") >/dev/null; then
        echo -e "${RED}KHÁC ĐẦU RA${RST}   $name (tối ưu đổi kết quả!)"
        diff <(strip_ansi <"$TMP/$name.a") <(strip_ansi <"$TMP/$name.b") | head -6
        diff_n=$((diff_n+1)); continue
    fi

    # IR đã tối ưu vẫn phải HỢP LỆ và biên dịch được qua backend đọc-từ-IR.
    if ! "$GC" "$src" --verify-ir --opt-ir >/dev/null 2>&1; then
        echo -e "${RED}IR HỎNG${RST}      $name (sau tối ưu)"
        diff_n=$((diff_n+1)); continue
    fi
    echo -e "${GREEN}KHỚP${RST}        $name"
    same=$((same+1))
done

echo "-------------------------"
echo -e "Opt diff: ${GREEN}$same khớp${RST}, ${RED}$diff_n khác${RST}, ${YEL}$unsup bỏ qua${RST}"
[ "$diff_n" -eq 0 ]
