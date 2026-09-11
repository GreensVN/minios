// Global tham chiếu global khai báo TRƯỚC nó (kể cả qua const/cỡ mảng).
const B: int = 2
const A: int = B + 1
let arr: [A]int = [1, 2, 3]
let mut cnt: int = A * 2
fn main() -> int {
    println("{} {} {}", A, len(arr), cnt)
    return 0
}
