#!/usr/bin/env bash
# Kiểm các lỗi LÚC CHẠY phải PANIC (mã thoát 101) thay vì âm thầm đọc/ghi bậy.
#
# Vì sao cần bộ riêng: bộ test chính so khớp toàn bộ đầu ra, mà thông báo panic
# có chứa ĐƯỜNG DẪN file nên không so khớp trực tiếp được. Ở đây chỉ kiểm
# (1) mã thoát 101 và (2) thông báo khớp một mẫu.
#
# Mỗi ca: tests/panic/<tên>.g  +  tests/panic/<tên>.txt (mẫu grep -F)
#
#   bash tests/run_panic.sh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GC="$ROOT/gc"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
GREEN="\033[32m"; RED="\033[1;31m"; RST="\033[0m"
strip_ansi() { sed -E 's/\x1b\[[0-9;]*m//g'; }

pass=0; fail=0
for src in "$ROOT"/tests/panic/*.g; do
    [ -e "$src" ] || continue
    name="$(basename "$src" .g)"
    want="$ROOT/tests/panic/$name.txt"
    bin="$TMP/$name"
    if ! "$GC" "$src" -o "$bin" >"$TMP/$name.cc" 2>&1; then
        echo -e "${RED}BIÊN DỊCH LỖI${RST}  $name"
        cat "$TMP/$name.cc"; fail=$((fail+1)); continue
    fi
    # Lấy mã thoát của CHÍNH chương trình, không phải của strip_ansi trong ống.
    "$bin" </dev/null >"$TMP/$name.out" 2>&1
    rc=$?
    out="$(strip_ansi <"$TMP/$name.out")"
    if [ "$rc" != "101" ]; then
        echo -e "${RED}FAIL${RST}         $name (mã thoát $rc, cần 101)"
        echo "$out" | head -3; fail=$((fail+1)); continue
    fi
    if [ -f "$want" ] && ! grep -qF "$(cat "$want")" <<<"$out"; then
        echo -e "${RED}FAIL${RST}         $name (thông báo không khớp)"
        echo "  mong đợi chứa: $(cat "$want")"
        echo "  thực tế:       $(echo "$out" | head -1)"
        fail=$((fail+1)); continue
    fi
    # Với --no-checks, CÙNG chương trình đó phải KHÔNG còn panic của G (người
    # dùng chủ động bỏ kiểm tra). Lúc này hành vi là UB của C — có thể chạy
    # tiếp, có thể SIGFPE/SIGILL — nên chỉ khẳng định "không phải 101" và nuốt
    # mọi tín hiệu của shell.
    if "$GC" "$src" --no-checks -o "$bin.nc" >/dev/null 2>&1; then
        nc_rc=0
        # 'set +m' + subshell: chặn shell in "Illegal instruction" khi UB gây
        # tín hiệu (đúng như mong đợi với --no-checks trên chia-0).
        ( set +m; exec 2>/dev/null; "$bin.nc" </dev/null >/dev/null 2>&1 ) \
            || nc_rc=$?
        if [ "$nc_rc" = "101" ]; then
            echo -e "${RED}FAIL${RST}         $name (--no-checks vẫn panic)"
            fail=$((fail+1)); continue
        fi
    fi
    echo -e "${GREEN}PASS${RST}         $name"
    pass=$((pass+1))
done

echo "-------------------------"
echo -e "Panic: ${GREEN}$pass pass${RST}, ${RED}$fail fail${RST}"
[ "$fail" -eq 0 ]
