// std.g - thư viện chuẩn của G (viết bằng chính ngôn ngữ G)
// Dùng:  import std

// Ước số chung lớn nhất (thuật toán Euclid)
fn gcd(a: int, b: int) -> int {
    let mut x: int = abs(a)
    let mut y: int = abs(b)
    while y != 0 {
        let t: int = y
        y = x % y
        x = t
    }
    return x
}

// Bội số chung nhỏ nhất
fn lcm(a: int, b: int) -> int {
    if a == 0 || b == 0 {
        return 0
    }
    return abs(a / gcd(a, b) * b)
}

// Luỹ thừa số nguyên: base^exp
fn ipow(base: int, exp: int) -> i64 {
    let mut result: i64 = 1
    let mut b: i64 = base as i64
    let mut e: int = exp
    while e > 0 {
        if e % 2 == 1 {
            result = result * b
        }
        b = b * b
        e = e / 2
    }
    return result
}

// Kiểm tra số nguyên tố
fn is_prime(n: int) -> bool {
    if n < 2 {
        return false
    }
    let mut i: int = 2
    while i * i <= n {
        if n % i == 0 {
            return false
        }
        i += 1
    }
    return true
}

// Giai thừa
fn factorial(n: int) -> i64 {
    let mut r: i64 = 1
    for i in 2..=n {
        r = r * (i as i64)
    }
    return r
}

// Hoán đổi hai số nguyên qua con trỏ
fn swap_int(a: *int, b: *int) {
    let t: int = *a
    *a = *b
    *b = t
}

// Dấu của số nguyên: -1, 0, hoặc 1
fn sign(x: int) -> int {
    if x > 0 { return 1 }
    if x < 0 { return -1 }
    return 0
}

fn is_even(n: int) -> bool { return n % 2 == 0 }
fn is_odd(n: int) -> bool { return n % 2 != 0 }

// Căn bậc hai nguyên (làm tròn xuống) — thuật toán Newton
fn isqrt(n: int) -> int {
    if n < 2 { return n }
    let mut x: int = n
    let mut y: int = (x + 1) / 2
    while y < x {
        x = y
        y = (x + n / x) / 2
    }
    return x
}

// Fibonacci lặp (nhanh, không tràn stack như đệ quy)
fn fib(n: int) -> i64 {
    let mut a: i64 = 0
    let mut b: i64 = 1
    for _i in 0..n {
        let t: i64 = a + b
        a = b
        b = t
    }
    return a
}

// Tổng các phần tử của một mảng động (truyền kèm độ dài)
fn sum_slice(a: *int, n: int) -> i64 {
    let mut s: i64 = 0
    for i in 0..n {
        s = s + (a[i] as i64)
    }
    return s
}

// ---- Chuỗi: tái dùng thư viện C qua 'extern' ----
extern fn strcmp(a: str, b: str) -> int
extern fn strlen(s: str) -> usize

// Hai chuỗi bằng nhau?
fn streq(a: str, b: str) -> bool {
    return strcmp(a, b) == 0
}

// Độ dài chuỗi (số byte)
fn str_len(s: str) -> usize {
    return strlen(s)
}

// ---- Chuỗi nâng cao (runtime g_runtime.h; bản cấp phát heap -> nhớ g_free) ----
extern fn g_str_dup(s: str) -> str
extern fn g_str_concat(a: str, b: str) -> str
extern fn g_substr(s: str, start: isize, len: isize) -> str
extern fn g_str_eq(a: str, b: str) -> bool
extern fn g_str_index(hay: str, needle: str) -> isize
extern fn g_str_contains(hay: str, needle: str) -> bool
extern fn g_str_starts_with(s: str, pre: str) -> bool
extern fn g_str_ends_with(s: str, suf: str) -> bool
extern fn g_parse_int(s: str) -> i64
extern fn g_parse_float(s: str) -> f64
extern fn g_int_to_str(v: i64) -> str

