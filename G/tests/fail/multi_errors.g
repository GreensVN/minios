// Checker phải báo NHIỀU lỗi trong một lượt (phục hồi theo câu lệnh) — snapshot
// giữ dòng đầu; kiểm số lỗi ở dòng cuối 'gc: N lỗi'.
fn f(a: int) -> int { return a }
fn main() -> int {
    let g: int = 1.5
    let s = "abc"
    let n = s + 1
    println("{}", g + f("x"))
    undefined_fn()
    return 0
}
