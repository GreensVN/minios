# Ngôn ngữ lập trình G

**G** là một ngôn ngữ lập trình biên dịch (compiled), hệ thống (systems), kết hợp tinh hoa của **5 ngôn ngữ** — với **type-checker**, **suy luận kiểu**, **method (impl)**, **con trỏ hàm**, **module**, **thư viện chuẩn** và **chẩn đoán lỗi đẹp**.

| Ảnh hưởng | Đóng góp cho G |
|-----------|----------------|
| **Assembly** | Khối `asm { }` chèn lệnh máy thô |
| **C** | Con trỏ, struct, kiểu thấp cấp, cấp phát thủ công, làm *backend* |
| **C++** | Biên dịch qua trình C/C++ tối ưu, `static inline`, prototype |
| **Rust** | `let` bất biến mặc định, `let mut`, `match`, `for i in a..b`, `impl`, `loop` |
| **Zig** | `defer` (LIFO), `comptime`, định dạng in `{}`/`{d}`/`{s}`, tường minh |

Triết lý: **frontend hiện đại (Rust/Zig) → type-check → biên dịch xuống C → mã máy native qua GCC/Clang.**

```
 source.g ─► Lexer ─► Parser ─► [gộp module] ─► Checker (kiểu) ─► Codegen ─► gcc/clang ─► mã máy
            (+ASI)    (AST)       (import)        (suy luận)        (C)
```

---

## Cài đặt & chạy

Cần `python3` và `gcc` hoặc `clang`.

```bash
cd G
./gc examples/showcase.g --run      # biên dịch + chạy
./gc examples/oop.g -o oop && ./oop # tạo file thực thi
./gc examples/fib.g --emit-c        # xem mã C trung gian
./tests/run_tests.sh                # chạy bộ test
```

### Tùy chọn của `gc`

| Cờ | Ý nghĩa |
|----|---------|
| `-o <file>` | Tên file thực thi đầu ra |
| `-r`, `--run` | Biên dịch xong chạy luôn |
| `--emit-c` | Chỉ in/ghi mã C |
| `--keep-c` | Giữ lại file `.c` trung gian |
| `--check` | Chỉ kiểm tra kiểu, không sinh mã |
| `--tokens` | In danh sách token (debug lexer) |
| `--ast` | In cây cú pháp AST (debug parser) |
| `--cc <cc>` | Chọn trình biên dịch C |
| `-O <0..3>` | Mức tối ưu (mặc định 2) |
| `--no-checks` | Tắt kiểm tra lúc chạy (biên mảng tĩnh, chia 0) — nhanh hơn nhưng lỗi thành UB |

---

## Tính năng & cú pháp

### Hàm, biến, kiểu
```g
fn add(a: int, b: int) -> int { return a + b }

let x: int = 10          // bất biến (const)
let mut y = 0            // thay đổi được, kiểu tự suy luận
const PI: f64 = 3.14159  // hằng toàn cục
```
Kiểu: `int i8..i64 u8..u64 usize isize f32 f64 bool char str void`, con trỏ `*T`, mảng `[N]T` / `[]T`.

### Điều khiển luồng
```g
if c { } else if d { } else { }
while cond { }
loop { ... break }                 // vòng lặp vô hạn (Rust)
for i in 0..10 { }                 // 0..9
for i in 0..=10 step 2 { }         // bao gồm 10, bước 2
for i in 10..0 step -1 { }         // đếm ngược (step âm)
let p = (n % 2 == 0) ? "chẵn" : "lẻ"   // ternary
```
Vòng `for ... step` chấp nhận **bước âm** (đếm ngược); khi dấu của bước chỉ biết
lúc chạy, chiều so sánh được chọn tự động.

### `match` (Rust) — nhiều pattern, khoảng, khớp chuỗi, mặc định
```g
match score {
    9 | 10   => { return "Xuất sắc" }   // nhiều pattern (|)
    80..=100 => { return "A" }          // khoảng bao gồm (lo..=hi)
    11..80   => { return "B" }          // khoảng nửa mở (lo..hi)
    _        => { return "Yếu" }
}
match cmd {                 // tự dùng strcmp cho chuỗi
    "quit" => { ... }
    _      => { ... }
}
match dir {                 // match enum phủ hết variant: KHÔNG cần '_'
    North => { return "lên" }
    South => { return "xuống" }
}
```
Khoảng dùng được cho cả `char`: `'a'..='z' => { ... }`.

**Guard `if` và binding (kiểu Rust):** một định danh trần *bắt* giá trị subject
vào tên mới, và `if <điều kiện>` lọc thêm — nhánh **rớt xuống** nhánh kế khi guard sai:
```g
match n {
    x if x < 0   => { return "âm" }        // binding 'x' + guard
    0            => { return "không" }
    x if x > 100 => { return "lớn" }
    x            => { return "thường" }     // binding mặc định, dùng được 'x'
}
```

### `struct`, `enum`, và `impl` (method)
```g
struct Rect { w: int, h: int }
enum Color { Red, Green = 5, Blue }

impl Rect {
    fn area(self) -> int { return self.w * self.h }  // self: *Rect, '.' tự thành '->'
    fn scale(self, k: int) { self.w = self.w * k }
}

let mut r = Rect { w: 3, h: 4 }
println("{}", r.area())   // -> 12
r.scale(2)
```

**Method tĩnh, `impl` trên enum, tên biến thể đầy đủ, so sánh struct:**
```g
impl Rect {
    fn square(n: int) -> Rect { return Rect { w: n, h: n } }   // không có self
}
impl Color {
    fn is_warm(self) -> bool { return *self == Color.Red }     // self: *Color
    fn name(self) -> str { match *self { Red => { return "red" } _ => { return "?" } } }
}
let sq = Rect.square(3)               // gọi qua tên kiểu
println("{}", sq == Rect { w: 3, h: 3 })   // struct '=='/'!=' so theo từng trường (đệ quy)
println("{}", Color.Red.is_warm())    // 'Enum.Variant' — rõ ràng hơn tên trần 'Red'
```

### Con trỏ & bộ nhớ động
```g
let mut v = 42
let p: *int = &v
*p = 100                     // v == 100

let mut buf: *int = g_alloc(int, 100)   // calloc
buf[0] = 1
g_free(buf)
```

### Mảng
```g
let nums: [5]int = [10, 20, 30, 40, 50]
for i in 0..len(nums) { ... }    // len() dùng được cho mảng tĩnh

const CAP: int = 8
let buf: [CAP]int = ...          // cỡ = tên hằng
let pad: [CAP + 1]int = ...      // cỡ = BIỂU THỨC HẰNG ([N+1], [2*M], [CAP/2]...)
let grid: [3][CAP]int = ...      // nhiều chiều với chiều biểu thức hằng

let ptrs: [3]*int = [&a, &b, &c] // MẢNG CÁC CON TRỎ ([N]*T, khác '*[N]T')
```

### Con trỏ hàm (hàm bậc cao)
Kiểu `fn(P1, P2, ...) -> R` cho phép truyền/lưu/trả về hàm — nền tảng cho callback,
map/filter/reduce, bảng điều phối:
```g
fn add(a: int, b: int) -> int { return a + b }
fn mul(a: int, b: int) -> int { return a * b }
fn sqr(x: int) -> int { return x * x }
fn inc(x: int) -> int { return x + 1 }

let f: fn(int, int) -> int = add        // biến con trỏ hàm
println("{}", f(3, 4))                   // 7

let table: [2]fn(int) -> int = [sqr, inc]       // mảng con trỏ hàm

// nhận con trỏ hàm làm tham số (hàm bậc cao)
fn apply(a: *int, n: int, g: fn(int) -> int) {
    for i in 0..n { a[i] = g(a[i]) }
}

// trả về con trỏ hàm
fn pick(op: int) -> fn(int, int) -> int {
    if op == 0 { return add }
    return mul
}
```
`std` cung cấp sẵn `map_into · filter_into · fold · count_if · any · all · find_first`.
So sánh được với `null`; in `{}` ra địa chỉ (`%p`). (Chưa có closure bắt biến.)

### `defer` (Zig) — chạy khi rời hàm theo thứ tự LIFO
```g
defer println("chạy thứ 2")
defer println("chạy thứ 1")    // in trước
```

### Inline Assembly (cơ bản & **mở rộng** kiểu GCC)
```g
asm { "nop" "nop" }                 // cơ bản: ghép chuỗi lệnh

// MỞ RỘNG — có toán hạng (đọc/ghi thanh ghi, MSR, control register...):
fn read_cr0() -> u64 {
    let mut v: u64 = 0
    asm {
        "mov %%cr0, %0"
        : "=r"(v)                   // outputs:  "ràng buộc"(ô_nhớ)
    }
    return v
}
asm {
    "lgdt (%0)"
    :                               // (không output)
    : "r"(gdt_ptr)                  // inputs:   "ràng buộc"(biểu_thức)
    : "memory"                      // clobbers: danh sách chuỗi
}
```
Toán hạng output phải là **ô nhớ khả biến** (compiler kiểm tra); biến trong toán
hạng được phân giải đúng tên C (shadowing). Xem thêm phần **Phát triển hệ điều hành**.

### `comptime` (Zig) — gợi ý tính/inline lúc biên dịch
```g
comptime fn square(n: int) -> int { return n * n }
```

### In ra màn hình — định dạng kiểu Zig (tự suy luận theo kiểu)
`print` / `println` (stdout) và `eprint` / `eprintln` (stderr).

| Placeholder | Ý nghĩa |
|-------------|---------|
| `{}` | **Tự suy luận** theo kiểu đối số (kể cả `bool` → `true`/`false`) |
| `{d}` `{ld}` | số nguyên / 64-bit |
| `{u}` `{lu}` | unsigned / 64-bit |
| `{f}` | số thực |
| `{s}` `{c}` | chuỗi / ký tự |
| `{x}` `{X}` `{o}` | hex / HEX / bát phân |
| `{b}` | bool → true/false; **số nguyên → nhị phân** (`{:08b}` đệm 0) |
| `{{` `}}` | dấu `{` `}` literal |

**Width / precision / căn lề** (kiểu Zig/Rust) qua `{key:flags}`:

| Ví dụ | Kết quả |
|-------|---------|
| `{d:5}` | `"   42"` (width tối thiểu 5, căn phải) |
| `{d:<5}` | `"42   "` (căn trái) |
| `{d:05}` | `"00042"` (đệm số 0) |
| `{f:.2}` | `"3.14"` (2 chữ số sau dấu phẩy) |
| `{f:8.3}` | `"   3.142"` (width 8, precision 3) |
| `{s:>10}` | `"        hi"` (chuỗi căn phải) |
| `{:^7}` | `"  ab   "` (căn giữa) |

> Compiler **kiểm tra số placeholder khớp số đối số** *và* **khớp kiểu với
> specifier** (vd `{s}` cho số, `{d}` cho float đều báo lỗi).

