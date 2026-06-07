// Kiểm tra mảng nhiều chiều, mảng động, len trên literal, foreach trên literal.

fn main() -> int {
    // Mảng 2 chiều với literal lồng
    let grid: [2][3]int = [[1, 2, 3], [4, 5, 6]]
    println("grid[0][2]={}, grid[1][0]={}", grid[0][2], grid[1][0])

    // Ghi vào mảng 2 chiều
    let mut m: [2][2]int = [[0, 0], [0, 0]]
    m[0][0] = 1; m[0][1] = 2; m[1][0] = 3; m[1][1] = 4
    let mut s: int = 0
    for i in 0..2 {
        for j in 0..2 {
            s += m[i][j]
        }
    }
    println("tổng ma trận = {}", s)

    // len trên mảng literal
    println("len([1,2,3,4,5]) = {}", len([1, 2, 3, 4, 5]))

    // foreach trên mảng literal
    let mut t: int = 0
    for x in [10, 20, 30, 40] {
        t += x
    }
    println("foreach literal = {}", t)

    // Mảng 3 chiều
    let cube: [2][2][2]int = [[[1, 2], [3, 4]], [[5, 6], [7, 8]]]
    println("cube[1][1][1] = {}", cube[1][1][1])

    // Mảng động (heap) qua con trỏ; ghi qua binding 'let' (bất biến) vẫn được
    let buf: *int = g_alloc(int, 4)
    for i in 0..4 {
        buf[i] = i * 100
    }
    println("buf[3] = {}", buf[3])
    g_free(buf)

    return 0
}