// Nối hai chuỗi -> chuỗi mới trên heap (nhớ g_free)
fn str_concat(a: str, b: str) -> str { return g_str_concat(a, b) }

// Cắt chuỗi con an toàn (chỉ số/độ dài tự kẹp về biên)
fn substr(s: str, start: int, len: int) -> str {
    return g_substr(s, start as isize, len as isize)
}

// Chuỗi a có chứa b không?
fn str_contains(hay: str, needle: str) -> bool { return g_str_contains(hay, needle) }

// Chuỗi bắt đầu/kết thúc bằng tiền tố/hậu tố?
fn starts_with(s: str, pre: str) -> bool { return g_str_starts_with(s, pre) }
fn ends_with(s: str, suf: str) -> bool { return g_str_ends_with(s, suf) }

// Phân tích số nguyên/thực từ chuỗi (lỗi -> 0)
fn parse_int(s: str) -> i64 { return g_parse_int(s) }
fn parse_float(s: str) -> f64 { return g_parse_float(s) }

// Chuyển số nguyên thành chuỗi mới (heap; nhớ g_free)
fn int_to_str(v: i64) -> str { return g_int_to_str(v) }

// ---- Số học bổ sung ----

// Luỹ thừa modulo: (base^exp) mod m — nhanh, tránh tràn cho số vừa phải
fn powmod(base: i64, exp: i64, m: i64) -> i64 {
    if m == 1 { return 0 }
    let mut result: i64 = 1
    let mut b: i64 = base % m
    let mut e: i64 = exp
    while e > 0 {
        if e % 2 == 1 {
            result = (result * b) % m
        }
        e = e / 2
        b = (b * b) % m
    }
    return result
}

// Số lớn nhất trong ba số
fn max3(a: int, b: int, c: int) -> int {
    return max(a, max(b, c))
}

// Số nhỏ nhất trong ba số
fn min3(a: int, b: int, c: int) -> int {
    return min(a, min(b, c))
}

// Đếm số bit 1 (popcount)
fn popcount(x: u64) -> int {
    let mut n: u64 = x
    let mut count: int = 0
    while n != 0 {
        count += (n & 1) as int
        n = n >> 1
    }
    return count
}

// Số Fibonacci thứ n có vượt quá đệ quy? Dùng bản lặp 'fib' ở trên.

// Hoán đổi hai phần tử trong mảng động
fn swap_at(a: *int, i: int, j: int) {
    let t: int = a[i]
    a[i] = a[j]
    a[j] = t
}

// Sắp xếp nổi bọt mảng động tăng dần (tại chỗ)
fn bubble_sort(a: *int, n: int) {
    let mut i: int = 0
    while i < n {
        let mut j: int = 0
        while j < n - i - 1 {
            if a[j] > a[j + 1] {
                swap_at(a, j, j + 1)
            }
            j += 1
        }
        i += 1
    }
}

// Tìm kiếm nhị phân trên mảng đã sắp xếp; trả về chỉ số hoặc -1
fn binary_search(a: *int, n: int, target: int) -> int {
    let mut lo: int = 0
    let mut hi: int = n - 1
    while lo <= hi {
        let mid: int = lo + (hi - lo) / 2
        if a[mid] == target {
            return mid
        }
        if a[mid] < target {
            lo = mid + 1
        } else {
            hi = mid - 1
        }
    }
    return -1
}

// Tổng tích luỹ lớn nhất của một dãy con liên tiếp (Kadane)
fn max_subarray(a: *int, n: int) -> i64 {
    if n <= 0 { return 0 }
    let mut best: i64 = a[0] as i64
    let mut cur: i64 = a[0] as i64
    for i in 1..n {
        let v: i64 = a[i] as i64
        cur = max(v, cur + v) as i64
        best = max(best, cur) as i64
    }
    return best
}