**In trực tiếp `struct` và `enum`** với `{}` (kiểu `{:?}` của Rust) — không cần in
từng trường:
```g
enum Color { Red, Green, Blue }
struct Point { x: int, y: int }
struct Box { lo: Point, hi: Point, color: Color }

println("{}", Point { x: 3, y: 4 })   // Point { x: 3, y: 4 }
println("{}", Green)                   // Green  (TÊN biến thể, không phải số)
println("{}", Box { lo: Point{x:0,y:0}, hi: Point{x:9,y:9}, color: Blue })
// -> Box { lo: Point { x: 0, y: 0 }, hi: Point { x: 9, y: 9 }, color: Blue }
```
Struct lồng được in **đệ quy**; enum in ra **tên biến thể** (dùng `{d}` nếu muốn số
nguyên). Đối số `print`/`format` được **đánh giá trái-sang-phải, đúng một lần**.

**`format(...)` (kiểu Zig `std.fmt`)** — dựng một **chuỗi mới trên heap** với đúng
cú pháp định dạng như trên (đối số được đánh giá đúng *một lần*); nhớ `g_free`:
```g
let s = format("[{d:05}] {s} ≈ {f:.2}", 42, "pi", 3.14159)  // "[00042] pi ≈ 3.14"
println("{s}", s)
g_free(s)
```

### Đọc đầu vào (stdin) — chương trình tương tác
`import std` rồi dùng:
```g
let n = read_int()            // đọc một số nguyên (i64); 0 nếu thất bại/EOF
let x = read_float()          // đọc một số thực (f64)
let line = read_line()        // đọc một dòng -> chuỗi mới trên heap; null khi EOF
if line != null { println("{s}", line); g_free(line) }
while !at_eof() { ... }        // lặp tới khi hết đầu vào
```

### Builtins
`len(x)` · `assert(cond[, msg])` · `assert_eq(a,b)` · `assert_ne(a,b)` · `check_eq(a,b)` · `check_ne(a,b)` · `test_summary()` · `panic(msg)` · `unreachable([msg])` · `todo([msg])` · `min(a,b)` · `max(a,b)` · `abs(x)` · `clamp(x,lo,hi)` · `swap(a,b)` · `typeof(x)` · `dbg(x)` · `format(fmt, ...)` · `g_alloc(T,n)` · `g_realloc(p,T,n)` · `g_free(p)` · `sizeof(T)` · `sizeof(expr)` · `alignof(T)` · `static_assert(cond, "msg")`.

**Intrinsics phát triển hệ điều hành** (xem phần dưới): `memcpy` · `memset` · `memmove` · `memcmp` · `vol_read` · `vol_write` · `popcount` · `clz` · `ctz` · `bswap` · `rotl` · `rotr` · `halt` · `cli` · `sti` · `pause` · `breakpoint` · `io_wait` · `rdtsc` · `inb`/`outb`/`inw`/`outw`/`inl`/`outl`.

- `dbg(x)` in `[dbg dòng N] <giá trị>` ra **stderr** (định dạng theo kiểu suy luận, kể cả struct/enum) rồi **trả lại chính `x`** — chèn vào giữa biểu thức để soi giá trị mà không đổi luồng: `let y = dbg(a + b) * 2`. Đánh giá `x` đúng *một lần*.

- `swap(a, b)` tráo nội dung hai **ô nhớ** cùng kiểu (đánh giá địa chỉ đúng *một lần* — an toàn với `swap(a[i()], a[j()])`); hai ô phải khả biến.
- `typeof(x)` trả về **chuỗi** tên kiểu suy luận (`"i64"`, `"f64"`, `"str"`, `"fn(int) -> int"`...) — hằng lúc biên dịch, không đánh giá `x`.
- `alignof(T)` cho **độ căn lề** của kiểu (bổ trợ `sizeof`) — `alignof(i64)`, `alignof(*Node)`, `alignof([4]int)`.

`unreachable()`/`todo()` không bao giờ trả về (như `panic`) nên thoả mãn phân
tích "mọi nhánh đều return" — tiện cho nhánh mặc định hoặc hàm chưa hoàn thiện.

### Kiểm thử (assert / test framework) — **generic theo mọi kiểu**

G có sẵn một bộ assert/test **generic**: so sánh và hiển thị `trái`/`phải` cho *bất kỳ*
kiểu nào — số, `bool`, `char`, **chuỗi (theo nội dung)**, **enum (theo tên biến thể)**,
và **struct (theo từng trường, đệ quy)**. Thêm một struct/enum mới là **tự động** dùng
được, không cần viết thêm gì (compiler sinh hàm so sánh `_g_eq_T` + bộ in cho mỗi kiểu).

| Builtin | Ý nghĩa |
|---------|---------|
| `assert(cond[, msg])` | đúng/sai luận lý; sai thì **dừng** chương trình |
| `assert_eq(a, b[, msg])` | `a == b`? sai thì in `trái`/`phải` rồi **dừng** |
| `assert_ne(a, b[, msg])` | `a != b`? sai thì **dừng** |
| `check_eq(a, b[, tên])` | như `assert_eq` nhưng **ghi nhận & tiếp tục**, trả `bool` |
| `check_ne(a, b[, tên])` | như `assert_ne` nhưng không dừng |
| `test_summary()` | in tổng kết, trả về **số ca trượt** (dùng làm mã thoát) |

```g
struct Point { x: int, y: int }
fn main() -> int {
    check_eq(2 + 2, 4, "số học")
    check_eq(Point { x: 1, y: 2 }, Point { x: 1, y: 2 }, "struct")  // so theo trường
    check_eq("abc", "abc", "chuỗi")                                  // so theo nội dung
    check_eq(Point { x: 1, y: 2 }, Point { x: 1, y: 9 }, "ca sai")
    return test_summary()        // -> mã thoát = số ca trượt
}
```
Ca trượt in rõ ràng (màu chỉ bật khi ra terminal, ống dẫn/redirect thì sạch):
```
✗ ca sai (dòng 6)
    trái:  Point { x: 1, y: 2 }
    phải:  Point { x: 1, y: 9 }

✗ 1/4 ca test TRƯỢT (3 đạt)
```
> Hai vế phải **cùng kiểu** (compiler bắt `check_eq(1, "x")`); mảng tĩnh trần không
> so trực tiếp được (mất độ dài khi phân rã — so từng phần tử). Mọi output ra
> **stderr** nên không lẫn với output chương trình.

### Module / `import`
```g
import std            // nạp lib/std.g
import "helpers.g"    // nạp file cùng thư mục
```
`lib/std.g` cung cấp:
- **Số học:** `gcd lcm gcd3 ipow is_prime factorial sign is_even is_odd isqrt fib powmod max3 min3 popcount sum_digits count_digits reverse_int is_palindrome_int mod_floor is_power_of_two next_power_of_two leading_zeros trailing_zeros sum_to num_divisors is_perfect totient`
- **Tổ hợp & thống kê:** `ncr npr variance stddev median_sorted` (+ `average`)
- **Toán f64 (libm):** `sqrt cbrt pow floor ceil round trunc fabs fmod sin cos tan atan2 exp log log2 log10 hypot lerp clampf deg2rad rad2deg sigmoid factorial_f sq_f cube_f approx_eq` (+ hằng `G_PI`, `G_E`, `G_TAU`, `G_PHI`)
- **Mảng (số nguyên):** `sum_slice swap_int swap_at bubble_sort insertion_sort quicksort binary_search lower_bound upper_bound max_subarray fill array_copy reverse reverse_range array_max array_min min_index max_index index_of contains count_val is_sorted array_sum array_product array_eq rotate_left dedup_sorted prefix_sum clamp_array`
- **Mảng (số thực f64):** `sum_slice_f average_f array_max_f array_min_f dot norm scale_f fill_f variance_f stddev_f`
- **Tiện ích khác:** `map_range char_at is_vowel ipow_nonneg triangular max3_f min3_f`
- **Bậc cao (con trỏ hàm):** `map_into filter_into fold count_if any all find_first`
- **Chuỗi:** `streq str_len str_concat substr str_contains starts_with ends_with parse_int parse_float int_to_str str_rev to_upper to_lower str_repeat count_char str_index trim replace_char`
- **Ký tự (ASCII):** `is_digit is_upper is_lower is_alpha is_alnum is_space to_upper_char to_lower_char digit_to_int hex_val`
- **Đầu vào (stdin):** `read_line read_int read_float at_eof`
- **Ngẫu nhiên (xorshift64):** `rng_seed rng_seed_time rand_u64 rand_range rand_int rand_float coin_flip shuffle`

> **Quản lý bộ nhớ chuỗi.** Mọi thứ tạo ra chuỗi *mới* đều cấp phát trên heap:
> hàm stdlib (`str_concat`, `substr`, `int_to_str`…), `format(...)`, lát cắt
> `s[a..b]`, và các method `str` biến đổi (`upper`, `lower`, `trim`, `sub`,
> `rev`, `repeat`, `concat`). G **không** có bộ thu gom rác — hãy `g_free` khi
> dùng xong, nếu không sẽ rò rỉ (chương trình ngắn thì vô hại; vòng lặp dài thì
> không). Các method *chỉ đọc* (`len`, `at`, `eq`, `contains`, `starts_with`,
> `ends_with`, `index_of`, `count`, `is_empty`, `to_int`, `to_float`) không cấp
> phát. Kiểm bằng `gcc -fsanitize=address` trên mã C sinh ra.

---

## 🖥️ Phát triển hệ điều hành (OS / kernel / freestanding)

G được thiết kế để viết được phần mềm hệ thống ở mức thấp nhất — kernel, firmware,
trình điều khiển — chạy **không cần libc, không cần hệ điều hành bên dưới**.
👉 Ví dụ hoàn chỉnh, boot được trong QEMU: [`examples/kernel/`](examples/kernel/).

### Chế độ freestanding & xuất file đối tượng

| Cờ | Ý nghĩa |
|----|---------|
| `--freestanding` | Không libc: `-ffreestanding -nostdlib`, không cần `main`, runtime tự cài `memcpy`/`memset`/`memmove`/`memcmp` và `panic`=dừng CPU |
| `-c`, `--compile-obj` | Xuất file đối tượng `.o` (không liên kết) — để ghép với bootloader/linker script |
| `-S`, `--emit-asm` | Xuất mã assembly `.s` |

```bash
gc kernel.g --freestanding -c -o kernel.o     # -> .o không phụ thuộc libc
```
Ở chế độ freestanding, runtime chỉ nạp header tuân thủ freestanding (`stdint`/
`stddef`/`stdbool`); **không có** heap (`g_alloc`), in ấn (`print`), hay đọc stdin
(những thứ này cần libc). Bạn tự viết driver màn hình/serial qua MMIO & cổng I/O.

### MMIO — đọc/ghi bộ nhớ qua `volatile`

Thanh ghi phần cứng ánh xạ vào bộ nhớ có thể đổi giá trị ngoài tầm CPU; phải
truy cập qua `volatile` để trình biên dịch không tối ưu bỏ:
```g
let vga = 0xB8000 as *u16
vol_write(vga + 80, 0x0F41)        // ghi ô VGA (ký tự 'A', màu trắng)
let status = vol_read(uart + 5)    // đọc thanh ghi trạng thái
```

### Cổng I/O & điều khiển CPU (x86)

```g
outb(0x3F8, byte)          inb(0x3F8) -> u8          // 8-bit
outw(port, w)              inw(port)  -> u16         // 16-bit
outl(port, dw)             inl(port)  -> u32         // 32-bit
cli()  sti()               // tắt/bật ngắt
halt()                     // hlt — dừng CPU tới ngắt kế
pause()                    // gợi ý spin-loop (chạy được cả user-space)
breakpoint()               // int3
io_wait()                  // trễ ~1µs
rdtsc() -> u64             // bộ đếm chu kỳ (đọc được ở user-space)
```
> Các lệnh **đặc quyền** (`in*`/`out*`/`hlt`/`cli`/`sti`) chỉ chạy ở **ring 0**
> (kernel). `pause`/`rdtsc`/`breakpoint` thì dùng được cả ở user-space.

