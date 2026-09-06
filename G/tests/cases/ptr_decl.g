// Khai báo kiểu con trỏ phức tạp và ghi qua con trỏ tới biến 'let'.
struct S { v: int }

fn fill(p: *[3]int, k: int) {            // con trỏ tới mảng
    for i in 0..3 { (*p)[i] = k + i }
}
fn sum_rows(m: *[2][3]int) -> int {
    let mut s = 0
    for i in 0..2 { for j in 0..3 { s += (*m)[i][j] } }
    return s
}
fn main() -> int {
    let x = 5
    let p = &x          // 'let' bất biến, nhưng ghi qua con trỏ vẫn hợp lệ
    *p = 6
    println("{}", x)

    let mut a: [3]int = [0, 0, 0]
    fill(&a, 10)
    println("{} {} {}", a[0], a[1], a[2])

    let mut m: [2][3]int = [[1, 2, 3], [4, 5, 6]]
    println("{}", sum_rows(&m))

    let mut ptrs: [2]*int = [&a[0], &a[2]]    // mảng con trỏ
    *ptrs[1] = 99
    println("{} {}", *ptrs[0], a[2])

    let mut s = S { v: 1 }
    let ps = &s
    ps.v = 42
    let pp = &ps                               // con trỏ tới con trỏ
    (*pp).v += 1
    println("{}", s.v)
    return 0
}
