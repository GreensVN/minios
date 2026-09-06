// Slice hoạt động ở chế độ KHÔNG LIBC: struct { ptr, len } thuần + kiểm biên
// dùng g_bounds_fail (freestanding = dừng CPU). Không cấp phát, không stdio.
fn sum(xs: slice<u32>) -> u32 {
    let mut s: u32 = 0
    for i in 0..len(xs) { s += xs[i] }
    return s
}
fn clear(xs: mut slice<u32>) {
    for i in 0..len(xs) { xs[i] = 0 }
}
fn kmain() {
    let mut regs: [4]u32 = [1, 2, 3, 4]
    outb(0x80, sum(regs) as u8)
    outb(0x81, sum(regs[1..3]) as u8)
    clear(regs[0..2])
    outb(0x82, sum(regs) as u8)
}
