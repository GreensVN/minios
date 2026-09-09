#!/usr/bin/env bash
# So khớp TRÌNH THÔNG DỊCH G-IR với backend C.
#
# VÌ SAO cần bộ này khi đã có run_backend_diff.sh: hai backend C **cùng đọc một
# IR**. Nếu tầng hạ mã hiểu sai ngữ nghĩa của G, cả hai sai GIỐNG NHAU và bộ so
# khớp kia vẫn xanh. Trình thông dịch là hiện thực THỨ BA, độc lập (chạy IR
# bằng Python, không qua C) — nó phá được điểm mù đó.
#
# Ca mà trình thông dịch chưa mô phỏng được (asm, intrinsic OS, vài hàm libc)
# được tính "chưa hỗ trợ", KHÔNG phải sai — và liệt kê rõ.
#
#   bash tests/run_interp_diff.sh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GC="$ROOT/gc"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
GREEN="\033[32m"; RED="\033[1;31m"; YEL="\033[33m"; RST="\033[0m"
strip_ansi() { sed -E 's/\x1b\[[0-9;]*m//g'; }

same=0; diff_n=0; unsup=0
declare -a UNSUP=()

for src in "$ROOT"/examples/*.g "$ROOT"/tests/cases/*.g; do
    [ -e "$src" ] || continue
    name="$(basename "$src" .g)"
    infile="$ROOT/tests/input/$name.txt"

    "$GC" "$src" -o "$TMP/$name.bin" >/dev/null 2>&1 || continue
    if [ -f "$infile" ]; then "$TMP/$name.bin" <"$infile" >"$TMP/$name.c.out" 2>&1
    else "$TMP/$name.bin" </dev/null >"$TMP/$name.c.out" 2>&1; fi
    c_rc=$?

    if [ -f "$infile" ]; then
        "$GC" "$src" --interp <"$infile" >"$TMP/$name.i.out" 2>"$TMP/$name.i.err"
    else
        "$GC" "$src" --interp </dev/null >"$TMP/$name.i.out" 2>"$TMP/$name.i.err"
    fi
    i_rc=$?

    # rc=3 = trình thông dịch báo "chưa mô phỏng" -> chưa hỗ trợ, không phải sai
    if [ "$i_rc" = "3" ]; then
        unsup=$((unsup+1))
        UNSUP+=("$name: $(strip_ansi <"$TMP/$name.i.err" | head -1 | cut -c1-76)")
        continue
    fi

    # Panic ghi ra stderr ở cả hai bên -> gộp để so cho công bằng.
    cat "$TMP/$name.i.err" >> "$TMP/$name.i.out"

    if [ "$c_rc" != "$i_rc" ]; then
        echo -e "${RED}KHÁC MÃ THOÁT${RST}  $name (C=$c_rc, interp=$i_rc)"
        diff_n=$((diff_n+1)); continue
    fi
    if ! diff -q <(strip_ansi <"$TMP/$name.c.out") \
                 <(strip_ansi <"$TMP/$name.i.out") >/dev/null; then
        echo -e "${RED}KHÁC ĐẦU RA${RST}   $name"
        diff <(strip_ansi <"$TMP/$name.c.out") \
             <(strip_ansi <"$TMP/$name.i.out") | head -6
        diff_n=$((diff_n+1)); continue
    fi
    echo -e "${GREEN}KHỚP${RST}        $name"
    same=$((same+1))
done

echo "-------------------------"
if [ "${#UNSUP[@]}" -gt 0 ]; then
    echo -e "${YEL}Trình thông dịch chưa mô phỏng (${#UNSUP[@]}):${RST}"
    printf '  %s\n' "${UNSUP[@]}" | head -25
fi
echo -e "Interp diff: ${GREEN}$same khớp${RST}, ${RED}$diff_n khác${RST}, ${YEL}$unsup chưa hỗ trợ${RST}"
[ "$diff_n" -eq 0 ]