### Thao tác bit (tôn trọng **bề rộng kiểu**, giống Rust)

```g
popcount(0xFF)        // 8 — đếm bit 1
clz(1 as u8)          // 7 — số 0 dẫn đầu trong 8 bit (không phải 63!)
ctz(0x80 as u8)       // 7 — số 0 theo sau
bswap(0x1234 as u16)  // 0x3412 — đảo byte
rotl(x, n)  rotr(x, n)// xoay bit trong đúng bề rộng của kiểu x
```

### Bộ nhớ thô

```g
memset(ptr, byte, n)        memcpy(dst, src, n)
memmove(dst, src, n)        memcmp(a, b, n) -> int
```
Hoạt động ở cả hai chế độ — hosted (libc) lẫn freestanding (runtime tự cài).

### Thuộc tính `@` (ABI & bố cục)

| Thuộc tính | Áp cho | Sinh ra |
|------------|--------|---------|
| `@packed` | struct | `__attribute__((packed))` — không đệm (bố cục thanh ghi/giao thức) |
| `@align(N)` | struct/fn/global | `aligned(N)` (N là luỹ thừa 2) |
| `@naked` | fn | `naked` — không prologue/epilogue (handler ngắt, stub) |
| `@noreturn` | fn | `noreturn` |
| `@interrupt` | fn | `interrupt` — ABI handler ngắt x86 |
| `@inline` | fn | `inline __attribute__((always_inline))` |
| `@section("..")` | fn/global | `section(...)` — đặt vào section linker |
| `@used` | fn/global | `used` — giữ lại dù không tham chiếu |

```g
@packed
struct GdtPtr { limit: u16, base: u64 }     // đúng 10 byte, không đệm

@align(4096)
let page_table: [512]u64 = ...              // căn theo trang

@noreturn @section(".text.boot")
fn _entry() { ... }
```

### Ký hiệu ngoài (linker / assembly)

```g
extern let _kernel_start: u8                // do linker script cấp
extern let _bss_end: u8
let size = (&_bss_end as u64) - (&_kernel_start as u64)
```

### Khẳng định lúc biên dịch

```g
static_assert(sizeof(GdtPtr) == 10, "GDT pointer phải 10 byte")
static_assert(CAP > 0)                 // thông điệp là tuỳ chọn
```
Bắt ngay khi biên dịch nếu điều kiện (hằng) sai — khoá bố cục struct/ABI. Điều
kiện phải là **hằng** (literal, `const`, `sizeof`/`alignof`, biến thể enum và phép
toán giữa chúng); tham chiếu biến/lời gọi lúc chạy là lỗi.

---

## Hệ thống kiểu & chẩn đoán

G có một **type-checker** chạy trước khi sinh mã:
- Suy luận kiểu cho mọi biểu thức (dùng cho định dạng `print`, auto-deref, phân giải method).
- Bắt lỗi: biến/định danh chưa khai báo, gán vào biến bất biến, sai số tham số, trường/struct/kiểu không tồn tại, lệch placeholder.

Lỗi hiển thị kèm dòng nguồn và con trỏ `^`:
```
bad.g:3:5: lỗi kiểu/ngữ nghĩa: không thể gán cho 'x' (bất biến — dùng 'let mut')
    3 |     x = 10
      |     ^
```

---

## Cấu trúc dự án

```
G/
├── gc                      # trình biên dịch (điểm vào)
├── README.md
├── compiler/
│   ├── lexer.py            # từ vựng + tự chèn ';' (ASI kiểu Go)
│   ├── ast_nodes.py        # định nghĩa nút AST
│   ├── parser.py           # cú pháp -> AST
│   ├── types.py            # hệ thống kiểu (GType, ánh xạ C, printf spec)
│   ├── checker.py          # phân tích ngữ nghĩa + suy luận kiểu
│   ├── codegen.py          # sinh mã C
│   └── driver.py           # pipeline + module + chẩn đoán + gọi cc
├── runtime/g_runtime.h     # runtime (g_alloc, g_panic, ...)
├── lib/std.g               # thư viện chuẩn (viết bằng G)
├── examples/               # hello, showcase, fib, sieve, oop, features, list, matrix, higher_order
└── tests/
    ├── run_tests.sh        # bộ test (so sánh output; --bless để cập nhật)
    ├── cases/              # test case riêng (chạy & so output)
    ├── expected/           # kết quả mong đợi
    └── fail/               # test "phải lỗi" (khoá thông điệp chẩn đoán)
```

---

## Quy tắc kết thúc câu lệnh

Như Go/Zig, G **tự động kết thúc câu lệnh ở cuối dòng** — không cần `;`.
Khi cần trải biểu thức nhiều dòng, để toán tử ở **cuối dòng**:
```g
let x = a +
        b        // OK
```

---

## Hệ thống kiểu & chẩn đoán — điểm nổi bật

- **Khớp định dạng `print`:** kiểm tra cả *số lượng* lẫn *kiểu* placeholder.
- **Tràn số literal:** báo lỗi khi literal vượt biên kiểu đích (`u8 = 300` → lỗi).
- **Bất biến qua method:** cấm gọi method-sửa-`self` trên binding `let`.
- **Phân tích đường về:** hàm non-void phải trả về trên mọi nhánh (hiểu `match`
  enum vét cạn, `if/else` cùng diverge, `loop` vô hạn, `panic/unreachable/todo`).
- **Gợi ý "có phải ... ?"** cho định danh/trường/kiểu gõ sai (Levenshtein).
- **Khai báo trùng:** bắt sớm trường struct / biến thể enum / hàm / method trùng
  tên (kèm va chạm tên biến thể enum giữa các enum) — thay vì rò lỗi C khó hiểu.
- **Gán không hợp lệ:** cấm gán cả mảng tĩnh bằng `=`, và gán kết quả hàm `void`
  cho biến.
- **So sánh dây chuyền:** bắt `a < b < c` (vô nghĩa toán học trong C/G) và gợi ý `&&`.
- **So sánh enum khác loại:** `EnumA == EnumB` (gần như luôn là lỗi logic) bị từ chối.
- **Lấy địa chỉ/giải tham chiếu sai:** `&<giá trị tạm>` và `*<không phải con trỏ>`
  báo lỗi G sạch thay vì rò lỗi C khó hiểu.
- **Chia cho hằng 0:** `x / 0`, `x % (3-3)` (mẫu số gấp được thành 0) bị bắt sớm.
- **`print` mơ hồ:** nhiều đối số mà thiếu chuỗi định dạng (sẽ bỏ bớt đối số) bị từ chối.
- **Chia nguyên rồi đổi sang thực:** `let x: f64 = 7 / 2` (mất phần lẻ -> 3.0) bị bắt.
- **Dịch bit không hợp lệ:** dịch **âm**, dịch **≥ 64 bit**, hay dịch một biến kiểu
  hẹp **vượt bề rộng** (`x: i32 << 40`) — đều là UB trong C — bị từ chối.
- **`match` enum chưa vét cạn:** thiếu biến thể mà không có `_` bị bắt (kèm danh
  sách biến thể còn thiếu); pattern thuộc **enum khác** với subject cũng bị bắt.
- **Mã chết:** câu lệnh sau `return`/`break`/`continue`/`panic` bị từ chối.
- **`defer` thoát luồng:** `return`/`break`/`continue` trong `defer` bị cấm.
- **Trường struct literal trùng:** `P { x: 1, x: 2 }` bị bắt.
- **Ép kiểu vô nghĩa:** `x as [N]T` / `x as Struct` bị từ chối.
- **Số 0 dẫn đầu:** `010` (C coi là bát phân 8) bị từ chối — dùng `0o10` cho bát phân.

> **Ngữ nghĩa vòng lặp:** `for i in a..b` lượng giá cận `b` (và `step`) **đúng
> một lần** khi vào vòng (giống Rust) — đổi `b` trong thân không làm dài thêm
> vòng lặp, và hàm dùng làm cận chỉ được gọi một lần.

## Giới hạn hiện tại

- `match` so khớp bằng `==`/`strcmp`/khoảng + guard `if` (chưa destructuring struct/enum dữ liệu).
- Chưa có generic, trait, ownership/borrow-checker đầy đủ.
- Có **con trỏ hàm** (`fn(T)->R`) nhưng **chưa có closure** bắt biến môi trường.
- Cỡ mảng là biểu thức **hằng** (chưa cỡ động lúc chạy — dùng `g_alloc`).
- Cổng I/O & nhiều intrinsic CPU là **đặc quyền x86** (chỉ chạy ở ring 0); ngoài
  x86 chúng biên dịch thành no-op an toàn.

Một nền tảng vững để mở rộng tiếp. 🚀

## Mới trong 0.22.0 — 🎭 Traits / Interfaces

- 🎭 **`trait` + `impl Trait for Kiểu` + ràng buộc generic `<T: Trait>`**:
  ```g
  trait Show { fn show(self) -> str }
  struct Pt { x: int, y: int }
  impl Show for Pt { fn show(self) -> str { return "Pt" } }

  fn nhan<T: Show>(v: T) -> str { return v.show() }
  fn ca_hai<T: Show + Area>(v: T) -> int { ... }   // nhiều ràng buộc
  ```
- ⚙️ **Trait là RÀNG BUỘC LÚC BIÊN DỊCH, không phải đối tượng động**: không
  vtable, không boxing, **không chi phí lúc chạy**. Kiểm tại nơi *nhân bản*
  generic — nên **G-IR và cả hai backend không đổi một dòng nào** (giống
  generics ở 0.21.0).
- 🛡️ Bốn kiểm tra, mỗi cái kèm cách sửa:
  - kiểu không thoả ràng buộc → *"'N' không thoả 'T: Ord2' — thêm
    'impl Ord2 for N { ... }'"*;
  - `impl` **thiếu method** → in ra chữ ký còn thiếu;
  - `impl` **sai chữ ký** (số tham số / kiểu / kiểu trả về);
  - ràng buộc tham chiếu trait không tồn tại.
- 🧩 **Trait dựng sẵn** cho kiểu nguyên thuỷ: `Ord`, `Eq`, `Show`, `Num` —
  `max2<T: Ord>(3, 7)` dùng được ngay, không cần `impl` tay cho `int`.
- 🔧 `Self` trong chữ ký trait được thay bằng kiểu cài đặt khi so khớp.
- 🐛 Sửa cảnh báo C `unused parameter 'self'` cho method không dùng `self`
  (tham số bắt buộc của method, không bỏ được).
- 🧪 **Bộ test: 243 ca** + backend-diff 105 + target 21 + panic 4 + IR 101
  + IR-unit 25 + layout 11 + ASan 96.

## Mới trong 0.21.0 — 🧬 Generics (`fn f<T>(...)`)

