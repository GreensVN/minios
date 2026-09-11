//! accept x86_64-none
//! reject aarch64-none không có cổng I/O riêng biệt
//! reject riscv64-none không có cổng I/O riêng biệt
//! reject wasm32 không có cổng I/O riêng biệt
// Cổng I/O chỉ tồn tại trên x86. Trước đây ca này biên dịch SẠCH trên mọi
// kiến trúc rồi hạ thành no-op — driver UART chết lặng.
fn uart_putc(c: u8) { outb(0x3F8, c) }
fn uart_ready() -> bool { return (inb(0x3FD) & 0x20) != 0 }
fn kmain() { if uart_ready() { uart_putc(65) } }
