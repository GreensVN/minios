// Gọi con trỏ hàm sai số tham số -> phải báo lỗi.
fn add(a: int, b: int) -> int { return a + b }

fn main() -> int {
    let f: fn(int, int) -> int = add
    return f(1)
}
