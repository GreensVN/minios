// Mảng literal lặp '[v; N]' (kiểu Rust) — N là hằng số biên dịch.
struct S { flags: [4]bool }
fn main() -> int {
    let mut a: [8]bool = [false; 8]
    a[3] = true
    println("{} {} {}", a[0], a[3], len(a))
    let z = [0; 5]
    println("{} {}", typeof(z), len(z))
    let m: [2][3]int = [[7; 3]; 2]
    println("{} {}", m[1][2], typeof(m))
    println("{} {}", ["x"; 3][2], len(["x"; 3]))
    // cỡ là biểu thức hằng
    const N: int = 3
    let c = [9; N * 2]
    println("{} {}", len(c), c[5])
    println("{}", S{flags: [true; 4]})
    return 0
}
