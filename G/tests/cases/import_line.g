// Lỗi 'không tìm thấy module' phải trỏ đúng dòng của import sai, không phải
// dòng 1. Ca này chỉ kiểm chương trình nhiều import hợp lệ vẫn chạy.
import std
import std
fn main() -> int {
    println("{}", gcd(12, 18))
    return 0
}
