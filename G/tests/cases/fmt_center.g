// Cờ căn GIỮA '{:^N}' (Rust) — printf không có, runtime tự đệm hai bên.
struct P { v: [3]int, name: str }
fn main() -> int {
    println("[{:^7}][{:^7}][{:^7.2f}]", "ab", 42, 3.14159)
    println("[{:^4}][{:^1}]", "abcd", "toolong")
    let s = format("{:^6}|", 7)
    println("{}", s)
    g_free(s)
    // trường mảng của struct được BUNG thay vì '[…]'
    println("{}", P{v: [1, 2, 3], name: "p"})
    return 0
}
