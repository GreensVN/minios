// Kiểm tra builtin format(): dựng chuỗi trên heap, hỗ trợ mọi specifier + flags,
// và đánh giá đối số đúng MỘT lần.
import std

let mut goi: int = 0
fn dem() -> int {
    goi += 1
    return goi * 10
}

fn main() -> int {
    let s = format("{s} = {} + {} -> {}", "tổng", 2, 3, 2 + 3)
    println("{s}", s)
    println("độ dài = {}", str_len(s))
    g_free(s)

    // width / precision / căn lề
    let a = format("[{d:5}]", 42)
    let b = format("[{d:<5}]", 42)
    let c = format("[{d:05}]", 42)
    let d = format("[{f:.3}]", 3.14159)
    println("{s} {s} {s} {s}", a, b, c, d)
    g_free(a); g_free(b); g_free(c); g_free(d)

    // hex / bool / char
    let e = format("{x} {X} {b} {c}", 255, 255, true, 65)
    println("{s}", e)
    g_free(e)

    // đối số có tác dụng phụ chỉ chạy một lần
    let f = format("dem()={}", dem())
    println("{s}, số lần gọi = {}", f, goi)
    g_free(f)

    // format + nối qua str_concat (giải phóng gọn gàng)
    let p1 = format("a={}", 1)
    let p2 = format(",b={}", 2)
    let g = str_concat(p1, p2)
    println("{s}", g)
    g_free(p1); g_free(p2); g_free(g)
    return 0
}