// ============================================================================
//  Toán học dấu phẩy động — cầu nối tới libm qua 'extern' (đã liên kết -lm)
// ============================================================================
extern fn sqrt(x: f64) -> f64
extern fn cbrt(x: f64) -> f64
extern fn pow(base: f64, e: f64) -> f64
extern fn floor(x: f64) -> f64
extern fn ceil(x: f64) -> f64
extern fn round(x: f64) -> f64
extern fn trunc(x: f64) -> f64
extern fn fabs(x: f64) -> f64
extern fn fmod(x: f64, y: f64) -> f64
extern fn sin(x: f64) -> f64
extern fn cos(x: f64) -> f64
extern fn tan(x: f64) -> f64
extern fn atan2(y: f64, x: f64) -> f64
extern fn exp(x: f64) -> f64
extern fn log(x: f64) -> f64
extern fn log2(x: f64) -> f64
extern fn log10(x: f64) -> f64
extern fn hypot(x: f64, y: f64) -> f64

const G_PI: f64 = 3.14159265358979323846
const G_E:  f64 = 2.71828182845904523536

// Nội suy tuyến tính giữa a và b theo t∈[0,1]
fn lerp(a: f64, b: f64, t: f64) -> f64 { return a + (b - a) * t }

// Kẹp số thực vào [lo, hi]
fn clampf(x: f64, lo: f64, hi: f64) -> f64 {
    if x < lo { return lo }
    if x > hi { return hi }
    return x
}

// Đổi độ <-> radian
fn deg2rad(d: f64) -> f64 { return d * G_PI / 180.0 }
fn rad2deg(r: f64) -> f64 { return r * 180.0 / G_PI }

// ============================================================================
//  Tiện ích số nguyên
// ============================================================================

// Tổng các chữ số (theo trị tuyệt đối)
fn sum_digits(n: int) -> int {
    let mut x: int = abs(n)
    let mut s: int = 0
    while x > 0 { s += x % 10; x = x / 10 }
    return s
}

// Số chữ số (0 có 1 chữ số)
fn count_digits(n: int) -> int {
    let mut x: int = abs(n)
    let mut c: int = 1
    while x >= 10 { c += 1; x = x / 10 }
    return c
}

// Đảo ngược các chữ số (giữ dấu): reverse_int(-123) = -321
fn reverse_int(n: int) -> int {
    let mut x: int = abs(n)
    let mut r: int = 0
    while x > 0 { r = r * 10 + x % 10; x = x / 10 }
    return sign(n) * r
}

// Số có đối xứng (palindrome) không? (chỉ xét số không âm)
fn is_palindrome_int(n: int) -> bool {
    return n >= 0 && reverse_int(n) == n
}

// ============================================================================
//  Tiện ích mảng động (truyền con trỏ + độ dài). 'array_min/max' cần n >= 1.
// ============================================================================

// Gán mọi phần tử bằng v
fn fill(a: *int, n: int, v: int) {
    for i in 0..n { a[i] = v }
}

// Sao chép n phần tử từ src sang dst
fn array_copy(dst: *int, src: *int, n: int) {
    for i in 0..n { dst[i] = src[i] }
}

// Đảo ngược mảng tại chỗ
fn reverse(a: *int, n: int) {
    let mut i: int = 0
    let mut j: int = n - 1
    while i < j {
        swap_at(a, i, j)
        i += 1
        j -= 1
    }
}

// Phần tử lớn nhất / nhỏ nhất
fn array_max(a: *int, n: int) -> int {
    let mut m: int = a[0]
    for i in 1..n { if a[i] > m { m = a[i] } }
    return m
}
fn array_min(a: *int, n: int) -> int {
    let mut m: int = a[0]
    for i in 1..n { if a[i] < m { m = a[i] } }
    return m
}

// Vị trí xuất hiện đầu tiên của target, hoặc -1
fn index_of(a: *int, n: int, target: int) -> int {
    for i in 0..n { if a[i] == target { return i } }
    return -1
}

