// ============================================================================
//  Trình diễn các TÍNH NĂNG PHÁT TRIỂN HỆ ĐIỀU HÀNH của G chạy được ở
//  không gian người dùng (không cần ring 0). Kernel thật xem examples/kernel/.
//  Lệnh đặc quyền (inb/outb/hlt/cli) chỉ biên dịch freestanding — xem
//  tests/freestanding/.
// ============================================================================

// --- Mô tả bố cục thanh ghi phần cứng bằng struct ĐÓNG GÓI (không đệm) ---
@packed
struct UartRegs {
    data: u8        // offset 0  — thanh ghi dữ liệu
    status: u8      // offset 1  — cờ trạng thái
    control: u16    // offset 2  — điều khiển
}

// --- Cờ quyền (bitmask) thao tác bằng intrinsic bit ---
const FLAG_READ:  u32 = 1
const FLAG_WRITE: u32 = 2
const FLAG_EXEC:  u32 = 4

fn main() -> int {
    // Bố cục thanh ghi cố định lúc biên dịch (bắt sai sót ngay).
    static_assert(sizeof(UartRegs) == 4, "UartRegs phải đúng 4 byte")

    println("=== G — tính năng phát triển hệ điều hành ===")
    println("sizeof(UartRegs) đóng gói = {} byte", sizeof(UartRegs))

    // --- MMIO mô phỏng: ghi/đọc qua 'volatile' trên một vùng RAM ---
    let mut mmio: *u32 = g_alloc(u32, 4)
    vol_write(mmio + 0, 0xDEADBEEF)
    vol_write(mmio + 1, 0x0000CAFE)
    println("MMIO[0]={x} MMIO[1]={x}", vol_read(mmio + 0), vol_read(mmio + 1))
    g_free(mmio)

    // --- Thao tác bit theo bề rộng kiểu ---
    let mut flags: u32 = 0
    flags = flags | FLAG_READ | FLAG_WRITE | FLAG_EXEC
    println("flags=0x{x} popcount={} ctz={}", flags, popcount(flags), ctz(flags))
    println("đổi byte 0x12345678 = 0x{x}", bswap(0x12345678 as u32))
    println("xoay trái u8 0x81 <<< 1 = {}", rotl(0x81 as u8, 1))
    println("đếm 0 dẫn đầu của u32 0x0000FFFF = {}", clz(0x0000FFFF as u32))

    // --- Bộ nhớ thô ---
    let mut a: [4]u32 = [10, 20, 30, 40]
    let mut b: [4]u32 = [0, 0, 0, 0]
    memcpy(&b[0], &a[0], sizeof(u32) * 4)
    println("memcpy b=[{}, {}, {}, {}] giống a? {}",
            b[0], b[1], b[2], b[3], memcmp(&a[0], &b[0], sizeof(u32) * 4) == 0)

    // --- Đo chu kỳ CPU bằng rdtsc (đọc được ở user-space) ---
    let t0 = rdtsc()
    let mut sink: u64 = 0
    for i in 0..1000 { sink += i as u64 }
    let elapsed = rdtsc() - t0
    println("rdtsc đo được vòng lặp (sink={}, tốn >0 chu kỳ? {})", sink, elapsed > 0)
    return 0
}