- 🧬 **Hàm generic** với suy kiểu từ đối số, hoặc chỉ định tường minh:
  ```g
  fn max2<T>(a: T, b: T) -> T { if a > b { return a } return b }
  fn first<T>(xs: slice<T>) -> T { return xs[0] }
  fn pick<A, B>(a: A, b: B) -> B { let _ = a return b }

  max2(3, 7)            // T = int  (suy từ đối số)
  max2(2.5, 1.5)        // T = f64
  first(a[..])          // T lấy từ slice<T>
  id<str>("boo")        // đối số kiểu TƯỜNG MINH
  ```
- ⚙️ **Monomorphization trong checker**: mỗi bộ kiểu cụ thể sinh ra một hàm
  thường (`max2` + `int` → `max2__int`), rồi được kiểm tra như mọi hàm khác.
  **G-IR và cả hai backend không cần một dòng thay đổi nào** — chúng chỉ thấy
  hàm thường. Đây là lý do chọn cách này thay vì kiểu-bị-xoá (type erasure):
  không cần boxing, không mất hiệu năng, không đụng ABI.
- 🛡️ **Lỗi trong thân generic được bắt tại KIỂU CỤ THỂ** (như C++/Rust):
  `bad("x")` với `fn bad<T>(a: T) -> T { return a + 1 }` báo
  *"không thể dùng '+' giữa 'str' và 'int'"*.
- 🛡️ Suy kiểu thất bại → yêu cầu chỉ định tường minh, kèm cú pháp mẫu. Đệ quy
  generic vô hạn trên kiểu bị chặn (giới hạn 64 bản nhân / độ sâu 16).
- 🔍 `f<int>(x)` chỉ được coi là đối số kiểu khi sau `>` là `(` — nên `a < b`
  vẫn là **so sánh**, không bị nuốt nhầm.
- 🧪 **Bộ test: 237 ca** + backend-diff 104 + target 21 + panic 4 + IR 100
  + IR-unit 25 + layout 11 + ASan 95; fuzz 32 000 vòng (có token generic),
  0 crash.

## Mới trong 0.20.0 — 🧠 Mô hình bộ nhớ & Allocator thay thế được

Xem [`docs/MEMORY.md`](docs/MEMORY.md) — mô hình bộ nhớ nay được **viết ra thành
văn**: hạng bộ nhớ, ai sở hữu/ai mượn, G bảo đảm gì lúc biên dịch, gì lúc chạy,
và **những gì G KHÔNG bảo đảm** (use-after-free, double-free, rò rỉ, aliasing).

- 🧠 **Bốn hạng bộ nhớ** được định nghĩa rõ: *giá trị* (stack, ngữ nghĩa sao
  chép), *tĩnh*, *sở hữu* (bạn phải `free`), *mượn* (`&x`, `slice<T>` — **không
  bao giờ** `free`).
- ✨ **Allocator thay thế được**: `alloc(T, n)` / `free(p)` / `realloc(p, T, n)`
  dùng allocator mặc định; `alloc_in(a, T, n)` / `free_in(a, p)` /
  `realloc_in(a, p, T, n)` nhận allocator tường minh.
  ```g
  let mut backing: [4096]u8 = [0; 4096]
  let mut a = arena_allocator(backing)   // KHÔNG cần libc
  let p = alloc_in(a, Node, 16)
  ```
- 🧩 **`arena_allocator(buf)` chạy ở freestanding/kernel** — bộ đệm do bạn cấp,
  không malloc. `free` của arena là **no-op có chủ ý**: cả vùng chết cùng bộ
  đệm. Đây chính là lý do phải có allocator thay thế được: trước đây `g_alloc`
  là macro `calloc` nên **không dùng được** trong kernel.
- 🛡️ **Kiểm lúc biên dịch**: bộ đệm arena phải khả biến (`let mut`) và phải là
  byte (`[N]u8` / `mut slice<u8>`); `alloc_in` phải nhận `Allocator`; `free`
  phải nhận con trỏ. Ở `--freestanding`, `alloc`/`free` **không allocator** bị
  từ chối kèm gợi ý dùng `alloc_in`.
- 🛡️ Arena kiểm **tràn khi nhân** `n * sizeof(T)` trước khi cấp — tránh cấp
  thiếu rồi ghi đè.
- ♻️ `g_alloc`/`g_free`/`g_realloc` vẫn hoạt động (tương thích ngược).
- 🧪 **Bộ test: 232 ca** + backend-diff 103 + target 21 + panic 4 + IR 99
  + IR-unit 25 + layout 11 + ASan 94; fuzz 32 000 vòng (có token allocator),
  0 crash. ASan với `detect_leaks=1` trên ca `allocator`: **0 rò rỉ**.

## Mới trong 0.19.0 — ✅ Giai đoạn B HOÀN TẤT: hai backend khớp 101/101

- ✅ **`--backend=c-ir` khớp 101/101, 0 khác, 0 chưa hỗ trợ** — gồm cả
  `tests/freestanding/` (biên dịch không libc) và `tests/panic/` (lỗi lúc chạy
  phải cùng mã thoát 101 **và** cùng thông điệp). Đây là tiêu chí thoát của
  Giai đoạn B trong ARCHITECTURE.md §3.
- 🐛 **Lỗi hạ mã IR còn lại được sửa** (mọi backend tương lai đều sẽ dính):
  - thuộc tính `@packed`/`@align` đặt sai chỗ (phải sau `}` đóng struct);
  - struct chưa sắp xếp topo → C thấy kiểu chưa hoàn chỉnh;
  - method TĨNH trong `impl` bị thêm tham số `self` ngầm;
  - `Enum.Variant` bị coi là truy cập trường (checker lưu tuple `(Kiểu, Tên)`,
    irgen đọc như tên trần);
  - `==`/`!=` trên struct/slice không hạ về hàm so sánh;
  - **binding trong `match`** (`x if x < 0 =>`) chưa được hạ → biến không tồn tại;
  - `slice<str>` sinh hai tên typedef khác nhau ở hai backend — nay
    `types.slice_c_name` là nguồn chân lý duy nhất;
  - cắt lát của slice không **kẹp biên** như `g_sslice`;
  - `*Struct` không đổi tên C an toàn (`*Default` → `default*`, từ khoá C);
  - intrinsic bit/CPU (`popcount`/`clz`/`ctz`/`bswap`/`rotl`/`rotr`, cổng I/O,
    MSR) chưa hạ; `clz` cần bù bề rộng còn `ctz` thì **không**;
  - `asm` mở rộng **mất toán hạng** → `%0` không tham chiếu được gì;
  - `s.at(i)` mất kiểm biên → không panic;
  - `sizeof(x)` với `x` là BIẾN (parser dựng thành `A.SizeOf`).
- 🧪 **Bộ so khớp mở rộng**: `run_backend_diff.sh` nay chạy cả freestanding và
  panic. Chính phần mở rộng này phát hiện 3 lỗi cuối — bộ cũ đã báo "93/93 khớp"
  trong khi asm, `s.at`, và freestanding vẫn hỏng.
- 🧪 **Bộ test: 225 ca** + backend-diff 101 + target 21 + panic 4 + IR 97
  + IR-unit 25 + layout 11 + ASan 93; fuzz 32 000 vòng, 0 crash.

## Mới trong 0.18.0 — 🔁 Giai đoạn B gần xong: 81/93 ca khớp hai backend

- 🔁 **`--backend=c-ir` khớp 81 ca** (từ 39), **0 khác**. Còn 12 ca chưa sinh mã
  được, và **không ca nào cho kết quả sai** — luôn báo lỗi rõ ràng.
- ✨ Hạ thêm trong `irgen.py`: `format(...)` (đo bằng `snprintf(NULL,0,…)` rồi
  cấp phát vừa khít), `dbg(x)`, `len()` (gấp hằng cho mảng tĩnh), khởi tạo
  global động (hàm `_g_init_globals` chạy trước `main`).
- 🐛 **Bảy lỗi hạ mã IR do so khớp hai backend phát hiện** — mọi backend tương
  lai (LLVM/WASM) đều sẽ dính:
  - **global có initializer không-hằng bị bỏ im lặng** → đọc ra 0;
  - `s[i]` trên `str` lấy **địa chỉ biến** thay vì nạp giá trị → `char_at()`
    đọc rác;
  - `makeslice` trên cơ sở `*[N]T` cộng con trỏ theo **đơn vị cả mảng** →
    `a[1..3]` trỏ ra ngoài mảng;
  - `{b}` là bool-hay-nhị-phân **tuỳ kiểu đối số**; IR luôn chọn nhị phân, và
    số âm in 64 bit thay vì đúng bề rộng kiểu (`-1 as i8`);
  - tham số khai báo tên đã đổi nhưng **chỗ dùng thì chưa** → tham số tên
    `round` trỏ vào `round()` của `<math.h>`;
  - **irgen có bản phân giải kiểu rút gọn riêng và nó trôi lệch**:
    `fn(int)->int` bị suy thành `int`. Nay checker ghi `ty.resolved`, irgen
    dùng lại — một nguồn chân lý.
- 🔧 Backend: global là **lvalue** trong C nhưng là con trỏ trong IR (phát
  `&x`); con trỏ hàm có typedef thật thay vì `void*`; `%` trên số thực →
  `fmod`; gán mảng cỡ tĩnh → `memcpy` (nhưng `[]T` là con trỏ trần thì không).
- 🧪 **Bộ test: 225 ca** + backend-diff 81 + target 21 + panic 4 + IR 97
  + IR-unit 25 + layout 11 + ASan 93; fuzz 32 000 vòng, 0 crash.

## Mới trong 0.17.0 — 🔁 Giai đoạn B tiến triển: 39 ca khớp hai backend

- 🔁 **`--backend=c-ir` khớp 39 ca** (từ 20) so với backend mặc định, **0 khác**.
  Toàn bộ phần hạ mã thêm nằm trong `irgen.py`, **không phải** trong backend —
  nhờ vậy LLVM/WASM sau này thừa hưởng luôn:
  - `abs/min/max/clamp` → `cmp` + `select` (macro C cũ còn đánh giá đối số nhiều
    lần; bản IR vật hoá nên `min(f(), g())` chỉ gọi mỗi hàm một lần);
  - `g_alloc/g_realloc` → cỡ phần tử tính sẵn bằng engine bố cục, backend không
    cần hiểu cú pháp kiểu của G;
  - `assert` → nhánh + panic; `swap` → load/store; `typeof` → hằng chuỗi;
  - `assert_*`/`check_*` + khung test, khớp **từng byte** kể cả màu ANSI;
  - cờ định dạng (`{:5}`, `{:<5}`, `{:05}`, `{:+}`, `{:.2}`, `{:^7}`, `{:b}`,
    `{ld}`…) dùng lại `SPEC_MAP`/`_apply_fmt_flags` của backend C thay vì viết
    lại — hai đường không thể trôi lệch;
  - in enum (tên biến thể), struct (đệ quy), mảng, bool, slice.
- 🐛 **Lỗi thật do so khớp hai backend phát hiện** (đều là lỗi *hạ mã IR*, tức sẽ
  ảnh hưởng mọi backend tương lai):
  - `for c in "chuỗi"` **không lặp lần nào** (foreach chỉ xử lý mảng);
  - `p[i]` trên con trỏ thường sinh `(*p)[i]` — chỉ đúng với `*[N]T`;
  - hằng số thực bị phát thành **chuỗi C**;
  - toán tử một ngôi không nới bề rộng: `-w` với `w: u32` in `4294967295`
    thay vì `-1`;
  - `extern fn` trùng ký hiệu runtime (`strlen`, `g_substr`…) phát lại nguyên
    mẫu → `conflicting types`. Nay quét thẳng `g_runtime.h` để biết ký hiệu nào
    đã có, danh sách không bao giờ lệch.
