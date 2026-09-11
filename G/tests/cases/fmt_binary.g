// '{b}'/'{:b}': bool -> true/false; số nguyên -> NHỊ PHÂN (kiểu Rust)
fn main() -> int {
    println("{:b} {b} {:b}", 5, true, 0)
    println("{:08b}|{:b}|{:b}", 5, 255 as u8, -1 as i8)
    println("{:b}", 1024)
    let s = format("{:b}-{}", 10, false)
    println("{}", s)
    g_free(s)
    return 0
}
