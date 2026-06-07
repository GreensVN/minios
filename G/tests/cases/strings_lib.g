// Kiểm tra thư viện chuỗi (std.g + runtime): nối, cắt, tìm, chuyển đổi.
import std

fn main() -> int {
    let greet = str_concat("Xin chào, ", "G!")
    println("{s}", greet)
    println("độ dài = {}", str_len(greet))

    let word = substr("programming", 0, 7)
    println("substr = {s}", word)

    println("contains 'gram'? {}", str_contains("programming", "gram"))
    println("starts 'pro'? {}", starts_with("programming", "pro"))
    println("ends 'ing'? {}", ends_with("programming", "ing"))
    println("streq? {}", streq("abc", "abc"))

    let n = parse_int("12345")
    println("parse_int = {ld}", n)

    let back = int_to_str(98765)
    println("int_to_str = {s}", back)

    g_free(greet)
    g_free(word)
    g_free(back)
    return 0
}