- 🧪 **Bộ test: 225 ca** + backend-diff 39 + target 21 + panic 4 + IR 97
  + IR-unit 25 + layout 11 + ASan 93; fuzz 18 000 vòng, 0 crash.

## Mới trong 0.16.0 — 🔁 Backend C đọc từ G-IR (Giai đoạn B)

- 🔁 **`--backend=c-ir`**: backend C thứ hai sinh mã **từ G-IR** thay vì từ AST,
  chạy song song với backend mặc định. CFG của IR ánh xạ gần một-một sang nhãn
  + `goto` của C.
- 🧪 **`tests/run_backend_diff.sh`** — cơ chế kiểm chứng của giai đoạn chuyển
  đổi: chạy CẢ HAI backend trên mọi ví dụ/ca test rồi so từng byte đầu ra và mã
  thoát. Hiện: **20 khớp, 0 khác**, 73 chưa hỗ trợ (các built-in in ấn/format
  phức tạp vẫn ở dạng intrinsic cấp cao). Backend cũ **vẫn là mặc định** cho tới
  khi con số "chưa hỗ trợ" về 0 — đúng chiến lược ở ARCHITECTURE.md §3.
- 🐛 **Lỗi thật do so khớp hai backend phát hiện** (không phải lỗi của backend
  mới — là lỗi của *bản hạ mã IR*, sẽ ảnh hưởng MỌI backend tương lai):
  - `elemaddr` trên slice lấy địa chỉ của **handle** thay vì `.ptr`;
  - biến thể enum có giá trị **âm tường minh** (`Neg = -1`) bị tính lại thành 0;
  - `1 << 40` mất bit vì C tính trong `int` trước khi gán vào `i64`;
  - `for i in 5..0 step -1` **không chạy lần nào** (chiều so sánh cố định `<`);
  - `s[0..=4]` cắt thiếu một ký tự (cờ `inclusive` được ghi rồi không ai đọc);
  - `match self` / `self == Red` so sánh trên **địa chỉ** thay vì giá trị;
  - `Red.is_red()` truyền hằng enum làm **con trỏ** → segfault.
- 🐛 **UB trong backend cũ**: `let x = 5; let p = &x; *p = 6` sinh `int const x`
  rồi ép bỏ `const` để ghi — **hành vi không xác định**, in `6` với `-O0` nhưng
  `5` với `-O2`. Nay biến bị lấy địa chỉ không gắn `const` nữa, kết quả ổn định
  ở mọi mức tối ưu. (Ca test `ptr_decl` trước đây khoá lại chính giá trị sai.)
- 📐 `sizeof`/`alignof` trong IR được **gấp thành hằng** bằng engine bố cục, nên
  mọi backend cho cùng con số mà không cần hỏi C.
- 🧪 **Bộ test: 225 ca** + backend-diff 20 + target 21 + panic 4 + IR 97
  + IR-unit 25 + layout 11 + ASan 93; fuzz 24 000 vòng, 0 crash.

## Mới trong 0.15.0 — 📐 ABI / bố cục theo target

- 🐛 **`usize`/`isize` hardcode 64-bit.** `Target.ptr_bits` đã tồn tại nhưng
  `types.py` bỏ qua nó, nên trên target 32-bit (`wasm32`) `usize` vẫn là 64-bit:
  `let n: usize = 5_000_000_000` lọt qua checker rồi **tràn âm thầm** lúc chạy.
  Nay bề rộng và biên giá trị đều theo target.
- 📐 **Engine bố cục độc lập C** (`compiler/layout.py`): tính `sizeof`/`alignof`/
  offset trường cho **bất kỳ target nào**, theo quy tắc ABI chuẩn, kể cả
  `@packed` và `@align(N)`. Trước đây việc này giao hết cho trình biên dịch C —
  nghĩa là backend LLVM/WASM tương lai sẽ không có gì để dựa vào, và không thể
  hỏi "struct này bố cục ra sao trên wasm32?" khi đang chạy trên x86.
- ✅ **`static_assert(sizeof(T) == N)` nay báo lỗi ở TẦNG G**, đúng dòng nguồn G,
  thay vì lọt xuống C rồi nổ với thông báo của C trỏ vào file `/tmp`. Và nó
  **kiểm theo target**: cùng một assert đúng trên x86_64 và sai trên wasm32.
- 🐛 **`@align(N)` bị bỏ qua khi tính bố cục** — `Attr` lưu đối số trong `args`
  (danh sách node) chứ không phải `arg`, nên cả `layout.py` lẫn `irgen.py` đọc
  nhầm thành `None`.
- 🐛 **`==` trên struct có trường `slice` sinh C không hợp lệ** (`invalid operands
  to binary ==`). Nay so sánh theo `(ptr, len)`.
- 🧪 **Đối chiếu với C** (`tests/test_layout.py`, 11 ca): sinh chương trình C in
  `sizeof`/`_Alignof`/`offsetof` rồi so từng con số với G. Thêm một lần quét
  toàn bộ codebase: **41 struct, 0 sai lệch**. Một "nguồn chân lý thứ hai" chỉ
  có giá trị nếu nó khớp nguồn thứ nhất.
- 🧪 **Bộ test: 225 ca** + target 21 + panic 4 + IR 97 + IR-unit 25 + layout 11
  + ASan 93; fuzz 50 000 vòng, 0 crash.

## Mới trong 0.14.0 — 🎯 Lớp Target/HAL

- 🐛 **Sửa lỗi âm thầm nguy hiểm nhất từng có trong G.** `outb`/`inb`/`cli`/
  `read_cr3`/`rdmsr`… là built-in **toàn cục**: chúng qua được checker trên mọi
  kiến trúc, rồi runtime C hạ chúng thành **no-op im lặng** ngoài x86. Nghĩa là:
  ```g
  fn uart_putc(c: u8) { outb(0x3F8, c) }   // aarch64: biên dịch SẠCH
                                            //          chạy KHÔNG LÀM GÌ
  ```
  Một driver chết lặng, không một cảnh báo. Nay là **lỗi biên dịch** kèm gợi ý
  thay thế (dùng MMIO `vol_write`/`vol_read`).
- 🎯 **Mô hình NĂNG LỰC, không phải tên kiến trúc** (`compiler/target.py`). Mỗi
  intrinsic gắn với một năng lực (`port_io`, `control_regs`, `cycle_counter`,
  `msr`, `tlb`, `privileged`…); mỗi target khai báo tập năng lực của nó. Nhờ vậy
  `rdtsc()` **vẫn dùng được** trên aarch64/riscv64 (có `cntvct_el0`/`rdcycle`)
  trong khi `outb()` thì không — điều mà cách chặn theo "arch == x86" làm sai.
- 🎯 **`--target`** (`x86_64-linux|-none`, `aarch64-…`, `riscv64-…`, `wasm32`) và
  **`--list-targets`** hiển thị năng lực từng target. Cross-compile thất bại vì
  thiếu toolchain nay báo lỗi **hành động được** (gợi ý `--cc=<triple>-gcc`),
  không còn đổ tại "lỗi nội bộ của G".
- 🔧 **Runtime không còn no-op giả.** Ngoài x86, những thứ **có tương đương thật**
  được cài đúng (aarch64: `wfi`/`yield`/`brk`/`cntvct_el0`/`daifset`; riscv64:
  `wfi`/`ebreak`/`rdcycle`/`csrci`), còn những thứ **không tồn tại** (cổng I/O,
  CR, MSR) thì **không định nghĩa nữa** — lỗi liên kết còn tốt hơn no-op âm thầm.
- 🐛 **`if f` (quên dấu ngoặc)** — con trỏ hàm luôn khác null nên điều kiện luôn
  đúng; trước đây lọt qua checker. Nay bị từ chối kèm gợi ý `f()`. Tương tự cho
  `f && ...` và điều kiện là `slice`.
- 🧪 **Bộ target mới** (`tests/run_target.sh`, 17 khẳng định): mỗi ca ghi rõ
  `//! accept <target>` / `//! reject <target> <thông báo>`. Đã kiểm ngược: cố ý
  thêm `port_io` cho aarch64 thì bộ này **đỏ** — nó thật sự bắt lỗi.
- 🧪 **Bộ test: 223 ca** + target 17 + panic 4 + IR 96 + IR-unit 25 + ASan 92;
  fuzz **60 000 vòng** xoay vòng qua mọi target, 0 crash.

## Mới trong 0.13.0 — 🔪 Slice thật (`slice<T>`)

- ✨ **`slice<T>` / `mut slice<T>` — con trỏ BÉO `(ptr, len)`.** Khác hẳn `[]T`
  (con trỏ trần, mất độ dài) và `[N]T` (mảng tĩnh). Độ dài **đi cùng** con trỏ,
  nên không thể "quên" truyền nó:
  ```g
  fn total(xs: slice<int>) -> int {
      let mut s = 0
      for i in 0..len(xs) { s += xs[i] }   // len() hoạt động
      return s
  }
  fn fill(xs: mut slice<int>, v: int) {
      for i in 0..len(xs) { xs[i] = v }    // ghi cần 'mut slice'
  }
  let mut a: [5]int = [1, 2, 3, 4, 5]
  total(a)          // mảng tĩnh TỰ chuyển thành slice (mang theo N)
  total(a[1..3])    // cắt lát: nửa mở; có a[..n], a[n..], a[..], a[lo..=hi]
  fill(a[0..2], 7)  // sửa đúng phần được mượn
  println("{}", a[1..4])   // in ra: [2, 3, 4]
  ```
- 🛡️ **Kiểm biên qua RANH GIỚI HÀM** — điều `[]T` không làm được. `get(a[0..2], 2)`
  panic đúng chỗ dù mảng gốc còn phần tử ở vị trí đó, vì slice mang theo `len`
  của **chính nó**. Tắt cùng `--no-checks` như mọi kiểm tra khác.
- 🛡️ **Quyền ghi nằm ở KIỂU, không ở biến.** `slice<T>` chỉ đọc; ghi qua nó là
  lỗi biên dịch. Không thể **mượn quyền ghi** từ một mảng `let`: truyền nó cho
  `mut slice<T>` bị từ chối. Và slice **không tự rã** thành `*T` — làm vậy là
  vứt bỏ độ dài, đúng thứ slice sinh ra để ngăn.
- 🧩 Hoạt động ở **freestanding/kernel** (struct thuần, không libc, không cấp
  phát), trong **struct**, với mọi kiểu phần tử (`str`, `struct`, `enum`), và
  cắt lát được **slice của slice**.
- 🧪 **Bộ panic mới** (`tests/run_panic.sh`): khẳng định lỗi lúc chạy **panic
  đúng mã thoát 101** và `--no-checks` gỡ được — trước đây an toàn lúc chạy
  hoàn toàn không có test nào phủ.
- 🧪 **Bộ test: 220 ca** + panic 4 + IR 96 + IR-unit 25 + ASan 92; fuzz **40 000
  vòng** với token slice, 0 crash.

## Mới trong 0.12.0 — 🏗️ G-IR, giao diện backend, fuzzing

