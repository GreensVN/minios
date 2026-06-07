// Kiểm tra định dạng có width/precision/căn lề (kiểu Zig/Rust).

fn main() -> int {
    // width tối thiểu
    println("[{d:5}]", 42)
    // căn trái
    println("[{d:<5}]", 42)
    // đệm số 0
    println("[{d:05}]", 42)
    // precision cho float
    println("[{f:.2}]", 3.14159)
    // width + precision
    println("[{f:8.3}]", 3.14159)
    // tự suy luận + width
    println("[{:6}]", 7)
    // chuỗi căn phải / căn trái
    println("[{s:>10}]", "hi")
    println("[{s:<10}]", "hi")
    // nhiều placeholder trong một dòng
    println("{d:3}|{d:<3}|{f:.1}", 1, 2, 3.456)
    return 0
}