// Mảng có chứa target không?
fn contains(a: *int, n: int, target: int) -> bool {
    return index_of(a, n, target) >= 0
}

// Đếm số lần target xuất hiện
fn count_val(a: *int, n: int, target: int) -> int {
    let mut c: int = 0
    for i in 0..n { if a[i] == target { c += 1 } }
    return c
}

// Mảng đã sắp xếp tăng dần chưa?
fn is_sorted(a: *int, n: int) -> bool {
    for i in 1..n { if a[i - 1] > a[i] { return false } }
    return true
}

// Sắp xếp chèn (insertion sort) tăng dần, tại chỗ — ổn định, tốt cho mảng nhỏ
fn insertion_sort(a: *int, n: int) {
    let mut i: int = 1
    while i < n {
        let key: int = a[i]
        let mut j: int = i - 1
        while j >= 0 && a[j] > key {
            a[j + 1] = a[j]
            j -= 1
        }
        a[j + 1] = key
        i += 1
    }
}

// ============================================================================
//  Hàm bậc cao (truyền CON TRỎ HÀM) — map / filter / fold / any / all ...
// ============================================================================

// Áp f cho từng phần tử src, ghi vào dst (n phần tử)
fn map_into(dst: *int, src: *int, n: int, f: fn(int) -> int) {
    for i in 0..n { dst[i] = f(src[i]) }
}

// Lọc phần tử thoả pred vào dst; trả về số phần tử giữ lại
fn filter_into(dst: *int, src: *int, n: int, pred: fn(int) -> bool) -> int {
    let mut k: int = 0
    for i in 0..n {
        if pred(src[i]) {
            dst[k] = src[i]
            k += 1
        }
    }
    return k
}

// Gộp toàn mảng bằng f, bắt đầu từ init: fold(a,n,0,add) = tổng
fn fold(a: *int, n: int, init: int, f: fn(int, int) -> int) -> int {
    let mut acc: int = init
    for i in 0..n { acc = f(acc, a[i]) }
    return acc
}

// Đếm số phần tử thoả pred
fn count_if(a: *int, n: int, pred: fn(int) -> bool) -> int {
    let mut c: int = 0
    for i in 0..n { if pred(a[i]) { c += 1 } }
    return c
}

// Có ít nhất một / tất cả phần tử thoả pred?
fn any(a: *int, n: int, pred: fn(int) -> bool) -> bool {
    for i in 0..n { if pred(a[i]) { return true } }
    return false
}
fn all(a: *int, n: int, pred: fn(int) -> bool) -> bool {
    for i in 0..n { if !pred(a[i]) { return false } }
    return true
}

// Chỉ số phần tử đầu tiên thoả pred, hoặc -1
fn find_first(a: *int, n: int, pred: fn(int) -> bool) -> int {
    for i in 0..n { if pred(a[i]) { return i } }
    return -1
}

// ============================================================================
//  Chuỗi nâng cao (runtime; bản cấp phát heap -> nhớ g_free)
// ============================================================================
extern fn g_str_rev(s: str) -> str
extern fn g_str_upper(s: str) -> str
extern fn g_str_lower(s: str) -> str
extern fn g_str_repeat(s: str, k: isize) -> str
extern fn g_str_count(s: str, c: char) -> isize

// Đảo ngược chuỗi -> chuỗi mới (heap)
fn str_rev(s: str) -> str { return g_str_rev(s) }

// Chuyển HOA / thường -> chuỗi mới (heap)
fn to_upper(s: str) -> str { return g_str_upper(s) }
fn to_lower(s: str) -> str { return g_str_lower(s) }

// Lặp chuỗi k lần -> chuỗi mới (heap)
fn str_repeat(s: str, k: int) -> str { return g_str_repeat(s, k as isize) }

// Đếm số lần ký tự c xuất hiện trong chuỗi
fn count_char(s: str, c: char) -> int { return g_str_count(s, c) as int }