Bản này là bước **kiến trúc**, không phải bước tính năng ngôn ngữ. Xem
[`ARCHITECTURE.md`](ARCHITECTURE.md) để biết audit đầy đủ và lộ trình.

- 🏗️ **G-IR — biểu diễn trung gian** (`compiler/ir.py`, `irgen.py`): three-address
  code trên CFG có basic block. Mọi cấu trúc điều khiển (`if/while/loop/for/
  match/defer`) được hạ hẳn thành `jump`/`branch`/`switch`. Chạy thử bằng
  `gc file.g --emit-ir`.
- 🛡️ **Trình kiểm IR** (`irverify.py`): kiểm terminator, nhãn, block không thể
  tới, dùng temp trước khi định nghĩa, định nghĩa lại temp, kiểu toán hạng.
  `gc file.g --verify-ir`. **93/93** ví dụ + ca test (kể cả kernel freestanding)
  hạ được sang IR và qua verifier — đây là bằng chứng IR phủ hết ngôn ngữ.
- 🔌 **Giao diện backend** (`backend.py`): `AstBackend` / `IRBackend` + registry.
  `--backend=c` (mặc định, đọc AST) hoặc `--backend=ir`. Backend C hiện tại
  **không đổi** — chiến lược chuyển đổi giữ nó làm mặc định cho tới khi bản
  đọc-từ-IR khớp 100% đầu ra (ARCHITECTURE.md §3).
- 🧪 **Fuzzing** (`tests/run_fuzz.py`): đột biến corpus thật + sinh token ngẫu
  nhiên, chạy hết lexer→parser→checker→IR. Yêu cầu: không bao giờ crash bằng
  exception Python, không treo. Đã chạy **80 000 vòng / 8 hạt giống, 0 crash**.
- 🐛 **Ba lỗi do fuzzing tìm ra:**
  - nguồn kết thúc giữa một ký tự (`'` cuối file) → `IndexError` làm **crash**
    trình biên dịch thay vì báo lỗi từ vựng;
  - nguồn kết thúc giữa `\x`/`\u{` → **treo vô hạn** (`"" in "0123..."` là
    `True` trong Python);
  - `v() && true` với `v()` trả `void` **lọt qua checker** — nhánh `&&`/`||`
    trả `bool` mà không kiểm toán hạng nào cả.
- 🧪 **Unit test IR** (`tests/test_ir.py`, 21 ca): kiểm **ngữ nghĩa** hạ mã, không
  chỉ tính hợp lệ — defer chốt giá trị trả về trước khi chạy, defer LIFO và
  được nhân bản ở mọi lối ra, `match` hằng thành `switch`, mảng dùng `memcpy`,
  `for mut` ghi qua `elemaddr`, `&&` đoản mạch thật. Cộng 6 ca kiểm rằng
  **verifier thật sự bắt lỗi** (tự dựng IR hỏng rồi khẳng định nó bị từ chối).
- 🧪 **Bộ test: 215 ca** (+5 ca hồi quy cho các lỗi fuzzing tìm ra).

## Mới trong 0.11.0 — 🧩 Destructuring, lát cắt chuỗi, hệ thống cảnh báo

- ✨ **Destructuring struct**: `let P{x, y} = p` rút trích trường ra biến cùng
  tên; `let P{x: a} = p` đổi tên; `let mut P{...}` cho binding khả biến. Giá trị
  nguồn được đánh giá **đúng một lần**, nên `let P{x} = mk()` an toàn.
- ✨ **Lát cắt chuỗi** `s[lo..hi]` / `s[lo..=hi]`, cận khuyết được: `s[..n]`,
  `s[n..]`, `s[..]`. Chỉ số được **kẹp** vào `[0, len]` (và `hi < lo` cho chuỗi
  rỗng) nên không bao giờ đọc ngoài vùng nhớ.
- ✨ **Hệ thống cảnh báo** (không chặn biên dịch, in màu vàng): biến khai báo mà
  **không dùng**, và `let mut` **không bao giờ được ghi**. Tiền tố `_` để miễn
  (`let _bo_qua = ...`). Ghi gián tiếp — method tự-sửa, `&x`, `for mut x`, ghi
  qua con trỏ `p[i] = v` — đều được tính đúng là "có ghi". Cờ mới `-w` (tắt
  cảnh báo) và `-W` (coi cảnh báo là lỗi).
- 🐛 **`let b = a` trên mảng CHIA SẺ bộ nhớ** thay vì sao chép — `b[0] = 9` sửa
  luôn `a` (`__auto_type` làm mảng phân rã thành con trỏ). Nay sao chép thật,
  đúng ngữ nghĩa giá trị của G.
- 🐛 **Tham số mảng `mut` ghi xuyên về nơi gọi** — C truyền mảng như con trỏ nên
  `fn f(mut a: [3]int) { a[0] = 99 }` sửa mảng của người gọi, trong khi `mut`
  trên tham số vô hướng lại là bản sao. Nay tham số mảng `mut` cũng là bản sao
  cục bộ.
- 🛡️ **Runner nghiêm ngặt hơn**: mọi ca test giờ phải **không có cảnh báo** nào
  (G lẫn `gcc -Wall -Wextra`), và có hạng mục `tests/warn/` khoá lại nội dung
  cảnh báo *và* số lượng (bắt dương tính giả).
- 🐛 **`defer` chạy TRƯỚC khi tính giá trị trả về** — `defer n = 999` rồi
  `return n + 1` trả về **1000** thay vì 1. Sai âm thầm, đúng vào thứ `defer`
  hay dùng nhất (dọn dẹp rồi trả kết quả). Nay giá trị được vật hoá trước, đúng
  ngữ nghĩa Zig/Go.
- 🐛 **Tên G trùng ký hiệu `<math.h>` sinh lỗi C thô** — `let mut log = 0` cho ra
  `static int log;` va vào `log()` của libm (driver luôn link `-lm`), báo lỗi C
  khó hiểu. Bộ tên C dành riêng nay phủ toàn bộ `<math.h>` (kể cả biến thể
  `f`/`l`) và nhiều hàm libc còn thiếu (`strstr`, `qsort`, `getenv`…).
- 🐛 **`self == Red` trong `impl` của enum báo lỗi** `'*Color'` vs `'Color'`,
  dù `match self { Red => ... }` lại chạy — `self` là con trỏ và `.field` đã tự
  deref. Nay `==`/`!=` trên chính `self` cũng tự deref; so sánh con trỏ nói
  chung (`p == 5`) vẫn bị chặn.
- 🧼 **Kiểm bằng sanitizer**: `bash tests/run_asan.sh` biên dịch lại mọi ví dụ
  và ca test bằng `-fsanitize=address,undefined` rồi chạy — **87/87 sạch**
  (không đọc/ghi ngoài biên, không use-after-free, không UB). `LEAKS=1` để bật
  kiểm rò rỉ.
- 🧪 **Bộ test: 210 ca** (+13): `destructure`, `str_slice`, `array_value_copy`,
  `unused_vars`, `defer_return_order`, `c_name_clash`, `self_compare` và 6 ca
  "phải lỗi".

## Mới trong 0.10.0 — ✨ `if`/`match` biểu thức, method của `str`, `[v; N]`

- ✨ **`if` và `match` ở vị trí BIỂU THỨC** (như Rust): `let v = if c { a } else { b }`,
  `let s = match e { A => "a", B => "b" }`. Nhánh `else` là **bắt buộc** và
  `match`-biểu thức phải **vét cạn** (mọi nhánh đều phải cho một giá trị); các
  nhánh phải **cùng kiểu** (số thì lấy kiểu chung). Guard/binding/khoảng dùng
  được như `match` câu lệnh.
- ✨ **Method dựng sẵn trên `str`** (không cần `import std`): `s.len()`,
  `s.is_empty()`, `s.upper()`, `s.lower()`, `s.trim()`, `s.rev()`, `s.at(i)`,
  `s.sub(start, len)`, `s.contains(x)`, `s.starts_with(x)`, `s.ends_with(x)`,
  `s.index_of(x)`, `s.count(c)`, `s.eq(x)`, `s.concat(x)`, `s.repeat(n)`,
  `s.to_int()`, `s.to_float()`. Tên sai được gợi ý ("có phải `len`?").
- ✨ **Mảng literal lặp `[v; N]`** (kiểu Rust): `[false; 8]`, `[[7; 3]; 2]`.
  `N` phải là hằng biên dịch; `const` **cục bộ** giờ cũng dùng được làm cỡ mảng
  (`const CAP = 4; let a: [CAP]int`).
- 🐛 **Cờ căn giữa `{:^N}`** từng bị **bỏ qua âm thầm** (in ra căn phải) → nay
  đệm đúng hai bên (`[{:^7}]` với `"ab"` cho `[  ab   ]`).
- 🐛 **Trường mảng của struct** khi in ra là nhãn vô nghĩa `[…]` → nay **bung nội
  dung**: `S { flags: [true, true, true, true] }` (mảng nhiều chiều in đệ quy;
  dài hơn 8 phần tử thì rút gọn).
- 🐛 **Chuỗi định dạng hỏng** (`"{"` thiếu `}`, `}` đơn lẻ) từng lọt qua và in ra
  như ký tự thường → nay là lỗi kèm hướng dẫn `{{` / `}}`.
- 🐛 **Mã C sinh ra sạch cảnh báo**: mảng bất biến không còn gắn `const` (gây
  *discards const qualifier* khi truyền cho `*T`), `&x` trên biến `let` ép bỏ
  `const`, cận trên của `for i in a..b` mang đúng kiểu biến đếm (hết
  *sign-compare*). Toàn bộ bộ test biên dịch **không một cảnh báo** với
  `-Wall -Wextra`.
- 🛡️ **Giải tham chiếu `null` chắc chắn** (`let p: *S = null; p.v` — biến bất
  biến khởi tạo null, hoặc `null.f`) là lỗi biên dịch thay vì segfault. Con trỏ
  `mut` (có thể đã gán lại) không bị báo nhầm.
- 🧰 **Chẩn đoán lệch một tầng con trỏ**: truyền `p: *S` cho tham số `S` (hay
  ngược lại) giờ gợi ý `*p` / `&p`; riêng `self` trong method được nhắc rõ
  "`self` là con trỏ tới đối tượng nhận" (`self.dot(*self)`).
- 🐛 **`for mut x in arr` từng sửa một BẢN SAO** — `for mut x in a { x *= 10 }`
  không hề đổi `a` (âm thầm vô hiệu). Nay `x` là **tham chiếu** tới phần tử (như
  `iter_mut` của Rust) và ghi thẳng vào mảng; áp dụng cho cả phần tử struct và
  hàng của mảng nhiều chiều. `for mut` trên chuỗi/mảng literal (chỉ đọc / giá trị
  tạm) là lỗi có hướng dẫn.
- 🐛 **`match`/`?:` cho ra MẢNG theo giá trị** khai kiểu `[3]int` nhưng C phân rã
  thành con trỏ → `let b = a` chia sẻ bộ nhớ thay vì sao chép (và literal thì trỏ
  vào giá trị tạm đã hết hạn). Nay bị từ chối, nhất quán với việc cấm hàm trả về
  mảng theo giá trị.
