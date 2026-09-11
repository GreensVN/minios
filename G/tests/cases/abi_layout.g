// Bố cục/ABI: G tự tính sizeof/alignof theo target (compiler/layout.py) thay vì
// nhờ C, nên static_assert về ABI báo lỗi ở TẦNG G. tests/test_layout.py đối
// chiếu từng con số với trình biên dịch C thật.
@packed struct Hdr { magic: u16, len: u32, flags: u8 }
struct Pt { x: i32, y: i32 }
struct Pad { a: u8, b: u32 }
@align(16) struct Al { a: u8, b: u32 }
struct Nest { a: u8, p: Pt, b: u8 }
enum Color { Red, Green }
struct WithEnum { a: u8, c: Color }

fn main() -> int {
    // Khoá bố cục: đổi thứ tự trường hay bỏ @packed là lỗi biên dịch ngay.
    static_assert(sizeof(Hdr) == 7, "Hdr đóng gói phải đúng 7 byte")
    static_assert(alignof(Hdr) == 1, "packed -> căn 1")
    static_assert(sizeof(Pt) == 8, "hai i32")
    static_assert(sizeof(Pad) == 8, "u8 + đệm + u32")
    static_assert(alignof(Pad) == 4, "căn theo trường rộng nhất")
    static_assert(sizeof(Al) == 16, "@align(16)")
    static_assert(sizeof(Nest) == 16, "u8 + Pt(căn 4) + u8 -> 16")
    static_assert(sizeof(WithEnum) == 8, "enum = int")
    // Kiểu bề rộng cố định: giống nhau ở mọi target.
    static_assert(sizeof(u8) == 1 && sizeof(u16) == 2, "cố định")
    static_assert(sizeof(i64) == 8 && sizeof(f64) == 8, "cố định 64")
    println("{} {} {} {}", sizeof(Hdr), sizeof(Pt), sizeof(Al), sizeof(Nest))
    println("{} {} {}", alignof(Hdr), alignof(Pad), sizeof(WithEnum))
    return 0
}
