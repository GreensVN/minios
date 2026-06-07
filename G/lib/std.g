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
