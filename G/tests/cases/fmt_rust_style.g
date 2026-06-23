// Định dạng kiểu Rust: chữ kiểu đặt SAU dấu ':' ('{:x}', '{:08x}', '{:.2f}'),
// cộng cờ dấu '+'/' ' và cờ dạng-thay-thế '#'. Bổ sung cho lối '{x}' / '{x:08}'
// (chữ kiểu TRƯỚC ':') vốn đã có. Tất cả ra stdout nên thứ tự tất định.
fn main() -> int {
    // hex / oct kiểu Rust
    println("[{:x}]", 255)          // ff
    println("[{:X}]", 255)          // FF
    println("[{:08x}]", 255)        // 000000ff
    println("[{:#x}]", 255)         // 0xff
    println("[{:o}]", 64)           // 100
    // số thực với precision
    println("[{:.2f}]", 3.14159)    // 3.14
    println("[{:8.3f}]", 3.14159)   // "   3.142"
    // cờ dấu
    println("[{:+}]", 42)           // +42
    println("[{:+}]", -42)          // -42
    println("[{: }]", 42)           //  42 (khoảng trắng dẫn đầu)
    println("[{:+08}]", 42)         // +0000042
    // căn lề
    println("[{:>6}]", 7)           // "     7"
    println("[{:<6}]", 7)           // "7     "
    // tương thích ngược: chữ kiểu TRƯỚC dấu ':'
    println("[{x}]", 255)           // ff
    println("[{x:08}]", 255)        // 000000ff
    println("[{:5}]", "hi")         // "   hi"
    return 0
}
