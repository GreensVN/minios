// Kiểu kết quả của toán tử một ngôi & char ⊕ char (thăng cấp như C)
fn main() -> int {
    let a: u8 = 5
    println("{} {}", -a, typeof(-a))          // -5 int (không phải 4294967291)
    let w: u32 = 1
    println("{} {}", -w, typeof(-w))          // -1 i64
    let c = 'z' - 'a'
    println("{} {}", c, typeof(c))            // 25 int (không phải ký tự \x19)
    let d = 'a' + 1
    println("{} {}", d, typeof(d))            // 98 int
    println("{}", ('a' + 1) as char)          // b
    let n: i16 = 3
    println("{} {}", ~n, typeof(~n))          // -4 int
    println("{}", !(a > 3))
    return 0
}
