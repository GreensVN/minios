// Khung kiểm thử GENERIC: check_eq / check_ne / assert_eq / assert_ne hoạt động
// trên MỌI kiểu (vô hướng, chuỗi so nội dung, enum theo tên, struct theo trường,
// struct lồng) nhờ hàm so sánh + định dạng sinh tự động. test_summary() trả về
// số ca trượt (= 0 ở đây) — tiện làm mã thoát của 'main'. Ghi ra stderr.
enum Color { Red, Green, Blue }
struct Point { x: int, y: int }
struct Box { lo: Point, hi: Point, color: Color }

fn main() -> int {
    check_eq(2 + 2, 4, "int")
    check_ne(3, 4, "int khác")
    check_eq(1.5 + 1.5, 3.0, "float")
    check_eq('z', 'z', "char")
    check_eq(true, 1 < 2, "bool")
    check_eq("xin chao", "xin chao", "chuoi (noi dung)")
    check_eq(Green, Green, "enum")
    check_eq(Point { x: 1, y: 2 }, Point { x: 1, y: 2 }, "struct")
    check_eq(Box { lo: Point { x: 0, y: 0 }, hi: Point { x: 9, y: 9 }, color: Blue },
             Box { lo: Point { x: 0, y: 0 }, hi: Point { x: 9, y: 9 }, color: Blue },
             "struct long")
    assert_eq(6 * 7, 42)        // chế độ dừng: đạt nên im lặng
    assert_ne(Red, Blue)
    return test_summary()
}
