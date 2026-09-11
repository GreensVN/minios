// Con trỏ 'mut' khởi tạo null rồi gán lại KHÔNG bị báo lỗi (chỉ 'let' bất biến).
struct S { v: int }
fn main() -> int {
    let mut p: *S = null
    if p == null { p = g_alloc(S, 1) }
    p.v = 7
    println("{} {}", p.v, p != null)
    g_free(p)
    let q: *S = null
    println("{}", q == null)      // so sánh với null vẫn hợp lệ
    return 0
}
