// Tiện ích căn chỉnh & thao tác bit của thư viện chuẩn (lib/std.g) — nền tảng
// cho cấp phát/phân trang. Bắt cả bẫy ưu tiên toán tử ('&' lỏng hơn '==').
import std

fn main() -> int {
    println("{} {} {}", align_up(13, 8), align_down(13, 8), align_up(4096, 4096))
    println("{} {}", is_aligned(4096, 4096), is_aligned(4097, 4096))
    println("{} {} {}", bit_set(0, 3), bit_clear(15, 1), bit_toggle(0, 5))
    println("{} {}", bit_test(8, 3), bit_test(8, 2))
    println("{} {} {}", int_log2(8), int_log2(9), int_log2(1))
    println("{}", bits_extract(0xFF00, 8, 8))
    return 0
}
