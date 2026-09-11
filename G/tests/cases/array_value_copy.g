// Mảng có ngữ nghĩa GIÁ TRỊ: 'let b = a' sao chép (trước đây __auto_type cho ra
// con trỏ vào chính a, nên b[0]=9 sửa luôn a). Tham số mảng 'mut' cũng là bản
// sao cục bộ — C truyền mảng như con trỏ nên nếu không sao chép sẽ ghi xuyên
// về nơi gọi.
fn peek(a: [3]int) -> int { return a[0] }
fn bump(mut a: [3]int) -> int {
    a[0] = 99
    return a[0]
}
struct Box { v: [2]int }
fn main() -> int {
    let a: [3]int = [1, 2, 3]
    let mut b = a
    b[0] = 9
    println("{} {}", a[0], b[0])

    let m: [2][2]int = [[1, 2], [3, 4]]
    let mut n = m
    n[0][0] = 7
    println("{} {}", m[0][0], n[0][0])

    let x: [3]int = [7, 8, 9]
    println("{} {} {}", bump(x), x[0], peek(x))

    // struct chứa mảng: sao chép sâu theo giá trị
    let s = Box{v: [1, 2]}
    let mut t = s
    t.v[0] = 5
    println("{} {}", s.v[0], t.v[0])
    return 0
}
