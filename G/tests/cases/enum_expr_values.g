// Test hồi quy: GIÁ TRỊ biến thể enum là một BIỂU THỨC HẰNG (không chỉ literal):
// '1 << n', 'A + k', 'sizeof(T)'... phải được checker gấp ĐÚNG để khớp giá trị C.
// Nếu sai (bug cũ chỉ nhận IntLit/-IntLit):
//   • cỡ mảng '[Exec]u8' bị lệch (Exec ghi nhầm = bộ đếm tự tăng, không phải 4),
//   • hai biến thể TRÙNG giá trị không được khử -> nhãn 'case' trùng -> lỗi C.

enum Flags { Read = 1 << 0, Write = 1 << 1, Exec = 1 << 2, RW = Read + Write }
enum Sz { ByteN = sizeof(u8), WordN = sizeof(u16), QuadN = sizeof(u64) }
enum Alias { Two = 1 + 1, AlsoTwo = 2 }     // hai biến thể cùng giá trị 2

fn main() -> int {
    println("{} {} {} {}", Read as int, Write as int, Exec as int, RW as int)
    println("{} {} {}", ByteN as int, WordN as int, QuadN as int)
    let buf: [Exec]u8                        // Exec = 4 -> [4]u8
    println("buflen={}", len(buf))
    println("{}", Two)                       // giá trị 2 -> in tên đầu "Two"
    return 0
}
