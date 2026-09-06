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
    # Không ca test nào được phát CẢNH BÁO (vd biến khai báo mà không dùng):
    # giữ toàn bộ ví dụ/test sạch, và bảo đảm cảnh báo không bị dương tính giả.
    if grep -q "cảnh báo" "$TMP/$name.cc"; then
        echo -e "${RED}CÓ CẢNH BÁO${RST}    $name"
        strip_ansi < "$TMP/$name.cc" | grep "cảnh báo" | head -5
        fail=$((fail+1)); return
    fi
    # Mã C sinh ra phải sạch dưới -Wall -Wextra (bắt lỗi SINH MÃ sớm: ép kiểu
    # sai, so sánh signed/unsigned, biến C thừa...).
    if command -v gcc >/dev/null 2>&1; then
        if "$GC" "$src" --emit-c -o "$TMP/$name.gen.c" >/dev/null 2>&1; then
            local cw
            cw="$(gcc -std=gnu11 -I "$ROOT/runtime" -Wall -Wextra \
                      -Wno-unused-variable -Wno-unused-const-variable \
                      -Wno-unused-but-set-variable \
                      -c "$TMP/$name.gen.c" -o /dev/null 2>&1)"
            if [ -n "$cw" ]; then
                echo -e "${RED}C CẢNH BÁO${RST}     $name"
                echo "$cw" | head -6
                fail=$((fail+1)); return
            fi
        fi
    fi
    # Đầu vào tuỳ chọn: tests/input/<tên>.txt được đưa vào stdin (cho chương trình
    # đọc input). Nếu không có, dùng /dev/null để EOF ngay (tất định, không treo).
    local infile="$ROOT/tests/input/$name.txt"
    if [ -f "$infile" ]; then
        "$bin" <"$infile" >"$got" 2>&1
    else
        "$bin" </dev/null >"$got" 2>&1
    fi

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
        local extra=""
        [ -f "$exp" ] && extra="$(tail -n +2 "$exp")"
        echo "$got" | grep -oE 'lỗi [^:]+: .*' | head -1 > "$exp"
        [ -n "$extra" ] && echo "$extra" >> "$exp"
        echo -e "${YEL}BLESS${RST}        $name (fail)"; return
    fi
    if [ ! -f "$exp" ]; then
        echo -e "${YEL}THIẾU KQ${RST}     $name (fail) (chạy --bless để tạo)"
        fail=$((fail+1)); return
    fi
    # Mỗi dòng của file mong đợi phải xuất hiện trong đầu ra (dòng 1 do --bless
    # sinh; các dòng thêm tay — vd 'gc: 4 lỗi' — kiểm phục hồi nhiều lỗi).
    local ok=1 want
    while IFS= read -r want; do
        [ -z "$want" ] && continue
        if ! echo "$got" | grep -qF "$want"; then
            ok=0
            echo -e "${RED}FAIL${RST}         $name (fail)"
            echo "  mong đợi chứa: $want"
            echo "  thực tế:       $(echo "$got" | head -1)"
            break
        fi
    done < "$exp"
    if [ "$ok" = "1" ]; then
        echo -e "${GREEN}PASS${RST}         $name (fail)"
        pass=$((pass+1))
    else
        fail=$((fail+1))
    fi
}

# Test "freestanding": chương trình phát triển hệ điều hành (kernel/firmware)
# phải BIÊN DỊCH được ở chế độ --freestanding -c (không libc) thành file đối
# tượng. KHÔNG chạy (có thể chứa lệnh đặc quyền hlt/cli/inb...). Khoá lại khả
# năng biên dịch không-libc của các intrinsic OS, @attributes, extern, asm mở rộng.
run_fs() {
    local src="$1"
    local name; name="$(basename "$src" .g)"
    if "$GC" "$src" --freestanding -c -o "$TMP/$name.o" >"$TMP/$name.fs" 2>&1; then
        echo -e "${GREEN}PASS${RST}         $name (freestanding)"
        pass=$((pass+1))
    else
        echo -e "${RED}FAIL${RST}         $name (freestanding)"
        cat "$TMP/$name.fs"
        fail=$((fail+1))
    fi
}

