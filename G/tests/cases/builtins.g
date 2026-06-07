// Kiểm tra builtins: min/max/abs/clamp (đánh giá đối số đúng MỘT lần),
// len, sizeof(type) và sizeof(biểu_thức), và số học cơ số.
let mut so_lan_goi: int = 0

fn dem() -> int {
    so_lan_goi += 1
    return 7
}

fn main() -> int {
    println("min(3,9)={}, max(3,9)={}", min(3, 9), max(3, 9))
    println("abs(-42)={}, clamp(15,0,10)={}, clamp(-5,0,10)={}",
            abs(-42), clamp(15, 0, 10), clamp(-5, 0, 10))

    // mỗi lời gọi có tác dụng phụ chỉ được đánh giá đúng 1 lần
    let m: int = min(dem(), 100)
    let x: int = max(dem(), 1)
    let c: int = clamp(dem(), 0, 5)
    println("m={}, x={}, c={}, số lần gọi dem()={}", m, x, c, so_lan_goi)

    // len cho mảng tĩnh và chuỗi
    let arr: [4]int = [9, 8, 7, 6]
    println("len(arr)={}, len(\"chào\")={}", len(arr), len("chào"))

    // sizeof
    let big: i64 = 1
    println("sizeof(int)={}, sizeof(i64)={}, sizeof(big*2)={}, sizeof(arr)={}",
            sizeof(int), sizeof(i64), sizeof(big * 2), sizeof(arr))

    // số học cơ số + dấu gạch dưới
    let a: int = 0xFF
    let b: int = 0b1010_1010
    let d: int = 1_000_000
    println("0xFF={}, 0b10101010={}, 1_000_000={}", a, b, d)
    return 0
}
