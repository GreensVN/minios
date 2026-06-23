// Các tiện ích mới của thư viện chuẩn: thao tác bit u64, f64 min/max/abs/sign,
// và một số hàm mảng/chuỗi bổ sung. Kết quả tất định (ra stdout).
import std
fn main() -> int {
    // ---- bit ----
    println("reverse_bits(1) = {x}", reverse_bits(1))        // 8000000000000000
    println("reverse_bits(0x8000000000000000) = {}", reverse_bits(0x8000000000000000))  // 1
    println("parity(7) = {} parity(6) = {}", parity(7), parity(6))   // 1 0
    println("make_u64 = {x}", make_u64(0xDEAD, 0xBEEF))      // dead0000beef
    println("hi32 = {x} lo32 = {x}", hi32(0xAABBCCDD11223344), lo32(0xAABBCCDD11223344))

    // ---- f64 ----
    println("min_f = {} max_f = {}", min_f(2.0, 3.0), max_f(2.0, 3.0))   // 2 3
    println("abs_f = {} sign_f = {}", abs_f(-4.5), sign_f(-2.0))         // 4.5 -1
    println("saturate = {} {} {}", saturate(-0.5), saturate(0.25), saturate(1.5))  // 0 0.25 1

    // ---- mảng / chuỗi ----
    let arr = [1, 1, 2, 3, 3, 3, 4]
    println("distinct = {}", count_distinct_sorted(arr, 7))   // 4
    println("sum_range(1,5) = {}", sum_range(1, 5))           // 15
    println("sum_range(3,3) = {}", sum_range(3, 3))           // 3
    let xs = [3, 1, 4, 1, 5, 9, 2, 6]
    println("second_max = {}", second_max(xs, 8))            // 6
    println("is_empty: {} {}", is_empty(""), is_empty("x"))  // true false
    println("first = {c} last = {c}", first_char("hello"), last_char("hello"))  // h o
    return 0
}
