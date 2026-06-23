// 'let' suy luận kiểu (không chú thích) phải khai báo bằng đúng kiểu VÔ HƯỚNG đã
// suy luận, để số học kiểu hẹp wrap đúng bề rộng — nhất quán với 'let x: T = ...'
// và với 'typeof'. (Trước đây dùng '__auto_type' của C nên 'u8 + u8' giữ 300.)
fn main() -> int {
    let a: u8 = 200
    let b: u8 = 100
    let inferred = a + b            // suy luận u8 -> wrap 44
    let explicit: u8 = a + b        // 44
    println("inferred={} explicit={}", inferred as int, explicit as int)  // 44 44
    println("typeof={}", typeof(inferred))                                 // u8

    // i16 wrap
    let x: i16 = 30000
    let y: i16 = 30000
    let s = x + y                   // suy luận i16 -> wrap (60000 -> -5536)
    println("i16 sum = {}", s as int)   // -5536

    // kiểu rộng vẫn đúng (không bị thu hẹp nhầm)
    let big = 1 << 40               // i64
    println("big = {}", big)        // 1099511627776

    // float / bool suy luận
    let f = 1.5 + 2.0
    let ok = 3 < 5
    println("f={} ok={}", f, ok)    // 3.5 true
    return 0
}
