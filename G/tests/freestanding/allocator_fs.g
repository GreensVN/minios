// Arena chạy ở chế độ KHÔNG LIBC: bộ đệm do người dùng cấp, không malloc.
// Đây là điểm chính của allocator thay thế được — cùng mã cấp phát dùng được
// cả ở kernel.
struct Desc { base: u32, limit: u32 }

fn kmain() {
    let mut backing: [2048]u8 = [0; 2048]
    let mut a = arena_allocator(backing)
    let regs = alloc_in(a, u32, 8)
    regs[0] = 0xDEAD
    regs[7] = 0xBEEF
    let ds = alloc_in(a, Desc, 4)
    ds[0].base = 0x1000
    ds[3].limit = 0xFFFF
    outb(0x80, regs[0] as u8)
    outb(0x81, ds[0].base as u8)
    free_in(a, regs)
}
