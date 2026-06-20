// Kiểm tra: MỌI intrinsic phát triển hệ điều hành BIÊN DỊCH được ở chế độ
// freestanding (không libc). Gồm cả lệnh ĐẶC QUYỀN (in/out/hlt/cli/sti) vốn
// không chạy được ở không gian người dùng — nên file này chỉ biên dịch (-c),
// không chạy. Biên dịch:  gc intrinsics_fs.g --freestanding -c

// Ký hiệu do linker script cung cấp
extern let _bss_start: u8
extern let _bss_end: u8

// Bố cục thanh ghi phần cứng: đóng gói chặt (không đệm)
@packed
struct GdtPtr { limit: u16, base: u64 }

// Cổng nối tiếp COM1 — kiểm thử cổng I/O x86
const COM1: u16 = 0x3F8

fn serial_init() {
    outb(COM1 + 1, 0x00 as u8)      // tắt ngắt
    outb(COM1 + 3, 0x80 as u8)      // bật DLAB
    outb(COM1 + 0, 0x03 as u8)      // tốc độ baud (thấp)
    outb(COM1 + 1, 0x00 as u8)      // (cao)
    outb(COM1 + 3, 0x03 as u8)      // 8 bit, không chẵn lẻ, 1 stop
}

fn serial_putc(c: char) {
    while (inb(COM1 + 5) & 0x20) == 0 { pause() }   // chờ THR rỗng
    outb(COM1, c as u8)
}

// Đọc control register CR0 qua asm mở rộng
fn read_cr0() -> u64 {
    let mut v: u64 = 0
    asm {
        "mov %%cr0, %0"
        : "=r"(v)
    }
    return v
}

// Nạp GDT qua lgdt (asm mở rộng với toán hạng input)
fn load_gdt(p: *GdtPtr) {
    asm {
        "lgdt (%0)"
        :
        : "r"(p)
        : "memory"
    }
}

fn clear_bss() {
    let start = &_bss_start as u64
    let end = &_bss_end as u64
    memset(&_bss_start, 0, (end - start) as int)
}

@noreturn
@section(".text.boot")
fn hang() {
    cli()
    loop { halt() }
}

@noreturn
fn kernel_main() {
    clear_bss()
    serial_init()
    serial_putc('G')
    let cr0 = read_cr0()
    if (cr0 & 1) != 0 { io_wait() }     // chế độ bảo vệ đã bật?
    sti()
    hang()
}
