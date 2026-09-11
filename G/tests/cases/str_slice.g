// 's[lo..hi]' cắt lát chuỗi (nửa mở), 's[lo..=hi]' bao gồm cận trên; cận có thể
// khuyết. Chỉ số được KẸP vào [0, len] nên không bao giờ đọc ngoài vùng nhớ.
fn src() -> str { return "hello world" }
fn main() -> int {
    let s = "hello world"
    println("[{}]", s[0..5])
    println("[{}]", s[6..])
    println("[{}]", s[..5])
    println("[{}]", s[..])
    println("[{}]", s[0..=4])
    println("[{}]", s[3..3])        // rỗng
    println("[{}]", s[99..200])     // kẹp -> rỗng
    println("[{}]", s[4..2])        // hi < lo -> rỗng
    let n = 6
    println("[{}]", s[n..n + 5])
    println("{}", s[0..5].upper())  // nối được với method str
    println("[{}]", src()[6..])
    return 0
}
