// So sánh THỨ TỰ: assert_lt/le/gt/ge (dừng khi sai) và check_lt/le/gt/ge (ghi
// nhận rồi tiếp tục). Hoạt động cho số, char, enum và CHUỖI (so theo strcmp).
// Toàn bộ đạt -> test_summary() trả 0. Ghi ra stderr (tránh lẫn thứ tự với stdout).
enum Level { Low, Mid, High }
fn main() -> int {
    // assert_* (đạt nên im lặng)
    assert_lt(1, 2)
    assert_le(2, 2)
    assert_gt(5, 3)
    assert_ge(3, 3)
    assert_lt('a', 'b')
    assert_lt("abc", "abd")
    assert_lt(Low, High)         // enum theo giá trị
    // check_* (ghi nhận; tất cả đạt)
    check_lt(1, 2, "1<2")
    check_le(2, 2, "2<=2")
    check_gt(9, 0, "9>0")
    check_ge(7, 7, "7>=7")
    check_lt("apple", "banana", "chuoi")
    return test_summary()
}