# Test "phải lỗi ở FREESTANDING": chương trình HỢP LỆ khi hosted nhưng phải bị
# checker từ chối ở '--freestanding' (dùng built-in cần libc). Khoá lại việc lỗi
# được báo ở tầng G thay vì rò rỉ lỗi biên dịch C thô.
run_fail_fs() {
    local src="$1"
    local name; name="$(basename "$src" .g)"
    local exp="$ROOT/tests/fail_fs/$name.txt"
    local got; got="$("$GC" "$src" --freestanding --check 2>&1 | strip_ansi)"
    if echo "$got" | grep -q "không phát hiện lỗi"; then
        echo -e "${RED}PHẢI LỖI NHƯNG OK${RST}  $name (freestanding)"
        fail=$((fail+1)); return
    fi
    # Cùng chương trình đó phải biên dịch được ở chế độ HOSTED.
    if ! "$GC" "$src" --check >/dev/null 2>&1; then
        echo -e "${RED}FAIL${RST}         $name (fail_fs: hosted cũng lỗi)"
        fail=$((fail+1)); return
    fi
    if [ "$bless" = "1" ]; then
        mkdir -p "$ROOT/tests/fail_fs"
        echo "$got" | grep -oE 'lỗi [^:]+: .*' | head -1 > "$exp"
        echo -e "${YEL}BLESS${RST}        $name (fail_fs)"; return
    fi
    if [ ! -f "$exp" ]; then
        echo -e "${YEL}THIẾU KQ${RST}     $name (fail_fs) (chạy --bless để tạo)"
        fail=$((fail+1)); return
    fi
    local ok=1 want
    while IFS= read -r want; do
        [ -z "$want" ] && continue
        if ! echo "$got" | grep -qF "$want"; then
            ok=0
            echo -e "${RED}FAIL${RST}         $name (fail_fs)"
            echo "  mong đợi chứa: $want"
            echo "  thực tế:       $(echo "$got" | head -1)"
            break
        fi
    done < "$exp"
    if [ "$ok" = "1" ]; then
        echo -e "${GREEN}PASS${RST}         $name (fail_fs)"
        pass=$((pass+1))
    else
        fail=$((fail+1))
    fi
}

# Test CẢNH BÁO: chương trình hợp lệ (biên dịch được) nhưng phải phát đúng các
# cảnh báo mong đợi. Khoá lại cả nội dung lẫn việc KHÔNG có dương tính giả.
run_warn() {
    local src="$1"
    local name; name="$(basename "$src" .g)"
    local exp="$ROOT/tests/warn/$name.txt"
    # Chỉ lấy DÒNG TIÊU ĐỀ của mỗi cảnh báo ('file:dòng:cột: cảnh báo ...') —
    # bỏ các dòng trích nguồn/caret bên dưới (chúng cũng chứa từ 'cảnh báo').
    local got; got="$("$GC" "$src" --check 2>&1 | strip_ansi \
                      | grep -oE 'cảnh báo [^:]+: .*')"
    if [ "$bless" = "1" ]; then
        mkdir -p "$ROOT/tests/warn"
        echo "$got" | grep -oE 'cảnh báo [^:]+: .*' > "$exp"
        echo -e "${YEL}BLESS${RST}        $name (warn)"; return
    fi
    if [ ! -f "$exp" ]; then
        echo -e "${YEL}THIẾU KQ${RST}     $name (warn) (chạy --bless để tạo)"
        fail=$((fail+1)); return
    fi
    # Số cảnh báo phải KHỚP CHÍNH XÁC (bắt dương tính giả), và mỗi dòng mong đợi
    # phải xuất hiện.
    local want_n got_n
    want_n="$(grep -c . "$exp")"
    got_n="$(echo "$got" | grep -c .)"
    if [ "$want_n" != "$got_n" ]; then
        echo -e "${RED}FAIL${RST}         $name (warn: mong $want_n cảnh báo, nhận $got_n)"
        echo "$got" | head -6
        fail=$((fail+1)); return
    fi
    local ok=1 want
    while IFS= read -r want; do
        [ -z "$want" ] && continue
        if ! echo "$got" | grep -qF "$want"; then
            ok=0
            echo -e "${RED}FAIL${RST}         $name (warn)"
            echo "  mong đợi chứa: $want"
            fail=$((fail+1)); break
        fi
    done < "$exp"
    if [ "$ok" = "1" ]; then
        echo -e "${GREEN}PASS${RST}         $name (warn)"
        pass=$((pass+1))
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
for src in "$ROOT"/tests/freestanding/*.g "$ROOT"/examples/kernel/*.g; do
    [ -e "$src" ] || continue
    run_fs "$src"
done
for src in "$ROOT"/tests/fail_fs/*.g; do
    [ -e "$src" ] || continue
    run_fail_fs "$src"
done
for src in "$ROOT"/tests/warn/*.g; do
    [ -e "$src" ] || continue
    run_warn "$src"
done

echo "-------------------------"
if [ "$bless" = "1" ]; then
    echo "Đã cập nhật kết quả mong đợi."
else
    echo -e "Kết quả: ${GREEN}$pass pass${RST}, ${RED}$fail fail${RST}"
fi
[ "$fail" -eq 0 ]
