//! accept x86_64-none
//! reject aarch64-none MSR (rdmsr/wrmsr) là đặc thù x86
fn kmain() { let v = rdmsr(0xC0000080) wrmsr(0xC0000080, v) }