// Vị trí xuất hiện đầu tiên của 'needle' trong 'hay', hoặc -1
fn str_index(hay: str, needle: str) -> int { return g_str_index(hay, needle) as int }

// ============================================================================
//  Sinh số giả ngẫu nhiên (xorshift64 — viết bằng chính ngôn ngữ G)
//  Dùng:  rng_seed(12345)  hoặc  rng_seed_time()  rồi  rand_int(0, 100) ...
//  (Tên 'rng_seed' thay vì 'srand' để không trùng hàm libc 'srand'.)
// ============================================================================
extern fn g_time_seed() -> u64
extern fn g_clock_secs() -> f64

// Trạng thái sinh số toàn cục (phải khác 0 để xorshift hoạt động)
let mut G_RNG_STATE: u64 = 0x2545F4914F6CDD1D

// Gieo hạt cố định (tái lập kết quả). seed=0 được nâng lên 1.
fn rng_seed(seed: u64) {
    G_RNG_STATE = seed
    if G_RNG_STATE == 0 { G_RNG_STATE = 1 }
}

// Gieo hạt theo thời gian (khác nhau mỗi lần chạy)
fn rng_seed_time() { rng_seed(g_time_seed()) }

// Số 64-bit giả ngẫu nhiên kế tiếp (xorshift64)
fn rand_u64() -> u64 {
    let mut x: u64 = G_RNG_STATE
    x = x ^ (x << 13)
    x = x ^ (x >> 7)
    x = x ^ (x << 17)
    G_RNG_STATE = x
    return x
}

// Số nguyên ngẫu nhiên trong [lo, hi) (nửa mở). hi<=lo -> lo.
fn rand_range(lo: i64, hi: i64) -> i64 {
    if hi <= lo { return lo }
    let span: u64 = (hi - lo) as u64
    return lo + (rand_u64() % span) as i64
}

// Số nguyên ngẫu nhiên trong [lo, hi)
fn rand_int(lo: int, hi: int) -> int {
    return rand_range(lo as i64, hi as i64) as int
}

// Số thực ngẫu nhiên trong [0.0, 1.0)
fn rand_float() -> f64 {
    return (rand_u64() >> 11) as f64 / 9007199254740992.0
}

// Tung đồng xu
fn coin_flip() -> bool { return (rand_u64() & 1) == 1 }

// Xáo trộn mảng tại chỗ (Fisher–Yates)
fn shuffle(a: *int, n: int) {
    let mut i: int = n - 1
    while i > 0 {
        let j: int = rand_int(0, i + 1)
        swap_at(a, i, j)
        i -= 1
    }
}

// ============================================================================
//  Số học bổ sung (bit, luỹ thừa hai, mod sàn)
// ============================================================================

// Ước chung lớn nhất của ba số
fn gcd3(a: int, b: int, c: int) -> int { return gcd(gcd(a, b), c) }

// Lấy dư "sàn" (kết quả luôn cùng dấu với m): mod_floor(-1, 3) = 2
fn mod_floor(a: int, m: int) -> int {
    let r: int = a % m
    if r != 0 && (r < 0) != (m < 0) { return r + m }
    return r
}

// n có phải luỹ thừa của hai?
fn is_power_of_two(n: i64) -> bool { return n > 0 && (n & (n - 1)) == 0 }

// Luỹ thừa hai nhỏ nhất >= n
fn next_power_of_two(n: i64) -> i64 {
    if n <= 1 { return 1 }
    let mut p: i64 = 1
    while p < n { p = p << 1 }
    return p
}

// Số bit 0 dẫn đầu / theo sau của một u64 (0 -> 64)
fn leading_zeros(x: u64) -> int {
    if x == 0 { return 64 }
    let mut n: int = 0
    let mut v: u64 = x
    while (v & 0x8000000000000000) == 0 { n += 1; v = v << 1 }
    return n
}
fn trailing_zeros(x: u64) -> int {
    if x == 0 { return 64 }
    let mut n: int = 0
    let mut v: u64 = x
    while (v & 1) == 0 { n += 1; v = v >> 1 }
    return n
}

