// Hồi quy: hằng dịch trái cho kết quả > 32-bit phải được nâng bề rộng (không
// còn tính trong 'int' rồi cắt cụt về 0), và literal lớn suy luận đúng 64-bit.
fn main() -> int {
    println("{}", 1 << 40)          // 1099511627776 (trước đây = 0)
    println("{}", 3 << 35)          // 103079215104
    println("{}", 1 << 30)          // 1073741824 (vẫn vừa i32)
    println("{}", 5000000000)       // literal > i32 -> i64
    println("{}", 0xFFFFFFFFFF)     // hex 40-bit
    let u: u64 = 1
    println("{}", u << 63)          // 9223372036854775808
    return 0
}
