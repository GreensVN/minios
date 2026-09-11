// 'for mut x in arr' là THAM CHIẾU tới phần tử (như iter_mut của Rust): sửa x
// ghi thẳng vào mảng. Trước đây x là bản sao nên phép sửa bị mất âm thầm.
struct P { x: int, y: int }
fn main() -> int {
    let mut a: [4]int = [1, 2, 3, 4]
    for mut x in a { x *= 10 }
    println("{} {} {}", a[0], a[2], a[3])

    let mut ps: [2]P = [P{x:1, y:1}, P{x:2, y:2}]
    for mut p in ps { p.x *= 100 }
    println("{} {}", ps[0].x, ps[1].x)

    // hàng của mảng nhiều chiều
    let mut m: [2][2]int = [[1, 2], [3, 4]]
    for mut row in m { row[0] = 9 }
    println("{} {}", m[0][0], m[1][0])

    // không 'mut' -> bản sao, mảng giữ nguyên
    for y in a { }
    println("{}", a[0])
    return 0
}
