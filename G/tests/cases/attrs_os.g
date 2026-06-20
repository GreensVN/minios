// Thuộc tính @ cho bố cục/ABI — nền tảng để mô tả thanh ghi phần cứng và
// điểm vào kernel. (@naked/@section/@noreturn được kiểm qua biên dịch freestanding.)

@packed
struct Packed { a: u8, b: u32, c: u8 }     // không đệm -> 6 byte

struct Plain { a: u8, b: u32, c: u8 }       // có đệm -> 12 byte

@align(64)
let cache_line: [4]u64 = [1, 2, 3, 4]       // căn theo 64 byte (dòng cache)

@inline
fn dbl(x: int) -> int { return x * 2 }

fn main() -> int {
    println("sizeof Packed={} Plain={}", sizeof(Packed), sizeof(Plain))
    println("alignof Packed={}", alignof(Packed))
    println("dbl(21)={}", dbl(21))
    println("cache_line[2]={}", cache_line[2])
    static_assert(sizeof(Packed) == 6, "Packed phải 6 byte")
    return 0
}