- ✨ **In thẳng cả mảng**: `println("{}", a)` với mảng cỡ tĩnh giờ bung
  `[1, 2, 3]` (đệ quy cho mảng nhiều chiều, phần tử struct/enum/chuỗi; cắt bớt
  sau 8 phần tử) — trước đây là lỗi biên dịch dù mảng *trong* struct vẫn in
  được. `dbg(a)` cũng vậy.
- ✨ **`Type::item` kiểu Rust**: `Color::Red`, `Counter::new()` — đồng nghĩa
  `Type.item`. `::` đã được lexer nhận nhưng không parser nào dùng, nên
  `Color::Red` báo "cần biểu thức" rất khó hiểu; dùng `::` sau một *giá trị* nay
  báo lỗi kèm gợi ý dùng `.`.
- 🐛 **`s.at(i)` ngoài biên trả `'\0'` âm thầm** trong khi `a[i]` ngoài biên thì
  panic — lỗi off-by-one lọt qua không dấu vết. Nay `s.at(i)` cũng panic
  (`--no-checks` tắt cả hai như nhau).
- 🐛 **`--freestanding` rò rỉ lỗi C thô**: gọi `println` trong chế độ không-libc
  vỡ ở backend với `'stdout' undeclared` — một lỗi C khó hiểu với người viết G.
  Nay checker biết chế độ freestanding và từ chối ngay các built-in cần
  stdio/heap (`print*`, `format`, `dbg`, `assert_eq`, `g_alloc`…) cùng các method
  `str` cấp phát (`upper`, `sub`, `trim`…), kèm gợi ý dùng `outb`/`vol_write`;
  các method `str` chỉ đọc vẫn dùng được.
- 🐛 **Struct literal thiếu trường bị C zero-init âm thầm** — `S{a:1}` khi `S`
  có `b` vẫn biên dịch và `b` lặng lẽ thành 0. Đây là lỗi kinh điển khi *thêm
  trường mới*: mọi literal cũ vẫn qua được. Nay phải liệt kê đủ mọi trường (như
  Rust); `S{}` trên struct **rỗng** vẫn hợp lệ.
- 🐛 **Lỗi `import` trỏ sai dòng**: "không tìm thấy module" luôn báo dòng 1, tức
  chỉ vào một `import` *khác* khi file có nhiều import. Nay trỏ đúng dòng.
- 🧰 **`import mod/a`** (thiếu ngoặc kép) từng báo "cần khai báo cấp cao (gặp op
  '/')" — nay gợi ý thẳng `import "mod/a.g"`. Phụ chú `(gặp ...)` cũng được bỏ
  khỏi các lỗi cú pháp đã tự đủ nghĩa, vì nó trỏ vào token *sau* chỗ sai.
- 🐛 **`mut` trên tham số bị bỏ qua hoàn toàn** — parser nhận rồi vứt đi, nên
  `fn f(x: int) { x = 5 }` vẫn ghi được vào tham số *không* `mut`, trái hẳn với
  `let`. Nay `mut` có nghĩa thật: thiếu nó là lỗi, kèm gợi ý đúng ngữ cảnh
  (`mut x: ...`, không phải `let mut`). `self` vẫn luôn khả biến.
- 🐛 **Escape lạ bị nuốt âm thầm**: `"a\q"` cho ra `aq`, nên gõ nhầm `\d` hay
  quên nhân đôi `\` trong đường dẫn đều lặng lẽ sai. Nay là lỗi, có liệt kê
  escape hợp lệ.
- 🧰 **Chuỗi quên `"` đóng** từng báo lỗi ở *cuối file*; nay báo ngay tại dòng mở
  chuỗi khi gặp xuống dòng.
- 🧪 **Bộ test: 197 ca** (+21): `if_match_expr`, `str_methods`, `array_repeat`,
  `fmt_center`, `null_guard`, `foreach_mut`, `print_array`, `path_sep`,
  `str_at_bounds`, `import_line`, `param_mut`, 22 ca "phải lỗi" và một hạng mục test mới `tests/fail_fs/`
  (hợp lệ khi hosted, phải bị từ chối ở `--freestanding`).

## Mới trong 0.9.0 — 🔍 Bắt thêm lỗi tĩnh, sửa lỗi sinh mã

- 🐛 **Mảng literal ở vị trí biểu thức** (`sum([1, 2, 3], 3)`, `[7, 8, 9][1]`,
  `len([1, 2])`) từng rò `{ ... }` trần xuống C → lỗi backend. Nay là compound
  literal C99, chạy đúng.
- 🐛 **`extern fn memcpy/strlen/...`** với chữ ký G "gần đúng" (`*u8` thay vì
  `void*`) từng gây `conflicting types` vì runtime đã định nghĩa chúng → nay
  không phát lại nguyên mẫu. Khai báo lại một hàm với **chữ ký khác** (`extern fn
  puts(x: int)` sau `puts(s: str)`) là lỗi G; lệch với header libc được giải
  thích rõ thay vì "lỗi nội bộ".
- 🐛 **Thứ tự khởi tạo global:** `const A = B + 1; const B = A + 1` (chu trình /
  tham chiếu tiến) từng âm thầm đọc 0 → nay lỗi "dùng global khai báo SAU nó".
- 🛡️ **`match` trên `bool`** phải vét cạn (`true`/`false` hoặc `_`) và khi đủ hai
  nhánh được coi là vét cạn (không cần `return` thừa). Pattern hằng **nằm trong
  khoảng** của nhánh trước (`1..=10 => …; 5 => …`), khoảng lồng khoảng và khoảng
  **rỗng** (`9..=8`) là lỗi "nhánh không bao giờ chạy".
- 🛡️ **Trả về địa chỉ biến cục bộ** (`return &x`, `return &s.v`, `return &a[1]`)
  — con trỏ treo kinh điển — nay bị bắt lúc biên dịch.
- 🛡️ **Ghi vào `str`** (`s[0] = 'x'` — chuỗi chỉ đọc) và chỉ số hằng vượt biên
  chuỗi literal (`"abc"[4]`) là lỗi G thay vì lỗi C/segfault.
- 🛡️ **Chuỗi định dạng:** khoá lạ (`{name}`, `{0}`, `{q}`), cờ sai (`{:-5}`,
  `{:z}`), `{p}` trên số → lỗi rõ ràng (trước đây âm thầm in thập phân).
- 🛡️ **`bool` chỉ so sánh với `bool`** (`b == 1`, `x == true`, `e == true` bị
  từ chối — nhất quán với việc `let b: bool = 1` đã bị cấm).
- 🛡️ **Builtin chặt hơn:** `min/max/clamp/abs` đòi đối số số; `abs` trên kiểu
  không dấu, `clamp(x, 10, 1)` (lo > hi) là lỗi; `panic()` cần đúng 1 chuỗi,
  `panic(5)` gợi ý `format(...)`; `assert("x")` báo điều kiện sai kiểu.
- 🧰 **Thuộc tính & asm (OS-dev):** thuộc tính lặp (`@packed @packed`),
  `@align` + `@aligned`, `@naked` + `@inline` là lỗi; hàm `@naked` chỉ được chứa
  `asm { }` và không khai báo kiểu trả về; `main` không thể `@naked`; `asm { }`
  rỗng, ràng buộc output thiếu `=`/`+`, input có `=` được bắt sớm. Lỗi thuộc
  tính giờ báo hết một lượt.
- 🧪 **Bộ test: 161 ca** (+29): `array_lit_expr`, `match_bool_exhaustive`,
  `extern_libc_sig`, `global_init_order` và 25 ca "phải lỗi".

## Mới trong 0.8.0 — 🛡️ An toàn lúc chạy & suy luận kiểu chặt hơn

- 🛡️ **Kiểm tra lúc chạy (kiểu Rust):** chỉ số **động** trên mảng tĩnh
  (`a[i]` với `a: [4]int`) và chia/lấy dư số nguyên cho mẫu **không hằng**
  (`x / d`, `x %= d`) được kiểm — sai thì `G panic: chỉ số 5 vượt biên mảng cỡ 3
  tại file.g:12:7` / `chia cho 0 tại ...` thay vì đọc rác hoặc SIGFPE. Chi phí
  gần bằng 0 ở `-O2` (gcc hoisting); tắt bằng `gc --no-checks`. Hoạt động cả
  freestanding (panic = dừng CPU). Con trỏ/`[]T` không có độ dài nên không kiểm.
- 🐛 **`{:b}` trên số in ra `true`** (bị hiểu là bool) → nay in **nhị phân**
  (`{:08b}` đệm 0, số âm bù hai theo bề rộng kiểu); bool vẫn `true/false`.
- 🐛 **Kiểu của toán tử một ngôi:** `-a` với `a: u8` từng cho `4294967291`
  (in theo u8 nhưng C đã thăng cấp); nay `-`/`~` trên kiểu hẹp cho `int`, `-u32`
  cho `i64` (giá trị `-1` đúng). `'z' - 'a'` cho `int` 25 thay vì ký tự `\x19`.
- 🐛 **Mảng literal:** `[1, "x"]` từng lọt xuống C; `[]`/`[null, null]` sinh kiểu
  C không tồn tại. Nay báo lỗi rõ; số hỗn hợp lấy kiểu chung (`[1, 2.5]` → `[2]f64`,
  `[1, 5000000000]` → `[2]i64`); `let c: [2]*int = [null, null]` hợp lệ.
- 🐛 **Gán vào biến đếm `for i in a..b`** làm hỏng vòng lặp âm thầm → nay là lỗi
  (biến đếm bất biến như Rust; `for mut i in a..b` bị từ chối với hướng dẫn).
- 🛡️ **`match` trên enum với tên viết hoa lạ** (`C =>` khi enum chỉ có `A, B`) từng
  bị hiểu là *binding bắt tất cả* và nuốt các nhánh sau → nay báo lỗi + gợi ý.
- 🛡️ **`int → enum` ngầm** (`let e: E = 5`, `f(1)` với `f(e: E)`) bị từ chối —
  dùng `5 as E`; chiều `enum → int` vẫn tự do.
- 🛡️ `-`/`~`/`!` trên chuỗi/struct/mảng, `~` trên số thực, `{b}` trên số thực:
  lỗi G thay vì lỗi C.
- 🧪 **Bộ test: 132 ca** (+13): `runtime_checks`, `unary_types`, `fmt_binary`,
  `array_lit_infer` và 9 ca "phải lỗi".

## Mới trong 0.7.0 — 🔧 Đợt sửa lỗi & nâng cấp trình biên dịch

- 🐛 **Sinh mã C an toàn với mọi tên định danh:** tên G trùng **từ khoá C**
  (`switch`, `default`, `char`, `register`...), **hàm libc** (`exp`, `log`,
  `puts`...) hay **global/hàm cùng tên** với biến cục bộ từng rò thành lỗi C khó
  hiểu (`expected identifier`, `conflicting types`); nay được đổi tên nhất quán ở
  mọi vị trí (struct/enum/trường/biến thể/tham số/global/method).
- 🐛 **Khai báo con trỏ phức tạp đúng cú pháp C:** `*[3]int` (con trỏ tới mảng),
  `[2]*int` (mảng con trỏ), `*[2][3]int`, `**T`... trong tham số/`let`/ép kiểu.
  Trước đây `p: *[3]int` sinh `int* p[3]` (sai nghĩa).
- 🐛 **Ghi qua con trỏ tới biến `let`:** `let p = &x; *p = 6` từng bị C từ chối
  (`const __auto_type` suy ra `const int*`); nay `let` chỉ khoá **binding**, đúng
  như tài liệu.
