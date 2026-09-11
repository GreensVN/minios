//! accept x86_64-none
//! accept aarch64-none
//! accept riscv64-none
//! reject wasm32 không có bộ đếm chu kỳ
// Bộ đếm chu kỳ CÓ tương đương thật ngoài x86 (cntvct_el0 / rdcycle) nên phải
// được chấp nhận — đây là lý do dùng "năng lực" thay vì chặn theo tên kiến trúc.
fn now() -> u64 { return rdtsc() }
fn kmain() { let _ = now() }
