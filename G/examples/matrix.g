// matrix.g - mảng nhiều chiều + thuật toán ma trận
// Trình diễn: [N][M]T, lặp lồng nhau, mảng literal lồng.

fn main() -> int {
    // Ma trận 3x3 (mảng 2 chiều, khởi tạo bằng literal lồng)
    let a: [3][3]int = [
        [1, 2, 3],
        [4, 5, 6],
        [7, 8, 9],
    ]

    // In ma trận
    println("Ma trận A:")
    for i in 0..3 {
        print("  ")
        for j in 0..3 {
            print("{} ", a[i][j])
        }
        println("")
    }

    // Tổng đường chéo chính
    let mut trace: int = 0
    for i in 0..3 {
        trace += a[i][i]
    }
    println("Vết (trace) = {}", trace)

    // Chuyển vị vào ma trận mới
    let mut t: [3][3]int = [[0,0,0],[0,0,0],[0,0,0]]
    for i in 0..3 {
        for j in 0..3 {
            t[j][i] = a[i][j]
        }
    }
    println("Chuyển vị A[0]: {} {} {}", t[0][0], t[0][1], t[0][2])

    // Tổng toàn bộ phần tử
    let mut total: int = 0
    for i in 0..3 {
        for j in 0..3 {
            total += a[i][j]
        }
    }
    println("Tổng mọi phần tử = {}", total)

    return 0
}
