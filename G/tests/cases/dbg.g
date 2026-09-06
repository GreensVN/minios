// dbg(x): in '[dbg dòng N] <giá trị>' ra stderr rồi TRẢ LẠI x (kiểu Rust).
// Chỉ ghi stderr (không stdout) để thứ tự dòng tất định khi gộp luồng.
struct V { a: int, b: int }
fn main() -> int {
    let x = dbg(40 + 2)        // 42
    let _y = dbg(x * 2)         // 84
    let _s = dbg("ok")          // ok
    let _f = dbg(3.5)           // 3.5
    let _v = dbg(V { a: 1, b: 2 })   // V { a: 1, b: 2 }
    return 0
}
