// assert_eq/check_eq: hai vế phải cùng kiểu (so sánh int với chuỗi vô nghĩa).
fn main() -> int {
    check_eq(1, "x", "sai kiểu")
    return 0
}
