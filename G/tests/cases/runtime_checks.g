// Kiểm tra lúc chạy: chỉ số động trên mảng tĩnh và chia cho 0 -> panic rõ ràng
// (không phải rác/SIGFPE). Chương trình này chỉ đi qua các đường KHÔNG panic.
fn main() -> int {
    let mut a: [4]int = [10, 20, 30, 40]
    let mut s = 0
    for i in 0..4 { s += a[i] }          // chỉ số động hợp lệ
    let k = 3
    a[k] /= 4                            // '/=' với mẫu không hằng
    println("{} {}", s, a[3])
    let d = 7
    println("{} {}", 100 / d, 100 % d)
    let g: [2][3]int = [[1, 2, 3], [4, 5, 6]]
    let mut t = 0
    for r in 0..2 { for c in 0..3 { t += g[r][c] } }
    println("{}", t)
    // ranh giới: chỉ số cuối cùng hợp lệ, không panic
    let last = 3
    println("{}", a[last])
    return 0
}
