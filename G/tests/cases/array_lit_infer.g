// Suy luận mảng literal: kiểu chung cho số; 'null' với chú thích con trỏ
struct P { x: int }
fn main() -> int {
    let a = [1, 2.5, 3]
    println("{} {}", typeof(a), a[1])
    let b = [1, 2, 5000000000]
    println("{} {}", typeof(b), b[2])
    let c: [3]*int = [null, null, null]
    println("{}", c[2] == null)
    let d = [P { x: 1 }, P { x: 2 }]
    println("{}", d[1].x)
    let e = [[1, 2], [3, 4]]
    println("{} {}", typeof(e), e[1][0])
    return 0
}
