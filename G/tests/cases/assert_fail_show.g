// Khoá ĐỊNH DẠNG hiển thị 'trái'/'phải' khi check_* TRƯỢT (các ca dưới đây CỐ Ý
// sai để kiểm thử phần hiển thị — test PASS khi output khớp kết quả mong đợi).
// Dùng check_* (không dừng) để mọi ca đều chạy. KHÔNG sửa số dòng phía dưới.
enum Color { Red, Green, Blue }
struct Point { x: int, y: int }
fn main() -> int {
    check_eq(2 + 2, 5, "so sai")
    check_eq(Point { x: 1, y: 2 }, Point { x: 1, y: 9 }, "struct sai")
    check_ne(Green, Green, "enum ne sai")
    check_eq("abc", "abd", "chuoi sai")
    return test_summary()
}
