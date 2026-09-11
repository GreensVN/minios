// Mảng literal ở vị trí BIỂU THỨC (đối số hàm, chỉ số trực tiếp, len) — trước
// đây sinh '{ ... }' trần trong C (lỗi backend). Nay là compound literal.
fn sum(xs: []int, n: int) -> int {
    let mut s: int = 0
    for i in 0..n { s = s + xs[i] }
    return s
}
fn sum3(xs: [3]int) -> int { return xs[0] + xs[1] + xs[2] }

struct S { v: [2]int, m: [2][2]int }

fn main() -> int {
    println("{}", sum([1, 2, 3], 3))
    println("{}", sum3([4, 5, 6]))
    println("{}", [7, 8, 9][1])
    println("{}", len([1, 2]))
    let x: int = 3
    println("{}", [x, x * 2][1])
    // trường mảng trong struct literal vẫn là initializer thường
    let s: S = S{v: [1, 2], m: [[1, 2], [3, 4]]}
    println("{} {}", s.v[1], s.m[1][0])
    return 0
}
