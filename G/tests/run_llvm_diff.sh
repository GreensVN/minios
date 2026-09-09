#!/usr/bin/env bash
# So khớp backend LLVM với backend C (tham chiếu).
#
# Backend LLVM đọc CÙNG G-IR như backend C, nên bộ này kiểm phần DỊCH IR->LLVM.
# Ca chưa hạ được bị TỪ CHỐI tường minh (không sinh mã sai) và tính là "chưa hỗ
# trợ", giống cách đã làm với c-ir.
#
#   bash tests/run_llvm_diff.sh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GC="$ROOT/gc"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
GREEN="\033[32m"; RED="\033[1;31m"; YEL="\033[33m"; RST="\033[0m"
same=0; diff_n=0; unsup=0
for src in "$ROOT"/examples/*.g "$ROOT"/tests/cases/*.g; do
    [ -e "$src" ] || continue
    name="$(basename "$src" .g)"
    infile="$ROOT/tests/input/$name.txt"; IN=/dev/null
    [ -f "$infile" ] && IN="$infile"
    "$GC" "$src" -o "$TMP/$name.c" >/dev/null 2>&1 || continue
    "$TMP/$name.c" <"$IN" >"$TMP/$name.co" 2>&1; crc=$?
    if ! "$GC" "$src" --backend=llvm -o "$TMP/$name.l" >/dev/null 2>&1; then
        unsup=$((unsup+1)); continue
    fi
    "$TMP/$name.l" <"$IN" >"$TMP/$name.lo" 2>&1; lrc=$?
    if [ "$crc" != "$lrc" ]; then
        echo -e "${RED}KHÁC MÃ THOÁT${RST}  $name (C=$crc, LLVM=$lrc)"
        diff_n=$((diff_n+1)); continue
    fi
    if ! diff -q "$TMP/$name.co" "$TMP/$name.lo" >/dev/null; then
        echo -e "${RED}KHÁC ĐẦU RA${RST}   $name"
        diff "$TMP/$name.co" "$TMP/$name.lo" | head -6
        diff_n=$((diff_n+1)); continue
    fi
    echo -e "${GREEN}KHỚP${RST}        $name"
    same=$((same+1))
done
echo "-------------------------"
echo -e "LLVM diff: ${GREEN}$same khớp${RST}, ${RED}$diff_n khác${RST}, ${YEL}$unsup chưa hỗ trợ${RST}"
[ "$diff_n" -eq 0 ]
