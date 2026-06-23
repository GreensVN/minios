// So sánh THỨ TỰ (assert_lt/le/gt/ge) không áp dụng cho struct — struct không có
// thứ tự tự nhiên theo trường. (assert_eq/ne thì được, so theo từng trường.)
struct P { x: int, y: int }
fn main() -> int {
    assert_lt(P { x: 1, y: 2 }, P { x: 3, y: 4 })
    return 0
}
