// Giá trị trả về được TÍNH TRƯỚC khi chạy defer (như Zig/Go): 'defer n = 999'
// không được ảnh hưởng tới 'return n + 1'. Trước đây defer chạy trước nên hàm
// trả về 1000 — sai âm thầm.
struct P { x: int, y: int }
let mut n: int = 0
fn scalar() -> int { defer n = 999 return n + 1 }
fn strv() -> str { defer n = 7 let a = "ab" return a }
fn structv() -> P { defer n = 5 return P{x: n, y: 1} }
fn nested() -> int {
    defer println("outer")
    { defer println("inner") println("blk") }
    return 42
}
fn multi() -> int {
    defer println("d1")
    defer println("d2")
    return 3
}
fn main() -> int {
    println("{} {}", scalar(), n)
    n = 0
    println("{} {}", strv(), n)
    n = 0
    println("{} {}", structv(), n)
    println("{}", nested())
    println("{}", multi())
    return 0
}
