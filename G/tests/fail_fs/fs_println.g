// Hợp lệ khi hosted, nhưng '--freestanding' không có stdio -> phải báo lỗi ở
// tầng G (trước đây lọt xuống backend C: "'stdout' undeclared").
fn kmain() { println("xin chào") }
fn main() -> int { kmain() return 0 }
