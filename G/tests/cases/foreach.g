// Kiểm tra vòng lặp foreach (for x in mảng / chuỗi) + break/continue
fn main() -> int {
    let nums: [5]int = [3, 1, 4, 1, 5]

    // duyệt mảng tĩnh, cộng dồn
    let mut tong: int = 0
    for x in nums {
        tong += x
    }
    println("tổng mảng = {}", tong)

    // foreach + continue (bỏ số chẵn) + break
    print("số lẻ: ")
    for x in nums {
        if x % 2 == 0 {
            continue
        }
        if x > 4 {
            break
        }
        print("{} ", x)
    }
    println("")

    // duyệt từng ký tự trong chuỗi
    let mut hoa: int = 0
    for c in "Hello, G!" {
        if c >= 'A' && c <= 'Z' {
            hoa += 1
        }
    }
    println("số chữ hoa = {}", hoa)

    // foreach lồng nhau
    let a: [2]int = [10, 20]
    let b: [3]int = [1, 2, 3]
    let mut s: int = 0
    for i in a {
        for j in b {
            s += i * j
        }
    }
    println("tích chéo = {}", s)

    // duyệt từng HÀNG của mảng 2 chiều (mỗi phần tử lại là mảng)
    let grid: [2][3]int = [[1, 2, 3], [4, 5, 6]]
    let mut g2: int = 0
    for row in grid {
        for x in row {
            g2 += x
        }
    }
    println("tổng 2D = {}", g2)

    // duyệt mảng 3 chiều
    let cube: [2][2][2]int = [[[1, 2], [3, 4]], [[5, 6], [7, 8]]]
    let mut g3: int = 0
    for plane in cube {
        for row in plane {
            for x in row {
                g3 += x
            }
        }
    }
    println("tổng 3D = {}", g3)
    return 0
}