// ============================================================================
//  Tiện ích mảng nâng cao: sắp xếp nhanh, tìm cận, xoay, khử trùng lặp
// ============================================================================

// Tổng / tích các phần tử
fn array_sum(a: *int, n: int) -> i64 { return sum_slice(a, n) }
fn array_product(a: *int, n: int) -> i64 {
    let mut p: i64 = 1
    for i in 0..n { p = p * (a[i] as i64) }
    return p
}

// Trung bình cộng (số thực)
fn average(a: *int, n: int) -> f64 {
    if n == 0 { return 0.0 }
    return (sum_slice(a, n) as f64) / (n as f64)
}

// Chỉ số của phần tử nhỏ nhất / lớn nhất
fn min_index(a: *int, n: int) -> int {
    let mut mi: int = 0
    for i in 1..n { if a[i] < a[mi] { mi = i } }
    return mi
}
fn max_index(a: *int, n: int) -> int {
    let mut mi: int = 0
    for i in 1..n { if a[i] > a[mi] { mi = i } }
    return mi
}

// Hai mảng n phần tử có bằng nhau từng phần tử không?
fn array_eq(a: *int, b: *int, n: int) -> bool {
    for i in 0..n { if a[i] != b[i] { return false } }
    return true
}

// Đảo ngược đoạn [lo, hi] tại chỗ
fn reverse_range(a: *int, lo: int, hi: int) {
    let mut i: int = lo
    let mut j: int = hi
    while i < j { swap_at(a, i, j); i += 1; j -= 1 }
}

// Phân hoạch Lomuto quanh chốt a[hi]; trả về vị trí chốt cuối cùng
fn partition(a: *int, lo: int, hi: int) -> int {
    let pivot: int = a[hi]
    let mut i: int = lo - 1
    let mut j: int = lo
    while j < hi {
        if a[j] <= pivot { i += 1; swap_at(a, i, j) }
        j += 1
    }
    swap_at(a, i + 1, hi)
    return i + 1
}

// Sắp xếp nhanh đoạn [lo, hi] (đệ quy)
fn quicksort_range(a: *int, lo: int, hi: int) {
    if lo < hi {
        let p: int = partition(a, lo, hi)
        quicksort_range(a, lo, p - 1)
        quicksort_range(a, p + 1, hi)
    }
}

// Sắp xếp nhanh toàn mảng tăng dần (tại chỗ)
fn quicksort(a: *int, n: int) { quicksort_range(a, 0, n - 1) }

// Cận dưới/trên (mảng đã sắp xếp): chỉ số chèn giữ thứ tự
fn lower_bound(a: *int, n: int, target: int) -> int {
    let mut lo: int = 0
    let mut hi: int = n
    while lo < hi {
        let mid: int = lo + (hi - lo) / 2
        if a[mid] < target { lo = mid + 1 } else { hi = mid }
    }
    return lo
}
fn upper_bound(a: *int, n: int, target: int) -> int {
    let mut lo: int = 0
    let mut hi: int = n
    while lo < hi {
        let mid: int = lo + (hi - lo) / 2
        if a[mid] <= target { lo = mid + 1 } else { hi = mid }
    }
    return lo
}

// Xoay trái k vị trí (tại chỗ, dùng 3 lần đảo ngược)
fn rotate_left(a: *int, n: int, k: int) {
    if n <= 1 { return }
    let s: int = mod_floor(k, n)
    if s == 0 { return }
    reverse_range(a, 0, s - 1)
    reverse_range(a, s, n - 1)
    reverse_range(a, 0, n - 1)
}

