// Test hồi quy: specifier định dạng 64-bit {lx}/{lX}/{lo} (hex/HEX/bát phân dài)
// và {lg}/{le} (số thực) phải in ĐÚNG cơ số, không lặng lẽ rơi về thập phân.

fn main() -> int {
    let big: i64 = 4294967295        // 0xFFFFFFFF
    println("{lx} {lX} {lo}", big, big, big)

    let huge: i64 = 4294967296       // 0x100000000 (vượt 32-bit)
    println("{lx}", huge)

    let d: f64 = 3.14159
    println("{lg} {le}", d, d)

    // specifier ngắn vẫn hoạt động như cũ
    println("{x} {X} {o}", 255, 255, 8)
    return 0
}