- 🐛 **Đối số của `g_free`/`panic`/`printf`... không được kiểm kiểu/đổi tên** →
  lỗi C `'i' undeclared` khi biến bị đổi tên; đã sửa.
- 🐛 **Tràn số học hằng:** `100000 * 100000` từng cho `1410065408`; nay biểu thức
  hằng vượt 32-bit **tự nâng lên i64** (như literal lớn), còn gán vào kiểu hẹp là
  lỗi biên dịch rõ ràng.
- 🐛 **Gợi ý "có phải ...?" giờ ổn định** giữa các lần chạy (trước phụ thuộc thứ
  tự băm của set).
- ✨ **Báo NHIỀU lỗi trong một lần biên dịch** (phục hồi theo câu lệnh/hàm, như
  gcc/rustc): dòng cuối `gc: N lỗi`; biến khai báo lỗi vẫn được ghi nhận để
  không sinh chuỗi lỗi "chưa khai báo" vô ích. Tối đa 20 lỗi.
- ✨ **Method tĩnh** `Type.fn(args)` (không có `self`) — hàm tạo kiểu `Vec2.of(1, 2)`.
- ✨ **`impl` trên enum** (`c.name()`, `match *self`), **tên biến thể đầy đủ**
  `Color.Red` (dùng được cả trong pattern `match`), **so sánh struct `==`/`!=`**
  theo từng trường (đệ quy).
- ✨ **`static_assert(cond)`** không cần thông điệp; chấp nhận `sizeof(Struct)`.
- ✨ **`step` là từ khoá ngữ cảnh:** `let step = 2` hợp lệ; `step 0` là lỗi.
- 🛡️ **Chẩn đoán mới:** chỉ số **hằng** vượt biên mảng tĩnh (`a[5]` trên `[2]int`);
  `f64 → int/bool` **ngầm** (gán/tham số/trả về — yêu cầu `as`); `x as bool`,
  `str as int`, `f64 ↔ con trỏ`; `g_alloc`/`g_realloc`/`g_free` sai số tham số/kiểu (trước rò macro C); điều kiện `if`/`while`/`?:` là chuỗi/struct/void;
  `str < str` (so địa chỉ); **struct/enum định nghĩa hai lần**, `impl` cho kiểu không
  tồn tại, gọi method tĩnh trên giá trị và ngược lại; nhánh `match` **không bao giờ
  chạy** (pattern hằng lặp lại / sau `_`); hàm trả về mảng theo giá trị.
- 🧪 **Bộ test: 119 ca** (+25): 4 ca chạy mới (`c_names`, `ptr_decl`,
  `static_methods`, `const_widen`) và 21 ca "phải lỗi"; `run_tests.sh` cho phép
  file mong đợi nhiều dòng (kiểm `gc: 4 lỗi`). Ví dụ kernel `examples/kernel/`
  nay **được commit thật** (trước bị `.gitignore` nuốt) và boot được (kiểm bằng v86).

## Mới trong 0.6.0 — 🖥️ Hướng phát triển hệ điều hành

- 🧱 **Chế độ freestanding** (`--freestanding`): biên dịch **không libc**
  (`-ffreestanding -nostdlib`) — viết được kernel/firmware. Runtime tự cài
  `memcpy`/`memset`/`memmove`/`memcmp` và `panic`=dừng CPU. Thêm `-c` (xuất `.o`)
  và `-S` (xuất `.s`). Ví dụ boot được trong QEMU: [`examples/kernel/`](examples/kernel/).
- ⚙️ **Intrinsics phần cứng:** MMIO `vol_read`/`vol_write` (volatile); cổng I/O
  x86 `inb`/`outb`/`inw`/`outw`/`inl`/`outl`; điều khiển CPU `halt`/`cli`/`sti`/
  `pause`/`breakpoint`/`io_wait`/`rdtsc`.
- 🔢 **Thao tác bit theo bề rộng kiểu** (giống Rust): `popcount`/`clz`/`ctz`/
  `bswap`/`rotl`/`rotr` — `clz(1 as u8)`=7 chứ không phải 63.
- 🧮 **Bộ nhớ thô:** `memcpy`/`memset`/`memmove`/`memcmp` (hosted & freestanding).
- 🏷️ **Thuộc tính `@`:** `@packed`/`@align(N)` (struct/global), `@naked`/
  `@noreturn`/`@interrupt`/`@inline`/`@section`/`@used` (fn) — mô tả bố cục thanh
  ghi phần cứng & điểm vào kernel. Checker kiểm đích & đối số.
- 🛠️ **Inline asm MỞ RỘNG** (kiểu GCC): `asm { "..." : outputs : inputs : clobbers }`
  với `"ràng buộc"(biểu_thức)` — đọc/ghi thanh ghi, control register, MSR.
- 🔗 **`extern let`:** tham chiếu ký hiệu do assembly/linker script cấp
  (`extern let _bss_end: u8`).
- ✅ **`static_assert(cond, "msg")`:** khẳng định hằng lúc biên dịch (khoá bố cục).
- 🧪 **Bộ test mở rộng (86 ca):** thêm ca chạy cho intrinsics OS, một section
  **freestanding** biên dịch kernel thật bằng `--freestanding -c`, và các ca
  "phải lỗi" khoá chẩn đoán mới (thuộc tính, static_assert, MMIO sai kiểu).
- 🐛 **Sửa shadowing hàm/tham số:** tham số (con trỏ hàm) trùng tên một hàm toàn
  cục từng bị phân giải nhầm về hàm đó (số tham số sai); nay biến cục bộ che đúng.

## Mới trong 0.5.0

- 🐛 **Sửa lỗi cắt cụt phép dịch hằng:** `1 << 40` trước đây cho **0** (tính trong
  `int` 32-bit của C); nay tự nâng bề rộng 64-bit và cho đúng `1099511627776`.
  Literal lớn cũng suy luận đúng kiểu theo giá trị (`5000000000` → `i64`).
- 🐛 **Thứ tự đánh giá đối số tất định:** lời gọi hàm/method và `print`/`format`
  nay đánh giá đối số **trái-sang-phải** (kiểu Rust) — `f(next(), next(), next())`
  chạy đúng `1 2 3` thay vì phụ thuộc thứ tự không xác định của C.
- 🐛 **Sửa crash trình biên dịch:** `return`/`break`/`continue` trong `defer` từng
  làm trình sinh mã **đệ quy vô hạn** — nay báo lỗi G rõ ràng.
- ✨ **In trực tiếp `struct`/`enum`:** `println("{}", point)` → `Point { x: 3, y: 4 }`
  (đệ quy cho struct lồng); enum in ra **tên biến thể** (`Green`, không phải `1`).
- ✨ **`dbg(x)`** (kiểu Rust): in `[dbg dòng N] <giá trị>` ra stderr rồi trả lại `x`.
- ✨ **Khung kiểm thử generic:** `assert_eq`/`assert_ne` (dừng khi sai), `check_eq`/
  `check_ne` (ghi nhận & tiếp tục), `test_summary()` (trả số ca trượt). Hiển thị
  `trái`/`phải` cho **mọi kiểu** (chuỗi theo nội dung, enum theo tên, struct theo
  trường — đệ quy); kiểu mới tự dùng được nhờ hàm so sánh sinh tự động. Màu chỉ bật
  khi ra terminal.
- 🛡️ **Nhiều chẩn đoán mới:** chia-nguyên-sang-thực, dịch bit không hợp lệ
  (âm/≥64/vượt-bề-rộng), `match` enum chưa vét cạn, pattern enum sai loại, mã chết
  sau `return`, trường literal trùng, ép kiểu sang mảng/struct, số 0 dẫn đầu.
- 📚 **Thư viện chuẩn — mảng số thực (f64):** `sum_slice_f average_f array_max_f
  array_min_f dot norm scale_f fill_f variance_f stddev_f`, cùng `map_range char_at
  is_vowel ipow_nonneg triangular max3_f min3_f`.
- ✅ **Bộ test mở rộng** (73 ca): thêm ca cho dịch bit, thứ tự đánh giá, in struct/
  enum, `dbg`, mảng f64, và 10 ca "phải lỗi" khoá các chẩn đoán mới.

## Mới trong 0.4.0

- 🐛 **Sửa lỗi nghiêm trọng:** `==`/`!=` trên chuỗi (so theo nội dung) trước đây làm
  **đổ trình sinh mã** (`_is_stringy` chưa định nghĩa) — nay hoạt động và có test.
- ⌨️ **Đọc đầu vào (stdin):** `read_line` · `read_int` · `read_float` · `at_eof` —
  lần đầu G chạy được chương trình **tương tác** (trước đây hoàn toàn không có input).
- ✨ **`typeof(x)`** (chuỗi tên kiểu), **`swap(a, b)`** (tráo ô nhớ an toàn),
  **`alignof(T)`** (độ căn lề, bổ trợ `sizeof`).
- ✨ **`==`/`!=` trên chuỗi so theo NỘI DUNG** (`g_str_eq`, an toàn null) — nhất quán
  với `match` chuỗi, hết bẫy so địa chỉ literal.
- 🔧 **`as` ràng buộc đúng như Rust** (lỏng hơn tiền tố): `&x as *T` = `(&x) as *T`,
  `-x as int` = `(-x) as int`.
- 🔧 **Số học con trỏ** `p += n` / `p -= n` (di chuyển con trỏ `n` phần tử).
- 🛡️ **Chẩn đoán mới:** so sánh dây chuyền, so enum khác loại, `&<rvalue>`,
  `*<không phải con trỏ>`, chia cho hằng 0, `print` nhiều đối số thiếu format.
- 📚 **Thư viện chuẩn mở rộng mạnh:** thống kê (`variance`/`stddev`/`median_sorted`),
  tổ hợp (`ncr`/`npr`), lý thuyết số (`num_divisors`/`is_perfect`/`totient`/`sum_to`),
  sắp xếp nhanh & tìm cận (`quicksort`/`lower_bound`/`upper_bound`), sinh số ngẫu nhiên
  tất định (`rng_seed`/`rand_int`/`shuffle`), vị từ ký tự, và nhiều hơn nữa.
- ✅ **Bộ test mở rộng** (57 ca) + hỗ trợ **stdin** trong `run_tests.sh`
  (`tests/input/<tên>.txt`).

## Mới trong 0.3.0

- 🐛 **Sửa crash:** `match` có nhánh *binding + guard* (vd `x if x>0 =>`) trước đây
  làm đổ trình biên dịch — nay hạ bậc bằng `if + goto` đúng ngữ nghĩa "nhánh đầu thắng",
  guard sai thì *rớt xuống* nhánh kế.
- ✨ **Con trỏ hàm** `fn(P...)->R`: biến, tham số, trả về, mảng, trường struct, hàm bậc cao.
- ✨ **`format(...)`**: dựng chuỗi trên heap kiểu Zig.
- ✨ **Cỡ mảng là biểu thức hằng** `[N+1]`, `[2*M]`, `[CAP/2]` + `sizeof` fold đúng.
- ✨ **Mảng con trỏ** `[N]*T`.
- 📚 **Thư viện chuẩn mở rộng:** toán libm, tiện ích mảng/số nguyên/chuỗi, và bộ hàm bậc cao.
