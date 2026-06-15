// Gán cùng một trường nhiều lần trong struct literal -> lỗi.
struct P { x: int, y: int }
fn main() -> int {
    let p = P { x: 1, x: 2, y: 3 }
    return p.x
}
