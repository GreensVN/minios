// Kiểm tra mảng các CON TRỎ: [N]*T (khác '*[N]T'). Trỏ vào biến/heap rồi deref.
import std

struct Node { val: int }

fn main() -> int {
    // Mảng con trỏ tới int, trỏ vào các biến cục bộ
    let mut a: int = 10
    let mut b: int = 20
    let mut c: int = 30
    let ps: [3]*int = [&a, &b, &c]
    let mut total: int = 0
    for i in 0..3 { total += *ps[i] }
    println("tổng qua mảng con trỏ = {}", total)   // 60

    // Sửa biến gốc qua con trỏ trong mảng
    *ps[1] = 200
    println("b sau khi sửa = {}", b)               // 200

    // Mảng con trỏ tới struct cấp phát động
    let mut nodes: [3]*Node = [null, null, null]
    for i in 0..3 {
        nodes[i] = g_alloc(Node, 1)
        nodes[i].val = (i + 1) * 100
    }
    let mut s: int = 0
    for i in 0..3 { s += nodes[i].val }
    println("tổng node = {}", s)                   // 600
    for i in 0..3 { g_free(nodes[i]) }
    return 0
}
