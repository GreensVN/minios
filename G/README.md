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

### Inline Assembly
```g
asm { "nop" "nop" }
```

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
| `{b}` | bool → true/false |
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

> Compiler **kiểm tra số placeholder khớp số đối số** *và* **khớp kiểu với
> specifier** (vd `{s}` cho số, `{d}` cho float đều báo lỗi).

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
`len(x)` · `assert(cond[, msg])` · `panic(msg)` · `unreachable([msg])` · `todo([msg])` · `min(a,b)` · `max(a,b)` · `abs(x)` · `clamp(x,lo,hi)` · `swap(a,b)` · `typeof(x)` · `format(fmt, ...)` · `g_alloc(T,n)` · `g_realloc(p,T,n)` · `g_free(p)` · `sizeof(T)` · `sizeof(expr)` · `alignof(T)`.

- `swap(a, b)` tráo nội dung hai **ô nhớ** cùng kiểu (đánh giá địa chỉ đúng *một lần* — an toàn với `swap(a[i()], a[j()])`); hai ô phải khả biến.
- `typeof(x)` trả về **chuỗi** tên kiểu suy luận (`"i64"`, `"f64"`, `"str"`, `"fn(int) -> int"`...) — hằng lúc biên dịch, không đánh giá `x`.
- `alignof(T)` cho **độ căn lề** của kiểu (bổ trợ `sizeof`) — `alignof(i64)`, `alignof(*Node)`, `alignof([4]int)`.

`unreachable()`/`todo()` không bao giờ trả về (như `panic`) nên thoả mãn phân
tích "mọi nhánh đều return" — tiện cho nhánh mặc định hoặc hàm chưa hoàn thiện.

### Module / `import`
```g
import std            // nạp lib/std.g
import "helpers.g"    // nạp file cùng thư mục
```
`lib/std.g` cung cấp:
- **Số học:** `gcd lcm gcd3 ipow is_prime factorial sign is_even is_odd isqrt fib powmod max3 min3 popcount sum_digits count_digits reverse_int is_palindrome_int mod_floor is_power_of_two next_power_of_two leading_zeros trailing_zeros sum_to num_divisors is_perfect totient`
- **Tổ hợp & thống kê:** `ncr npr variance stddev median_sorted` (+ `average`)
- **Toán f64 (libm):** `sqrt cbrt pow floor ceil round trunc fabs fmod sin cos tan atan2 exp log log2 log10 hypot lerp clampf deg2rad rad2deg sigmoid factorial_f sq_f cube_f approx_eq` (+ hằng `G_PI`, `G_E`, `G_TAU`, `G_PHI`)
- **Mảng:** `sum_slice swap_int swap_at bubble_sort insertion_sort quicksort binary_search lower_bound upper_bound max_subarray fill array_copy reverse reverse_range array_max array_min min_index max_index index_of contains count_val is_sorted array_sum array_product array_eq rotate_left dedup_sorted prefix_sum clamp_array`
- **Bậc cao (con trỏ hàm):** `map_into filter_into fold count_if any all find_first`
- **Chuỗi:** `streq str_len str_concat substr str_contains starts_with ends_with parse_int parse_float int_to_str str_rev to_upper to_lower str_repeat count_char str_index trim replace_char`
- **Ký tự (ASCII):** `is_digit is_upper is_lower is_alpha is_alnum is_space to_upper_char to_lower_char digit_to_int hex_val`
- **Đầu vào (stdin):** `read_line read_int read_float at_eof`
- **Ngẫu nhiên (xorshift64):** `rng_seed rng_seed_time rand_u64 rand_range rand_int rand_float coin_flip shuffle`

> Các hàm chuỗi trả chuỗi mới (vd `str_concat`, `substr`, `int_to_str`) cấp phát
> trên heap — nhớ `g_free` khi dùng xong.

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

> **Ngữ nghĩa vòng lặp:** `for i in a..b` lượng giá cận `b` (và `step`) **đúng
> một lần** khi vào vòng (giống Rust) — đổi `b` trong thân không làm dài thêm
> vòng lặp, và hàm dùng làm cận chỉ được gọi một lần.

## Giới hạn hiện tại

- `match` so khớp bằng `==`/`strcmp`/khoảng + guard `if` (chưa destructuring struct/enum dữ liệu).
- `asm` là *basic asm* GCC (chưa ràng buộc toán tử `%0/%1`).
- Chưa có generic, trait, ownership/borrow-checker đầy đủ.
- Có **con trỏ hàm** (`fn(T)->R`) nhưng **chưa có closure** bắt biến môi trường.
- Cỡ mảng là biểu thức **hằng** (chưa cỡ động lúc chạy — dùng `g_alloc`).

Một nền tảng vững để mở rộng tiếp. 🚀

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
