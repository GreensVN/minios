// Kernel Multiboot tối giản viết bằng G — chạy trực tiếp trên CPU (ring 0),
// không libc, không hệ điều hành bên dưới. Được boot.s (đầu vào Multiboot 1)
// gọi vào 'kmain(magic, mbi)'.
//
// Xây dựng:  make            (cần gcc -m32 + ld; xem Makefile)
// Chạy:      make run        (qemu-system-i386 -kernel kernel.elf)
//
// Kernel này: xoá BSS, in ra màn hình VGA và cổng nối tiếp COM1, kiểm tra
// magic Multiboot, hiển thị dung lượng RAM bootloader báo, rồi dừng CPU.

// ---- ký hiệu từ linker.ld ----
extern let _bss_start: u8
extern let _bss_end: u8

// ---- hằng phần cứng ----
const VGA_MEM: u32 = 0xB8000
const VGA_W: int = 80
const VGA_H: int = 25
const COM1: u16 = 0x3F8
const MB_MAGIC: u32 = 0x2BADB002

// Cấu trúc thông tin Multiboot 1 (chỉ các trường đầu; bố cục cố định -> @packed)
@packed
struct MultibootInfo {
    flags: u32,
    mem_lower: u32,
    mem_upper: u32,
    boot_device: u32,
    cmdline: u32,
}

// ---- trạng thái console (BSS) ----
let mut cur_row: int = 0
let mut cur_col: int = 0
let mut color: u8 = 0x0F        // trắng trên đen

fn vga_cell(row: int, col: int) -> *u16 {
    return (VGA_MEM as *u16) + (row * VGA_W + col)
}

fn vga_clear() {
    for r in 0..VGA_H {
        for c in 0..VGA_W {
            vol_write(vga_cell(r, c), ((color as u16) << 8) | 0x20)
        }
    }
    cur_row = 0
    cur_col = 0
}

fn vga_scroll() {
    for r in 1..VGA_H {
        for c in 0..VGA_W {
            vol_write(vga_cell(r - 1, c), vol_read(vga_cell(r, c)))
        }
    }
    for c in 0..VGA_W {
        vol_write(vga_cell(VGA_H - 1, c), ((color as u16) << 8) | 0x20)
    }
    cur_row = VGA_H - 1
}

fn serial_init() {
    outb(COM1 + 1, 0x00 as u8)   // tắt ngắt
    outb(COM1 + 3, 0x80 as u8)   // DLAB
    outb(COM1 + 0, 0x03 as u8)   // 38400 baud
    outb(COM1 + 1, 0x00 as u8)
    outb(COM1 + 3, 0x03 as u8)   // 8N1
    outb(COM1 + 2, 0xC7 as u8)   // FIFO
}

fn serial_putc(c: char) {
    while (inb(COM1 + 5) & 0x20) == 0 { pause() }
    outb(COM1, c as u8)
}

fn print_char(c: char) {
    serial_putc(c)
    if c == '\n' {
        serial_putc('\r')
        cur_col = 0
        cur_row += 1
    } else {
        vol_write(vga_cell(cur_row, cur_col), ((color as u16) << 8) | (c as u16))
        cur_col += 1
        if cur_col >= VGA_W { cur_col = 0; cur_row += 1 }
    }
    if cur_row >= VGA_H { vga_scroll() }
}

fn print_str(s: str) {
    let mut i = 0
    while s[i] != '\0' {
        print_char(s[i])
        i += 1
    }
}

fn put_hex(v: u32) {
    let digits = "0123456789ABCDEF"
    print_str("0x")
    let mut shift = 28
    while shift >= 0 {
        print_char(digits[((v >> shift) & 0xF) as int])
        shift -= 4
    }
}

fn put_uint(v: u32) {
    let mut buf: [12]char = ['0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0']
    let mut n = v
    let mut i = 0
    if n == 0 { print_char('0'); return }
    while n > 0 {
        buf[i] = ('0' as u32 + n % 10) as char
        n /= 10
        i += 1
    }
    while i > 0 {
        i -= 1
        print_char(buf[i])
    }
}

fn clear_bss() {
    let start = &_bss_start as u32
    let end = &_bss_end as u32
    memset(&_bss_start, 0, (end - start) as int)
}

@noreturn
fn hang() {
    cli()
    loop { halt() }
}

// Điểm vào từ boot.s. Không được trả về.
@used
fn kmain(magic: u32, mbi: *MultibootInfo) {
    clear_bss()
    serial_init()
    vga_clear()

    color = 0x0A
    print_str("G kernel: hello from ring 0!\n")
    color = 0x0F

    print_str("multiboot magic = ")
    put_hex(magic)
    if magic != MB_MAGIC {
        color = 0x0C
        print_str("  (SAI - khong duoc nap boi bootloader Multiboot?)\n")
        hang()
    }
    print_str("  OK\n")

    if (mbi.flags & 1) != 0 {
        print_str("RAM thap:  ")
        put_uint(mbi.mem_lower)
        print_str(" KiB\nRAM cao:   ")
        put_uint(mbi.mem_upper)
        print_str(" KiB\n")
    }

    print_str("sizeof(MultibootInfo) = ")
    put_uint(sizeof(MultibootInfo) as u32)
    print_str("\nrdtsc = ")
    put_hex(rdtsc() as u32)
    print_str("\n\nDung CPU (hlt). Tam biet!\n")
    hang()
}
