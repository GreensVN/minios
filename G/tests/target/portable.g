//! accept x86_64-none
//! accept aarch64-none
//! accept riscv64-none
//! accept wasm32
// Intrinsic ĐỘC LẬP kiến trúc: thao tác bit + MMIO. Phải chạy trên MỌI target —
// đây là cách viết driver di động (MMIO thay cho cổng I/O).
fn mmio_write(addr: *u32, v: u32) { vol_write(addr, v) }
fn popcnt(x: u64) -> int { return popcount(x) }
fn swap_bytes(x: u32) -> u32 { return bswap(x) }
fn kmain() { let _ = popcnt(255) }