// Khử phần tử trùng liên tiếp (mảng đã sắp xếp) -> độ dài mới
fn dedup_sorted(a: *int, n: int) -> int {
    if n == 0 { return 0 }
    let mut w: int = 1
    for i in 1..n {
        if a[i] != a[w - 1] { a[w] = a[i]; w += 1 }
    }
    return w
}

// ============================================================================
//  Vị từ & biến đổi ký tự (ASCII) — không cấp phát
// ============================================================================
fn is_digit(c: char) -> bool { return c >= '0' && c <= '9' }
fn is_upper(c: char) -> bool { return c >= 'A' && c <= 'Z' }
fn is_lower(c: char) -> bool { return c >= 'a' && c <= 'z' }
fn is_alpha(c: char) -> bool { return is_upper(c) || is_lower(c) }
fn is_alnum(c: char) -> bool { return is_alpha(c) || is_digit(c) }
fn is_space(c: char) -> bool {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r'
}
fn to_upper_char(c: char) -> char { if is_lower(c) { return (c - 32) as char } return c }
fn to_lower_char(c: char) -> char { if is_upper(c) { return (c + 32) as char } return c }

// Chữ số '0'..'9' -> 0..9 (ký tự khác -> -1)
fn digit_to_int(c: char) -> int {
    if is_digit(c) { return (c - '0') as int }
    return -1
}

// ============================================================================
//  Thêm chuỗi (runtime; cấp phát heap -> nhớ g_free)
// ============================================================================
extern fn g_str_trim(s: str) -> str
extern fn g_str_replace_char(s: str, from: char, to: char) -> str

// Cắt khoảng trắng đầu/cuối -> chuỗi mới (heap)
fn trim(s: str) -> str { return g_str_trim(s) }

// Thay mọi ký tự 'from' bằng 'to' -> chuỗi mới (heap)
fn replace_char(s: str, from: char, to: char) -> str {
    return g_str_replace_char(s, from, to)
}

// ============================================================================
//  Toán học bổ sung (f64)
// ============================================================================
const G_TAU: f64 = 6.28318530717958647692
const G_PHI: f64 = 1.61803398874989484820

// Hàm sigmoid logistic
fn sigmoid(x: f64) -> f64 { return 1.0 / (1.0 + exp(-x)) }

// Giai thừa dạng số thực (cho n lớn không tràn i64)
fn factorial_f(n: int) -> f64 {
    let mut r: f64 = 1.0
    for i in 2..=n { r = r * (i as f64) }
    return r
}

// Bình phương / lập phương nhanh
fn sq_f(x: f64) -> f64 { return x * x }
fn cube_f(x: f64) -> f64 { return x * x * x }

// ============================================================================
//  Đọc đầu vào (stdin) — mở khoá chương trình tương tác
//  read_line trả chuỗi mới trên heap (nhớ g_free); null khi hết đầu vào (EOF).
// ============================================================================
extern fn g_read_line() -> str
extern fn g_read_int() -> i64
extern fn g_read_float() -> f64
extern fn g_eof() -> bool

// Đọc một dòng (không gồm '\n') -> chuỗi mới (heap); null khi EOF
fn read_line() -> str { return g_read_line() }

// Đọc một số nguyên / số thực (bỏ qua khoảng trắng dẫn đầu); 0 nếu thất bại
fn read_int() -> i64 { return g_read_int() }
fn read_float() -> f64 { return g_read_float() }

// Đã hết đầu vào (EOF) chưa?
fn at_eof() -> bool { return g_eof() }

// ============================================================================
//  Thống kê (trên mảng số nguyên động)
// ============================================================================

// Phương sai tổng thể (chia cho n)
fn variance(a: *int, n: int) -> f64 {
    if n == 0 { return 0.0 }
    let m: f64 = average(a, n)
    let mut s: f64 = 0.0
    for i in 0..n {
        let d: f64 = (a[i] as f64) - m
        s = s + d * d
    }
    return s / (n as f64)
}

// Độ lệch chuẩn tổng thể
fn stddev(a: *int, n: int) -> f64 { return sqrt(variance(a, n)) }

