// Kiểm biên qua RANH GIỚI HÀM — điều '[]T' (con trỏ trần) không làm được, vì
// độ dài bị bỏ lại ở nơi gọi. Ở đây chỉ kiểm các truy cập HỢP LỆ; trường hợp
// vượt biên (panic, mã thoát 101) được kiểm riêng trong tests/run_panic.sh vì
// thông báo panic có chứa đường dẫn file.
fn get(xs: slice<int>, i: int) -> int { return xs[i] }
fn last(xs: slice<int>) -> int { return xs[len(xs) - 1] }
fn main() -> int {
    let a: [4]int = [10, 20, 30, 40]
    println("{} {}", get(a, 3), last(a))
    println("{} {}", get(a[0..2], 1), last(a[1..3]))
    println("{}", last(a[..]))
    return 0
}
