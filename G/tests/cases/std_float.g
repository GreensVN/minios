// Bộ hàm mảng số thực (f64) + tiện ích bổ sung trong std.
import std
fn main() -> int {
    let mut v: [4]f64 = [1.0, 2.0, 3.0, 4.0]
    let p: *f64 = &v[0]
    println("{f} {f} {f} {f}",
            sum_slice_f(p, 4), average_f(p, 4),
            array_max_f(p, 4), array_min_f(p, 4))     // 10 2.5 4 1
    println("{f:.4}", norm(p, 4))                      // 5.4772
    let mut w: [4]f64 = [4.0, 3.0, 2.0, 1.0]
    println("{f}", dot(p, &w[0], 4))                   // 20
    println("{}", triangular(5))                       // 15
    println("{}", ipow_nonneg(2, 10))                  // 1024
    println("{c} {b}", char_at("hello", 1), is_vowel('e'))  // e true
    println("{f}", map_range(5.0, 0.0, 10.0, 0.0, 100.0))   // 50
    return 0
}
