// Intrinsics phát triển hệ điều hành chạy được ở không gian người dùng:
// thao tác bit (theo bề rộng kiểu), bộ nhớ thô, MMIO volatile, static_assert.
// (Lệnh đặc quyền inb/outb/hlt/cli được kiểm bằng biên dịch freestanding riêng.)

fn main() -> int {
    // ===== thao tác bit — tôn trọng bề rộng kiểu (giống Rust u8/u16/u32) =====
    println("popcount(0xFF)={}", popcount(0xFF))
    let a: u8 = 1
    println("clz_u8(1)={} ctz_u8(0x80)={}", clz(a), ctz(0x80 as u8))
    println("bswap32(0x11223344)={x}", bswap(0x11223344 as u32))
    println("bswap16(0x0102)={x}", bswap(0x0102 as u16))
    println("rotl_u8(1,1)={} rotr_u8(1,1)={}", rotl(1 as u8, 1), rotr(1 as u8, 1))

    // ===== bộ nhớ thô (libc hosted / runtime tự cài khi freestanding) =====
    let mut buf: [8]u8 = [0, 0, 0, 0, 0, 0, 0, 0]
    memset(&buf[0], 65, 4)              // 4 byte 'A'
    let mut dst: [8]u8 = [0, 0, 0, 0, 0, 0, 0, 0]
    memcpy(&dst[0], &buf[0], 8)
    println("memcpy dst[0]={c} memcmp={}", dst[0] as char, memcmp(&dst[0], &buf[0], 8))

    // ===== MMIO: đọc/ghi qua 'volatile' (ở đây trên bộ nhớ thường) =====
    let mut cell: u32 = 0
    vol_write(&cell, 0xCAFE)
    println("vol_read={x}", vol_read(&cell))

    // ===== khẳng định lúc biên dịch =====
    static_assert(sizeof(u64) == 8, "u64 phải 8 byte")
    static_assert(sizeof(u8) == 1, "u8 phải 1 byte")
    println("static_assert OK")
    return 0
}
