// Method dựng sẵn trên 'str' (đường cú pháp cho hàm runtime, không cần import).
fn main() -> int {
    let s = "  Hello World  "
    let t = s.trim()
    println("[{}] {}", t, t.len())
    println("{} {}", t.upper(), t.lower())
    println("{} {} {}", t.contains("World"), t.starts_with("Hel"), t.ends_with("ld"))
    println("{} {} {}", t.index_of("World"), t.count('l'), t.at(0))
    println("{} {}", t.is_empty(), "".is_empty())
    let u = t.sub(0, 5)
    println("{} {}", u, u.rev())
    println("{} {}", "42".to_int() + 1, "ab".repeat(3))
    println("{} {}", "a".concat("b"), "x".eq("x"))
    // chuỗi hoá + dùng trong điều kiện / match
    println("{}", match t.len() { 0 => "empty" 1..=4 => "short" _ => "long" })
    g_free(t) g_free(u)
    return 0
}
