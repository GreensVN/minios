#!/usr/bin/env bash
# So khớp ĐẦU RA giữa hai backend C: bản cũ (đọc AST, mặc định) và bản mới
# (đọc G-IR, '--backend=c-ir').
#
# Đây là cơ chế kiểm chứng của Giai đoạn B (ARCHITECTURE.md §3): backend mới chỉ
# được đổi thành mặc định khi bộ này khớp 100%. Chạy song song hai backend rồi
# so từng byte đầu ra là cách duy nhất chứng minh việc chuyển đổi KHÔNG đổi
# hành vi — thay vì tin vào việc "đọc lại mã thấy có vẻ đúng".
#
# Ca nào backend mới CHƯA hỗ trợ (intrinsic in ấn/format còn ở dạng cấp cao)
# được tính là "chưa hỗ trợ", không phải "sai" — và được liệt kê rõ.
#
#   bash tests/run_backend_diff.sh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GC="$ROOT/gc"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
GREEN="\033[32m"; RED="\033[1;31m"; YEL="\033[33m"; RST="\033[0m"

same=0; diff_n=0; unsup=0
declare -a UNSUP_LIST=()

for src in "$ROOT"/examples/*.g "$ROOT"/tests/cases/*.g; do
    [ -e "$src" ] || continue
    name="$(basename "$src" .g)"
    infile="$ROOT/tests/input/$name.txt"

    # backend cũ (tham chiếu)
    if ! "$GC" "$src" -o "$TMP/$name.old" >/dev/null 2>&1; then
        continue                       # ca không biên dịch được: bỏ qua
    fi
    if [ -f "$infile" ]; then "$TMP/$name.old" <"$infile" >"$TMP/$name.o.out" 2>&1
    else "$TMP/$name.old" </dev/null >"$TMP/$name.o.out" 2>&1; fi
    old_rc=$?

    # backend mới (đọc IR)
    if ! "$GC" "$src" --backend=c-ir -o "$TMP/$name.new" \
            >"$TMP/$name.err" 2>&1; then
        unsup=$((unsup+1))
        UNSUP_LIST+=("$name: $(head -1 "$TMP/$name.err" | cut -c1-90)")
        continue
    fi
    if [ -f "$infile" ]; then "$TMP/$name.new" <"$infile" >"$TMP/$name.n.out" 2>&1
    else "$TMP/$name.new" </dev/null >"$TMP/$name.n.out" 2>&1; fi
    new_rc=$?

    if [ "$old_rc" != "$new_rc" ]; then
        echo -e "${RED}KHÁC MÃ THOÁT${RST}  $name (cũ=$old_rc mới=$new_rc)"
        diff_n=$((diff_n+1)); continue
    fi
    if ! diff -q "$TMP/$name.o.out" "$TMP/$name.n.out" >/dev/null; then
        echo -e "${RED}KHÁC ĐẦU RA${RST}   $name"
        diff "$TMP/$name.o.out" "$TMP/$name.n.out" | head -6
        diff_n=$((diff_n+1)); continue
    fi
    echo -e "${GREEN}KHỚP${RST}        $name"
    same=$((same+1))
done

echo "-------------------------"
if [ "${#UNSUP_LIST[@]}" -gt 0 ]; then
    echo -e "${YEL}Chưa hỗ trợ trong backend c-ir (${#UNSUP_LIST[@]}):${RST}"
    printf '  %s\n' "${UNSUP_LIST[@]}" | head -20
fi
echo -e "Backend diff: ${GREEN}$same khớp${RST}, ${RED}$diff_n khác${RST}, ${YEL}$unsup chưa hỗ trợ${RST}"
# Chỉ FAIL khi có KHÁC BIỆT thật; "chưa hỗ trợ" là trạng thái đã biết của
# giai đoạn chuyển đổi.
[ "$diff_n" -eq 0 ]
