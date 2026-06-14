// Kiểm tra cỡ mảng là BIỂU THỨC HẰNG: [N], [N+1], [2*M], [CAP/2], lồng nhiều chiều,
// và sizeof trên kiểu mảng tượng trưng (fold thành hằng số biên dịch).
const N: int = 4
const M: int = 3
const CAP: int = 8

fn main() -> int {
    // cỡ = tên hằng
    let a: [N]int = [10, 20, 30, 40]
    // cỡ = biểu thức hằng
    let b: [N + 1]int = [1, 2, 3, 4, 5]
    let c: [2 * M]int = [1, 1, 1, 1, 1, 1]
    let d: [CAP / 2]int = [7, 7, 7, 7]

    println("len: a={}, b={}, c={}, d={}", len(a), len(b), len(c), len(d))

    let mut sa: int = 0
    for i in 0..len(a) { sa += a[i] }
    println("tổng a = {}", sa)

    // mảng nhiều chiều với chiều biểu thức hằng
    let grid: [M][M + 1]int = [
        [1, 2, 3, 4],
        [5, 6, 7, 8],
        [9, 10, 11, 12],
    ]
    println("grid[2][3] = {}", grid[2][3])

    // sizeof trên kiểu mảng hằng -> đúng số byte
    println("sizeof([CAP]int) = {}, sizeof([N+1]i64) = {}",
            sizeof([CAP]int), sizeof([N + 1]i64))
    return 0
}
