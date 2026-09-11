//! accept x86_64-none
//! reject aarch64-none đặc thù x86
//! reject riscv64-none đặc thù x86
fn page_table() -> u64 { return read_cr3() }
fn kmain() { write_cr3(page_table()) }
