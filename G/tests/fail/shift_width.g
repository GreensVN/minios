// Dịch một biến kiểu hẹp quá bề rộng của nó là UB trong C.
fn main() -> int {
    let x: i32 = 5
    let y = x << 40
    return y
}
