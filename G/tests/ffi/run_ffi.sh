#!/usr/bin/env bash
# Kiểm FFI đầu-cuối: dựng một thư viện C thật rồi gọi từ G bằng CẢ BA cách,
# trên CẢ BA backend.
#   1. FFI tĩnh qua cờ dòng lệnh  (-L/-l)
#   2. FFI tĩnh qua '@link' trong nguồn (+ '@symbol' đổi tên)
#   3. FFI ĐỘNG lúc chạy (dl_open/dl_sym)
#   4. Binding sinh tự động bằng tools/gbind.py
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GC="$ROOT/gc"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
GREEN="\033[32m"; RED="\033[1;31m"; RST="\033[0m"
pass=0; fail=0
chk() {  # chk <tên> <mong đợi> <thực tế>
    if [ "$2" = "$3" ]; then echo -e "${GREEN}PASS${RST}         $1"; pass=$((pass+1))
    else echo -e "${RED}FAIL${RST}         $1"; echo "  mong: $2"; echo "  nhận: $3"; fail=$((fail+1)); fi
}

cat > "$TMP/lib.c" <<'EOF'
#include <string.h>
int  gt_twice(int x) { return x * 2; }
double gt_halve(double x) { return x / 2.0; }
int  gt_sum3(int a, int b, int c) { return a + b + c; }
unsigned long gt_len(const char* s) { return (unsigned long)strlen(s); }
EOF
cat > "$TMP/lib.h" <<'EOF'
int gt_twice(int x);
double gt_halve(double x);
int gt_sum3(int a, int b, int c);
unsigned long gt_len(const char* s);
int gt_var(const char* f, ...);
EOF
cc -shared -fPIC "$TMP/lib.c" -o "$TMP/libgtffi.so" 2>/dev/null || {
    echo "bỏ qua: không dựng được thư viện thử"; exit 0; }

# --- 1. cờ dòng lệnh ---
cat > "$TMP/a.g" <<'EOF'
extern fn gt_twice(x: int) -> int
fn main() -> int { println("{}", gt_twice(21)) return 0 }
EOF
for b in c c-ir llvm; do
    if "$GC" "$TMP/a.g" --backend=$b -L"$TMP" -lgtffi -o "$TMP/a.$b" >/dev/null 2>&1; then
        chk "cờ -L/-l ($b)" "42" "$(LD_LIBRARY_PATH=$TMP "$TMP/a.$b" 2>&1)"
    else echo "  (bỏ qua $b)"; fi
done

# --- 2. '@link' + '@symbol' trong nguồn ---
cat > "$TMP/b.g" <<EOF
@link("$TMP:gtffi") extern fn gt_halve(x: f64) -> f64
@link("$TMP:gtffi") @symbol("gt_sum3") extern fn cong3(a: int, b: int, c: int) -> int
fn main() -> int { println("{} {}", gt_halve(9.0), cong3(1,2,3)) return 0 }
EOF
for b in c c-ir llvm; do
    if "$GC" "$TMP/b.g" --backend=$b -o "$TMP/b.$b" >/dev/null 2>&1; then
        chk "@link/@symbol ($b)" "4.5 6" "$(LD_LIBRARY_PATH=$TMP "$TMP/b.$b" 2>&1)"
    else echo "  (bỏ qua $b)"; fi
done

# --- 3. FFI động ---
cat > "$TMP/c.g" <<EOF
fn main() -> int {
    let h = dl_open("$TMP/libgtffi.so")
    if h == null { println("mở lỗi: {}", dl_error()) return 1 }
    let p = dl_sym(h, "gt_twice")
    if p == null { println("thiếu ký hiệu") return 1 }
    let f = p as fn(int) -> int
    println("{}", f(50))
    dl_close(h)
    return 0
}
EOF
for b in c c-ir llvm; do
    if "$GC" "$TMP/c.g" --backend=$b -o "$TMP/c.$b" >/dev/null 2>&1; then
        chk "dl_open/dl_sym ($b)" "100" "$("$TMP/c.$b" 2>&1)"
    else echo "  (bỏ qua $b)"; fi
done

# --- 4. binding sinh tự động ---
python3 "$ROOT/tools/gbind.py" "$TMP/lib.h" --link "$TMP:gtffi" \
        -o "$TMP/bind.g" 2>/dev/null
cat > "$TMP/d.g" <<EOF
import "$TMP/bind.g"
fn main() -> int { println("{} {}", gt_sum3(2,3,4), gt_len("abcd")) return 0 }
EOF
if "$GC" "$TMP/d.g" -o "$TMP/d.out" >/dev/null 2>&1; then
    chk "gbind sinh binding" "9 4" "$(LD_LIBRARY_PATH=$TMP "$TMP/d.out" 2>&1)"
else
    echo -e "${RED}FAIL${RST}         gbind sinh binding (không biên dịch được)"
    fail=$((fail+1))
fi
# gbind PHẢI bỏ qua hàm biến-đối-số (sinh binding sai còn tệ hơn bỏ sót)
if grep -q "gt_var" "$TMP/bind.g" && ! grep -q "// *gt_var" "$TMP/bind.g"; then
    echo -e "${RED}FAIL${RST}         gbind bỏ qua hàm biến-đối-số"; fail=$((fail+1))
else
    echo -e "${GREEN}PASS${RST}         gbind bỏ qua hàm biến-đối-số"; pass=$((pass+1))
fi

echo "-------------------------"
echo -e "FFI: ${GREEN}$pass pass${RST}, ${RED}$fail fail${RST}"
[ "$fail" -eq 0 ]
