// 'let P{x, y} = v' rút trích trường ra biến cùng tên; 'x: tên_khác' để đổi tên;
// 'let mut' cho binding khả biến. Giá trị nguồn được đánh giá đúng MỘT lần.
struct P { x: int, y: int }
struct Wrap { inner: P, tag: str }
let mut calls: int = 0
fn mk() -> P { calls += 1 return P{x: 3, y: 4} }
fn main() -> int {
    let p = P{x: 1, y: 2}
    let P{x, y} = p
    println("{} {}", x, y)

    let P{x: a, y: b} = mk()
    println("{} {} calls={}", a, b, calls)

    let mut P{x: mx, y: my} = p
    mx += 10
    my += 20
    println("{} {} | gốc {} {}", mx, my, p.x, p.y)

    // chỉ lấy một phần, và trên trường struct lồng
    let w = Wrap{inner: P{x: 7, y: 8}, tag: "ok"}
    let Wrap{tag} = w
    let P{x: ix} = w.inner
    println("{} {}", tag, ix)
    return 0
}