// Trung vị của mảng ĐÃ SẮP XẾP (n chẵn -> trung bình hai phần tử giữa)
fn median_sorted(a: *int, n: int) -> f64 {
    if n == 0 { return 0.0 }
    if n % 2 == 1 { return a[n / 2] as f64 }
    return ((a[n / 2 - 1] + a[n / 2]) as f64) / 2.0
}

// ============================================================================
//  Tổ hợp & lý thuyết số bổ sung
// ============================================================================

// Chỉnh hợp P(n, r) = n!/(n-r)!
fn npr(n: int, r: int) -> i64 {
    if r < 0 || r > n { return 0 }
    let mut result: i64 = 1
    for i in 0..r { result = result * ((n - i) as i64) }
    return result
}

// Tổ hợp C(n, r) = n!/(r!(n-r)!) — nhân/chia xen kẽ để tránh tràn sớm
fn ncr(n: int, r: int) -> i64 {
    if r < 0 || r > n { return 0 }
    let mut rr: int = r
    if rr > n - rr { rr = n - rr }
    let mut result: i64 = 1
    for i in 0..rr {
        result = result * ((n - i) as i64)
        result = result / ((i + 1) as i64)
    }
    return result
}

// Tổng 1 + 2 + ... + n (công thức Gauss)
fn sum_to(n: int) -> i64 {
    let nn: i64 = n as i64
    return nn * (nn + 1) / 2
}

// Số ước dương của |n| (0 -> 0)
fn num_divisors(n: int) -> int {
    let m: int = abs(n)
    if m == 0 { return 0 }
    let mut count: int = 0
    let mut i: int = 1
    while i * i <= m {
        if m % i == 0 {
            count += 1
            if i != m / i { count += 1 }
        }
        i += 1
    }
    return count
}

// n có phải số hoàn hảo (tổng ước thực sự = chính nó)?
fn is_perfect(n: int) -> bool {
    if n < 2 { return false }
    let mut s: int = 1
    let mut i: int = 2
    while i * i <= n {
        if n % i == 0 {
            s += i
            if i != n / i { s += n / i }
        }
        i += 1
    }
    return s == n
}

// Hàm Euler phi (đếm số nguyên tố cùng nhau với n trong [1, n])
fn totient(n: int) -> int {
    if n <= 0 { return 0 }
    let mut result: int = n
    let mut m: int = n
    let mut p: int = 2
    while p * p <= m {
        if m % p == 0 {
            while m % p == 0 { m = m / p }
            result = result - result / p
        }
        p += 1
    }
    if m > 1 { result = result - result / m }
    return result
}

// ============================================================================
//  Tiện ích mảng & ký tự bổ sung
// ============================================================================

// Tổng tích luỹ: dst[i] = src[0] + ... + src[i]
fn prefix_sum(dst: *int, src: *int, n: int) {
    let mut acc: int = 0
    for i in 0..n {
        acc = acc + src[i]
        dst[i] = acc
    }
}

// Kẹp mọi phần tử vào [lo, hi] tại chỗ
fn clamp_array(a: *int, n: int, lo: int, hi: int) {
    for i in 0..n { a[i] = clamp(a[i], lo, hi) }
}

// Giá trị của một chữ số hex ('0'..'9','a'..'f','A'..'F') -> 0..15; khác -> -1
fn hex_val(c: char) -> int {
    if c >= '0' && c <= '9' { return (c - '0') as int }
    if c >= 'a' && c <= 'f' { return (c - 'a' + 10) as int }
    if c >= 'A' && c <= 'F' { return (c - 'A' + 10) as int }
    return -1
}

// So sánh xấp xỉ hai số thực trong sai số eps
fn approx_eq(a: f64, b: f64, eps: f64) -> bool {
    let d: f64 = a - b
    let ad: f64 = (d < 0.0) ? -d : d
    return ad <= eps
}
