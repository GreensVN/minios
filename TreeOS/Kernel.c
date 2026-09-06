/* =============================================================================
 *  Kernel.c - MiniOS v4.1 kernel
 *
 *  Build (see Makefile):
 *    gcc -m32 -c Kernel.c -o kernel.o -ffreestanding -fno-pie -O2 -Wall -Wextra
 *        -nostdlib -fno-builtin -fno-stack-protector -mno-sse -mno-mmx
 *
 *  Entered from entry.asm as  kernel_main(magic, info)  in 32-bit protected
 *  mode with a flat GDT, interrupts disabled and .bss already cleared.
 *
 *  Subsystems (in order of initialisation):
 *    serial (COM1 mirror of the console)   VGA text console + status bar
 *    boot info / memory map                GDT + IDT + PIC + PIT + keyboard
 *    heap (first-fit, coalescing)          physical frame allocator (bitmap)
 *    kernel threads (preemptive RR)        INT 0x80 system calls
 *    interactive shell
 * ===========================================================================*/

#include "kernel.h"
#include "driver_manager.h"

#define KERNEL_VERSION "4.1.0"

/* ------------------------------------------------------------------ VGA -- */
#define VGA_MEMORY   ((volatile u16 *)0xB8000)
#define VGA_WIDTH    80
#define VGA_HEIGHT   25
#define CONSOLE_ROWS (VGA_HEIGHT - 1)   /* last row is the status bar */
#define VGA_CTRL     0x3D4
#define VGA_DATA     0x3D5

enum vga_color {
    VGA_BLACK = 0, VGA_BLUE, VGA_GREEN, VGA_CYAN, VGA_RED, VGA_MAGENTA,
    VGA_BROWN, VGA_LIGHT_GREY, VGA_DARK_GREY, VGA_LIGHT_BLUE, VGA_LIGHT_GREEN,
    VGA_LIGHT_CYAN, VGA_LIGHT_RED, VGA_LIGHT_MAGENTA, VGA_YELLOW, VGA_WHITE
};

/* ----------------------------------------------------------- constants -- */
#define PIC1_CMD   0x20
#define PIC1_DATA  0x21
#define PIC2_CMD   0xA0
#define PIC2_DATA  0xA1
#define PIC_EOI    0x20
#define PIT_HZ     100
#define COM1       0x3F8

#define PAGE_SIZE       4096
#define HEAP_MAX_SIZE   (32u * 1024 * 1024)
#define HEAP_MIN_SIZE   (1u  * 1024 * 1024)
#define BLOCK_MAGIC     0xB10CB10Cu
#define MAX_TASKS       32
#define TASK_STACK_SIZE 16384
#define QUANTUM_TICKS   5
#define KB_BUF_SIZE     256
#define SHELL_LINE_MAX  128

/* =============================================================== port I/O == */
static inline void outb(u16 port, u8 v)  { __asm__ volatile("outb %0, %1" : : "a"(v), "Nd"(port)); }
static inline u8   inb(u16 port)         { u8 r; __asm__ volatile("inb %1, %0" : "=a"(r) : "Nd"(port)); return r; }
static inline void outw(u16 port, u16 v) { __asm__ volatile("outw %0, %1" : : "a"(v), "Nd"(port)); }
static inline u16  inw(u16 port)         { u16 r; __asm__ volatile("inw %1, %0" : "=a"(r) : "Nd"(port)); return r; }
static inline void io_wait(void)         { outb(0x80, 0); }

static inline u32 irq_save(void) {
    u32 f;
    __asm__ volatile("pushfl; popl %0; cli" : "=r"(f) : : "memory");
    return f;
}
static inline void irq_restore(u32 f) {
    __asm__ volatile("pushl %0; popfl" : : "r"(f) : "memory", "cc");
}

/* ============================================================== strings ==== */
void *memset(void *dest, int val, size_t len) {
    u8 *p = dest;
    while (len--) *p++ = (u8)val;
    return dest;
}
void *memcpy(void *dest, const void *src, size_t len) {
    u8 *d = dest; const u8 *s = src;
    while (len--) *d++ = *s++;
    return dest;
}
void *memmove(void *dest, const void *src, size_t len) {
    u8 *d = dest; const u8 *s = src;
    if (d == s || len == 0) return dest;
    if (d < s) { while (len--) *d++ = *s++; }
    else { d += len; s += len; while (len--) *--d = *--s; }
    return dest;
}
int memcmp(const void *a, const void *b, size_t n) {
    const u8 *p = a, *q = b;
    for (; n; n--, p++, q++) if (*p != *q) return *p - *q;
    return 0;
}
size_t strlen(const char *s) { size_t n = 0; while (s[n]) n++; return n; }
int strcmp(const char *a, const char *b) {
    while (*a && *a == *b) { a++; b++; }
    return (u8)*a - (u8)*b;
}
int strncmp(const char *a, const char *b, size_t n) {
    for (; n; n--, a++, b++) {
        if (*a != *b) return (u8)*a - (u8)*b;
        if (!*a) return 0;
    }
    return 0;
}
char *strcpy(char *d, const char *s) { char *r = d; while ((*d++ = *s++)); return r; }
char *strncpy(char *d, const char *s, size_t n) {
    size_t i = 0;
    for (; i < n && s[i]; i++) d[i] = s[i];
    for (; i < n; i++) d[i] = 0;
    return d;
}
char *strcat(char *d, const char *s) { char *r = d; while (*d) d++; while ((*d++ = *s++)); return r; }
char *strchr(const char *s, int c) {
    for (;; s++) { if (*s == (char)c) return (char *)s; if (!*s) return NULL; }
}
static int atoi_simple(const char *s) {
    int neg = 0, v = 0;
    while (*s == ' ') s++;
    if (*s == '-') { neg = 1; s++; } else if (*s == '+') s++;
    while (*s >= '0' && *s <= '9') v = v * 10 + (*s++ - '0');
    return neg ? -v : v;
}

/* =============================================================== serial ==== */
static bool serial_ok = false;

static void serial_init(void) {
    outb(COM1 + 1, 0x00);          /* disable interrupts            */
    outb(COM1 + 3, 0x80);          /* DLAB                          */
    outb(COM1 + 0, 0x01);          /* 115200 baud                   */
    outb(COM1 + 1, 0x00);
    outb(COM1 + 3, 0x03);          /* 8N1                           */
    outb(COM1 + 2, 0xC7);          /* FIFO                          */
    outb(COM1 + 4, 0x0B);          /* RTS/DSR                       */
    serial_ok = true;
}
static void serial_putc(char c) {
    if (!serial_ok) return;
    int guard = 100000;
    while (!(inb(COM1 + 5) & 0x20) && guard--) ;
    outb(COM1, (u8)c);
}

/* ============================================================= console ===== */
static volatile u16 *vga = VGA_MEMORY;
static u8 cur_x = 0, cur_y = 0;
static u8 cur_color = 0x0F;

static inline u8  make_color(u8 fg, u8 bg) { return (u8)(fg | (bg << 4)); }
static inline u16 vga_entry(char c, u8 color) { return (u16)(u8)c | ((u16)color << 8); }

static void update_cursor(void) {
    u16 pos = (u16)(cur_y * VGA_WIDTH + cur_x);
    outb(VGA_CTRL, 0x0F); outb(VGA_DATA, (u8)(pos & 0xFF));
    outb(VGA_CTRL, 0x0E); outb(VGA_DATA, (u8)(pos >> 8));
}
void set_color(u8 fg, u8 bg) { cur_color = make_color(fg, bg); }

void clear_screen(void) {
    for (int i = 0; i < VGA_WIDTH * CONSOLE_ROWS; i++) vga[i] = vga_entry(' ', cur_color);
    cur_x = cur_y = 0;
    update_cursor();
}
static void scroll(void) {
    for (int i = 0; i < VGA_WIDTH * (CONSOLE_ROWS - 1); i++) vga[i] = vga[i + VGA_WIDTH];
    for (int i = 0; i < VGA_WIDTH; i++)
        vga[(CONSOLE_ROWS - 1) * VGA_WIDTH + i] = vga_entry(' ', cur_color);
    cur_y = CONSOLE_ROWS - 1;
}
void putchar(char c) {
    u32 f = irq_save();
    serial_putc(c);
    switch (c) {
    case '\n': cur_x = 0; cur_y++; serial_putc('\r'); break;
    case '\r': cur_x = 0; break;
    case '\t': cur_x = (u8)((cur_x + 8) & ~7); break;
    case '\b':
        if (cur_x > 0) { cur_x--; vga[cur_y * VGA_WIDTH + cur_x] = vga_entry(' ', cur_color); }
        break;
    default:
        vga[cur_y * VGA_WIDTH + cur_x] = vga_entry(c, cur_color);
        cur_x++;
    }
    if (cur_x >= VGA_WIDTH) { cur_x = 0; cur_y++; }
    if (cur_y >= CONSOLE_ROWS) scroll();
    update_cursor();
    irq_restore(f);
}
void print(const char *s) { while (*s) putchar(*s++); }

/* status bar (row 24) – written directly, never scrolls */
static void status_write(int col, const char *s, u8 color) {
    for (; *s && col < VGA_WIDTH; col++, s++)
        vga[(VGA_HEIGHT - 1) * VGA_WIDTH + col] = vga_entry(*s, color);
}
static void status_fill(u8 color) {
    for (int i = 0; i < VGA_WIDTH; i++) vga[(VGA_HEIGHT - 1) * VGA_WIDTH + i] = vga_entry(' ', color);
}

/* ============================================================== printf ===== */
static void print_num(u32 n, u32 base, bool upper, int width, char pad, bool neg) {
    char buf[34];
    const char *digits = upper ? "0123456789ABCDEF" : "0123456789abcdef";
    int i = 0;
    if (n == 0) buf[i++] = '0';
    while (n) { buf[i++] = digits[n % base]; n /= base; }
    if (neg) buf[i++] = '-';
    while (i < width && i < 33) buf[i++] = pad;
    if (neg && pad == '0') {                     /* move '-' in front of zeros */
        int j = 0; while (j < i && buf[j] != '-') j++;
        if (j < i) { buf[j] = '0'; buf[i - 1] = '-'; }
    }
    while (i > 0) putchar(buf[--i]);
}

static int num_width(u32 n, u32 base) {
    int w = 1;
    while (n >= base) { n /= base; w++; }
    return w;
}

static void vprintf_impl(const char *fmt, __builtin_va_list ap) {
    for (; *fmt; fmt++) {
        if (*fmt != '%') { putchar(*fmt); continue; }
        fmt++;
        char pad = ' '; int width = 0; bool left = false;
        for (;; fmt++) {
            if (*fmt == '-') left = true;
            else if (*fmt == '0') pad = '0';
            else break;
        }
        while (*fmt >= '0' && *fmt <= '9') width = width * 10 + (*fmt++ - '0');
        while (*fmt == 'l') fmt++;
        if (left) pad = ' ';
        switch (*fmt) {
        case 'd': case 'i': {
            int v = __builtin_va_arg(ap, int);
            print_num(v < 0 ? (u32)(-(v + 1)) + 1u : (u32)v, 10, false, left ? 0 : width, pad, v < 0);
            if (left) { int n = num_width(v < 0 ? (u32)(-(v + 1)) + 1u : (u32)v, 10) + (v < 0); while (n++ < width) putchar(' '); }
            break;
        }
        case 'u': case 'x': case 'X': {
            u32 v = __builtin_va_arg(ap, u32);
            u32 base = (*fmt == 'u') ? 10 : 16;
            print_num(v, base, *fmt == 'X', left ? 0 : width, pad, false);
            if (left) { int n = num_width(v, base); while (n++ < width) putchar(' '); }
            break;
        }
        case 'p': print("0x"); print_num((u32)__builtin_va_arg(ap, void *), 16, false, 8, '0', false); break;
        case 'c': putchar((char)__builtin_va_arg(ap, int)); break;
        case 's': {
            const char *s = __builtin_va_arg(ap, const char *);
            if (!s) s = "(null)";
            int len = (int)strlen(s);
            if (!left) for (int k = len; k < width; k++) putchar(' ');
            print(s);
            if (left) for (int k = len; k < width; k++) putchar(' ');
            break;
        }
        case '%': putchar('%'); break;
        case 0:   return;
        default:  putchar('%'); putchar(*fmt); break;
        }
    }
}
void printf(const char *fmt, ...) {
    __builtin_va_list ap;
    __builtin_va_start(ap, fmt);
    vprintf_impl(fmt, ap);
    __builtin_va_end(ap);
}

static void log_tag(const char *tag, u8 color) {
    putchar('['); u8 c = cur_color; set_color(color, VGA_BLACK); print(tag); cur_color = c; print("] ");
}
#define LOG(tag, ...)  do { log_tag(tag, VGA_LIGHT_CYAN);  printf(__VA_ARGS__); } while (0)
#define OK(...)        do { log_tag(" OK ", VGA_LIGHT_GREEN); printf(__VA_ARGS__); } while (0)
#define WARN(...)      do { log_tag("WARN", VGA_YELLOW);     printf(__VA_ARGS__); } while (0)

/* ============================================================ boot info ==== */
static struct {
    u32 mem_lower_kb, mem_upper_kb;
    u32 phys_top;            /* highest usable physical address (+1) */
    u32 e820_count;
    e820_entry_t e820[64];
    u32 cpu_flags;
    char vendor[13];
    const char *loader;
} boot;

static void parse_boot_info(u32 magic, void *info) {
    if (magic == BOOT_MAGIC_MINIOS && info) {
        boot_info_t *bi = info;
        boot.loader = "MiniOS bootloader";
        boot.mem_lower_kb = bi->mem_lower;
        boot.mem_upper_kb = bi->mem_upper;
        boot.cpu_flags = bi->cpu_flags;
        memcpy(boot.vendor, bi->vendor, 13);
        e820_entry_t *e = (e820_entry_t *)bi->e820_addr;
        for (u32 i = 0; i < bi->e820_count && boot.e820_count < 64; i++)
            boot.e820[boot.e820_count++] = e[i];
    } else if (magic == BOOT_MAGIC_MULTIBOOT && info) {
        multiboot_info_t *mb = info;
        boot.loader = "Multiboot (GRUB)";
        if (mb->flags & 1) { boot.mem_lower_kb = mb->mem_lower; boot.mem_upper_kb = mb->mem_upper; }
        if (mb->flags & (1 << 6)) {
            u32 p = mb->mmap_addr, end = mb->mmap_addr + mb->mmap_length;
            while (p < end && boot.e820_count < 64) {
                multiboot_mmap_t *m = (multiboot_mmap_t *)p;
                e820_entry_t *d = &boot.e820[boot.e820_count++];
                d->base = m->base; d->length = m->length; d->type = m->type; d->acpi = 1;
                p += m->size + 4;
            }
        }
    } else {
        boot.loader = "unknown (assuming 32 MiB)";
        boot.mem_lower_kb = 640;
        boot.mem_upper_kb = 31 * 1024;
    }
    if (!boot.vendor[0] && cpuid_available()) {
        u32 r[4]; get_cpuid(0, r);
        memcpy(boot.vendor, &r[1], 4); memcpy(boot.vendor + 4, &r[3], 4); memcpy(boot.vendor + 8, &r[2], 4);
        boot.vendor[12] = 0;
    }
    if (!boot.vendor[0]) strcpy(boot.vendor, "unknown");

    /* derive totals + highest usable address below 4 GiB from the map */
    u32 upper_from_map = 0, lower_from_map = 0;
    boot.phys_top = 0x100000 + boot.mem_upper_kb * 1024;
    for (u32 i = 0; i < boot.e820_count; i++) {
        e820_entry_t *e = &boot.e820[i];
        if (e->type != 1 || (e->base >> 32)) continue;
        u64 end = e->base + e->length;
        if (end > 0xFFFFFFFFull) end = 0xFFFFFFFFull;
        if ((u32)end > boot.phys_top) boot.phys_top = (u32)end;
        if (end > 0x100000) upper_from_map += (u32)((end - (e->base > 0x100000 ? e->base : 0x100000)) >> 10);
        if (e->base < 0x100000) lower_from_map += (u32)(((end < 0x100000 ? end : 0x100000) - e->base) >> 10);
    }
    if (!boot.mem_upper_kb) boot.mem_upper_kb = upper_from_map;
    if (!boot.mem_lower_kb) boot.mem_lower_kb = lower_from_map;
}

/* ================================================================= GDT ===== */
struct gdt_entry { u16 limit_lo, base_lo; u8 base_mid, access, gran, base_hi; } __attribute__((packed));
struct gdt_ptr   { u16 limit; u32 base; } __attribute__((packed));

static struct gdt_entry gdt[5];
static struct gdt_ptr   gdt_ptr;
extern void load_gdt(struct gdt_ptr *p);

static void gdt_set(int i, u32 base, u32 limit, u8 access, u8 gran) {
    gdt[i].base_lo = base & 0xFFFF; gdt[i].base_mid = (base >> 16) & 0xFF; gdt[i].base_hi = (base >> 24) & 0xFF;
    gdt[i].limit_lo = limit & 0xFFFF; gdt[i].gran = (u8)(((limit >> 16) & 0x0F) | (gran & 0xF0));
    gdt[i].access = access;
}
static void gdt_install(void) {
    gdt_set(0, 0, 0, 0, 0);
    gdt_set(1, 0, 0xFFFFF, 0x9A, 0xCF);    /* 0x08 kernel code */
    gdt_set(2, 0, 0xFFFFF, 0x92, 0xCF);    /* 0x10 kernel data */
    gdt_set(3, 0, 0xFFFFF, 0xFA, 0xCF);    /* 0x18 user code   */
    gdt_set(4, 0, 0xFFFFF, 0xF2, 0xCF);    /* 0x20 user data   */
    gdt_ptr.limit = sizeof(gdt) - 1;
    gdt_ptr.base = (u32)&gdt;
    load_gdt(&gdt_ptr);
}

/* ================================================================= IDT ===== */
static idt_entry_t idt[256];
static idt_ptr_t   idt_ptr;

#define ISR(n) extern void isr##n(void);
ISR(0) ISR(1) ISR(2) ISR(3) ISR(4) ISR(5) ISR(6) ISR(7) ISR(8) ISR(9) ISR(10) ISR(11)
ISR(12) ISR(13) ISR(14) ISR(15) ISR(16) ISR(17) ISR(18) ISR(19) ISR(20) ISR(21) ISR(22)
ISR(23) ISR(24) ISR(25) ISR(26) ISR(27) ISR(28) ISR(29) ISR(30) ISR(31)
#define IRQ(n) extern void irq##n(void);
IRQ(0) IRQ(1) IRQ(2) IRQ(3) IRQ(4) IRQ(5) IRQ(6) IRQ(7) IRQ(8) IRQ(9) IRQ(10) IRQ(11)
IRQ(12) IRQ(13) IRQ(14) IRQ(15)
extern void syscall_int(void);

static void idt_set_gate(u8 n, void (*handler)(void), u8 flags) {
    u32 base = (u32)handler;
    idt[n].base_low = base & 0xFFFF;
    idt[n].base_high = (base >> 16) & 0xFFFF;
    idt[n].selector = 0x08;
    idt[n].always0 = 0;
    idt[n].flags = flags;
}
static void idt_install(void) {
    void (*isrs[32])(void) = {
        isr0, isr1, isr2, isr3, isr4, isr5, isr6, isr7, isr8, isr9, isr10, isr11, isr12, isr13,
        isr14, isr15, isr16, isr17, isr18, isr19, isr20, isr21, isr22, isr23, isr24, isr25, isr26,
        isr27, isr28, isr29, isr30, isr31 };
    void (*irqs[16])(void) = {
        irq0, irq1, irq2, irq3, irq4, irq5, irq6, irq7, irq8, irq9, irq10, irq11, irq12, irq13,
        irq14, irq15 };
    memset(idt, 0, sizeof(idt));
    for (int i = 0; i < 32; i++) idt_set_gate((u8)i, isrs[i], 0x8E);
    for (int i = 0; i < 16; i++) idt_set_gate((u8)(32 + i), irqs[i], 0x8E);
    idt_set_gate(0x80, syscall_int, 0xEE);      /* DPL 3: callable from user mode */
    idt_ptr.limit = sizeof(idt) - 1;
    idt_ptr.base = (u32)&idt;
    load_idt(&idt_ptr);
}

/* ================================================================= PIC ===== */
static void pic_remap(void) {
    outb(PIC1_CMD, 0x11); io_wait(); outb(PIC2_CMD, 0x11); io_wait();
    outb(PIC1_DATA, 0x20); io_wait(); outb(PIC2_DATA, 0x28); io_wait();   /* vectors 32-47 */
    outb(PIC1_DATA, 0x04); io_wait(); outb(PIC2_DATA, 0x02); io_wait();   /* cascade on IRQ2 */
    outb(PIC1_DATA, 0x01); io_wait(); outb(PIC2_DATA, 0x01); io_wait();   /* 8086 mode */
    outb(PIC1_DATA, 0xF8);   /* unmask timer, keyboard, cascade */
    outb(PIC2_DATA, 0xFF);
}
static inline void pic_eoi(u32 irq) {
    if (irq >= 8) outb(PIC2_CMD, PIC_EOI);
    outb(PIC1_CMD, PIC_EOI);
}

/* ================================================================ timer ==== */
static volatile u32 ticks = 0;
static u32 cpu_mhz = 0;

static void pit_init(u32 hz) {
    u32 div = 1193182 / hz;
    outb(0x43, 0x36);
    outb(0x40, (u8)(div & 0xFF));
    outb(0x40, (u8)(div >> 8));
}
static void sleep_ticks_busy(u32 n) {          /* usable before tasking */
    u32 end = ticks + n;
    while ((i32)(ticks - end) < 0) halt();
}
static void format_uptime(char *out) {          /* "HH:MM:SS" */
    u32 s = ticks / PIT_HZ;
    u32 h = s / 3600, m = (s / 60) % 60; s %= 60;
    out[0] = (char)('0' + h / 10 % 10); out[1] = (char)('0' + h % 10); out[2] = ':';
    out[3] = (char)('0' + m / 10); out[4] = (char)('0' + m % 10); out[5] = ':';
    out[6] = (char)('0' + s / 10); out[7] = (char)('0' + s % 10); out[8] = 0;
}

/* ============================================================= keyboard ==== */
static const char kb_map[128] = {
    0, 27, '1','2','3','4','5','6','7','8','9','0','-','=','\b','\t',
    'q','w','e','r','t','y','u','i','o','p','[',']','\n', 0,
    'a','s','d','f','g','h','j','k','l',';','\'','`', 0,'\\',
    'z','x','c','v','b','n','m',',','.','/', 0,'*', 0,' ', 0,
};
static const char kb_map_shift[128] = {
    0, 27, '!','@','#','$','%','^','&','*','(',')','_','+','\b','\t',
    'Q','W','E','R','T','Y','U','I','O','P','{','}','\n', 0,
    'A','S','D','F','G','H','J','K','L',':','"','~', 0,'|',
    'Z','X','C','V','B','N','M','<','>','?', 0,'*', 0,' ', 0,
};
static char kb_buf[KB_BUF_SIZE];
static volatile u32 kb_head = 0, kb_tail = 0;
static bool kb_shift = false, kb_ctrl = false, kb_alt = false, kb_caps = false;
static bool kb_extended = false;

static void kb_push(char c) {
    u32 next = (kb_head + 1) % KB_BUF_SIZE;
    if (next != kb_tail) { kb_buf[kb_head] = c; kb_head = next; }
}
static bool kb_has_key(void) { return kb_head != kb_tail; }
static char kb_getc_nonblock(void) {
    if (!kb_has_key()) return 0;
    char c = kb_buf[kb_tail];
    kb_tail = (kb_tail + 1) % KB_BUF_SIZE;
    return c;
}
static char kb_getc(void) {
    char c;
    while (!(c = kb_getc_nonblock())) halt();
    return c;
}
static void keyboard_irq(void) {
    u8 sc = inb(0x60);
    if (sc == 0xE0) { kb_extended = true; return; }
    if (kb_extended) { kb_extended = false; return; }     /* arrows etc: ignored */
    bool release = sc & 0x80;
    sc &= 0x7F;
    switch (sc) {
    case 0x2A: case 0x36: kb_shift = !release; return;
    case 0x1D: kb_ctrl = !release; return;
    case 0x38: kb_alt = !release; return;
    case 0x3A: if (!release) kb_caps = !kb_caps; return;
    }
    if (release || sc >= 128) return;
    char c = kb_shift ? kb_map_shift[sc] : kb_map[sc];
    if (!c) return;
    if (kb_caps && ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'))) c ^= 0x20;
    if (kb_ctrl && c >= 'a' && c <= 'z') c = (char)(c - 'a' + 1);
    kb_push(c);
}
static void keyboard_init(void) {
    while (inb(0x64) & 1) inb(0x60);          /* drain */
}

/* ================================================================= heap ==== */
typedef struct block {
    u32 magic;
    size_t size;                 /* payload size */
    bool used;
    struct block *next, *prev;
} block_t;

static block_t *heap_head = NULL;
static u32 heap_start = 0, heap_end = 0;
static volatile u32 heap_lock = 0;
static struct { u32 allocs, frees, bytes_used, peak; } heap_stats;

static void heap_init(u32 start, u32 end) {
    heap_start = start; heap_end = end;
    heap_head = (block_t *)start;
    heap_head->magic = BLOCK_MAGIC;
    heap_head->size = end - start - sizeof(block_t);
    heap_head->used = false;
    heap_head->next = heap_head->prev = NULL;
}
static void heap_split(block_t *b, size_t size) {
    if (b->size < size + sizeof(block_t) + 32) return;
    block_t *n = (block_t *)((u8 *)(b + 1) + size);
    n->magic = BLOCK_MAGIC; n->size = b->size - size - sizeof(block_t); n->used = false;
    n->next = b->next; n->prev = b;
    if (b->next) b->next->prev = n;
    b->next = n; b->size = size;
}
void *kmalloc_aligned(size_t size, u32 align) {
    if (!size || !heap_head) return NULL;
    if (align < 16) align = 16;
    size = (size + 15) & ~15u;
    u32 f = irq_save(); spinlock_acquire(&heap_lock);
    for (block_t *b = heap_head; b; b = b->next) {
        if (b->used) continue;
        u32 payload = (u32)(b + 1);
        u32 aligned = (payload + align - 1) & ~(align - 1);
        u32 gap = aligned - payload;
        if (gap && gap < sizeof(block_t) + 16) {          /* not enough room for a split */
            aligned += align; gap = aligned - payload;
        }
        if (b->size < gap + size) continue;
        if (gap) {                                          /* carve leading free block */
            heap_split(b, gap - sizeof(block_t));
            b = b->next;
        }
        heap_split(b, size);
        b->used = true;
        heap_stats.allocs++; heap_stats.bytes_used += b->size;
        if (heap_stats.bytes_used > heap_stats.peak) heap_stats.peak = heap_stats.bytes_used;
        spinlock_release(&heap_lock); irq_restore(f);
        return b + 1;
    }
    spinlock_release(&heap_lock); irq_restore(f);
    return NULL;
}
void *kmalloc(size_t size) { return kmalloc_aligned(size, 16); }
void *kcalloc(size_t n, size_t sz) {
    void *p = kmalloc(n * sz);
    if (p) memset(p, 0, n * sz);
    return p;
}
void kfree(void *ptr) {
    if (!ptr) return;
    block_t *b = (block_t *)ptr - 1;
    if (b->magic != BLOCK_MAGIC || !b->used) { WARN("kfree(%p): bad block\n", ptr); return; }
    u32 f = irq_save(); spinlock_acquire(&heap_lock);
    b->used = false;
    heap_stats.frees++; heap_stats.bytes_used -= b->size;
    if (b->next && !b->next->used) {                       /* merge with next */
        b->size += sizeof(block_t) + b->next->size;
        b->next = b->next->next;
        if (b->next) b->next->prev = b;
    }
    if (b->prev && !b->prev->used) {                       /* merge with prev */
        b->prev->size += sizeof(block_t) + b->size;
        b->prev->next = b->next;
        if (b->next) b->next->prev = b->prev;
    }
    spinlock_release(&heap_lock); irq_restore(f);
}
void *krealloc(void *ptr, size_t size) {
    if (!ptr) return kmalloc(size);
    if (!size) { kfree(ptr); return NULL; }
    block_t *b = (block_t *)ptr - 1;
    if (b->size >= size) return ptr;
    void *n = kmalloc(size);
    if (n) { memcpy(n, ptr, b->size); kfree(ptr); }
    return n;
}
static u32 heap_free_bytes(void) {
    u32 t = 0;
    for (block_t *b = heap_head; b; b = b->next) if (!b->used) t += b->size;
    return t;
}
static bool heap_check(void) {
    for (block_t *b = heap_head; b; b = b->next) {
        if (b->magic != BLOCK_MAGIC) return false;
        if (b->next && b->next->prev != b) return false;
    }
    return true;
}

/* ===================================================== frame allocator ==== */
static u32 *frame_bitmap = NULL;
static u32 frame_base = 0, frame_count = 0, frames_used = 0;

static void frames_init(u32 start, u32 end) {
    frame_base = (start + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1);
    frame_count = end > frame_base ? (end - frame_base) / PAGE_SIZE : 0;
    u32 words = (frame_count + 31) / 32;
    frame_bitmap = kcalloc(words ? words : 1, sizeof(u32));
    if (!frame_bitmap) frame_count = 0;
}
static u32 alloc_frame(void) {
    for (u32 i = 0; i < frame_count; i++) {
        if (!(frame_bitmap[i / 32] & (1u << (i % 32)))) {
            frame_bitmap[i / 32] |= 1u << (i % 32);
            frames_used++;
            return frame_base + i * PAGE_SIZE;
        }
    }
    return 0;
}
static void free_frame(u32 addr) {
    if (addr < frame_base) return;
    u32 i = (addr - frame_base) / PAGE_SIZE;
    if (i >= frame_count || !(frame_bitmap[i / 32] & (1u << (i % 32)))) return;
    frame_bitmap[i / 32] &= ~(1u << (i % 32));
    frames_used--;
}

/* ============================================================== tasking ==== */
typedef enum { TASK_READY, TASK_RUNNING, TASK_SLEEPING, TASK_ZOMBIE } task_state_t;

typedef struct task {
    u32 pid;
    char name[24];
    task_state_t state;
    cpu_context_t ctx;
    u8 *stack;
    void (*entry)(void);
    u32 wake_tick;
    u32 quantum;
    u32 cpu_ticks;
    u32 switches;
    struct task *next;
} task_t;

static task_t tasks[MAX_TASKS];
static task_t *current = NULL;
static u32 next_pid = 1;
static u32 context_switches = 0;
static bool tasking_on = false;

static void schedule(void);

static void task_exit(void) {
    disable_interrupts();
    current->state = TASK_ZOMBIE;
    schedule();
    for (;;) halt();
}
static void task_trampoline(void) {
    /* entered with IF set (initial eflags on the crafted stack) */
    current->entry();
    task_exit();
}
static task_t *task_alloc(void) {
    for (int i = 0; i < MAX_TASKS; i++) if (tasks[i].state == TASK_ZOMBIE && tasks[i].pid == 0) return &tasks[i];
    return NULL;
}
static task_t *task_create(const char *name, void (*entry)(void)) {
    u32 f = irq_save();
    task_t *t = task_alloc();
    if (!t) { irq_restore(f); return NULL; }
    memset(t, 0, sizeof(*t));
    t->stack = kmalloc_aligned(TASK_STACK_SIZE, 16);
    if (!t->stack) { irq_restore(f); return NULL; }
    strncpy(t->name, name, sizeof(t->name) - 1);
    t->pid = next_pid++;
    t->entry = entry;
    t->quantum = QUANTUM_TICKS;
    /* initial frame for switch_context: eflags, edi, esi, ebx, ebp, ret */
    u32 *sp = (u32 *)(t->stack + TASK_STACK_SIZE);
    *--sp = 0;                          /* fake return address of trampoline */
    *--sp = (u32)task_trampoline;       /* ret target                        */
    *--sp = 0; *--sp = 0; *--sp = 0; *--sp = 0;   /* ebp ebx esi edi          */
    *--sp = 0x202;                      /* eflags: IF=1                      */
    t->ctx.esp = (u32)sp;
    t->state = TASK_READY;
    /* insert after current in the ring */
    t->next = current->next;
    current->next = t;
    irq_restore(f);
    return t;
}
static void task_reap(task_t *t) {
    if (t->stack) kfree(t->stack);
    t->stack = NULL;
    t->pid = 0;
    t->state = TASK_ZOMBIE;
}
/* Must be called with interrupts disabled. */
static void schedule(void) {
    if (!tasking_on || !current) return;
    task_t *prev = current;
    task_t *t = current->next;
    task_t *next = NULL;
    for (int i = 0; i < MAX_TASKS && t; i++, t = t->next) {
        if (t->state == TASK_SLEEPING && (i32)(ticks - t->wake_tick) >= 0) t->state = TASK_READY;
        if (t->state == TASK_READY || (t->state == TASK_RUNNING && t == prev)) { next = t; break; }
    }
    /* unlink zombies behind us (never the one we are running on) */
    task_t *p = prev;
    for (int i = 0; i < MAX_TASKS; i++) {
        task_t *z = p->next;
        if (z == prev) break;
        if (z->state == TASK_ZOMBIE && z != prev) { p->next = z->next; task_reap(z); continue; }
        p = z;
    }
    if (!next || next == prev) {
        if (prev->state == TASK_RUNNING) prev->quantum = QUANTUM_TICKS;
        return;
    }
    if (prev->state == TASK_RUNNING) prev->state = TASK_READY;
    next->state = TASK_RUNNING;
    next->quantum = QUANTUM_TICKS;
    next->switches++;
    context_switches++;
    current = next;
    switch_context(&prev->ctx, &next->ctx);
}
static void yield(void) __attribute__((unused));
static void yield(void) {
    u32 f = irq_save();
    schedule();
    irq_restore(f);
}
static void sleep_ms(u32 ms) {
    if (!tasking_on) { sleep_ticks_busy(ms / (1000 / PIT_HZ)); return; }
    u32 f = irq_save();
    current->wake_tick = ticks + (ms + (1000 / PIT_HZ) - 1) / (1000 / PIT_HZ);
    current->state = TASK_SLEEPING;
    schedule();
    irq_restore(f);
}
static void tasking_init(void) {
    for (int i = 0; i < MAX_TASKS; i++) { tasks[i].state = TASK_ZOMBIE; tasks[i].pid = 0; }
    task_t *t = &tasks[0];
    memset(t, 0, sizeof(*t));
    strcpy(t->name, "kernel");
    t->pid = 0;
    t->state = TASK_RUNNING;
    t->quantum = QUANTUM_TICKS;
    t->next = t;
    current = t;
    tasking_on = true;
}

/* background thread: keeps the status bar clock alive (visible preemption) */
static volatile u32 bg_counter = 0;
static void status_task(void) {
    for (;;) {
        char up[9];
        format_uptime(up);
        status_write(VGA_WIDTH - 9, up, make_color(VGA_BLACK, VGA_LIGHT_GREY));
        bg_counter++;
        sleep_ms(500);
    }
}

/* ============================================================= syscalls ==== */
u32 syscall_handler(interrupt_frame_t *f) {
    u32 num = f->eax, a1 = f->ebx, a2 = f->ecx, a3 = f->edx;
    u32 ret = (u32)-1;
    switch (num) {
    case SYSCALL_WRITE:
        if (a1 == 1 || a1 == 2) {
            const char *s = (const char *)a2;
            for (u32 i = 0; i < a3; i++) putchar(s[i]);
            ret = a3;
        }
        break;
    case SYSCALL_READ:
        if (a1 == 0 && a3) { ((char *)a2)[0] = kb_getc(); ret = 1; }
        break;
    case SYSCALL_GETPID: ret = current ? current->pid : 0; break;
    case SYSCALL_YIELD:  schedule(); ret = 0; break;
    case SYSCALL_SLEEP:  sleep_ms(a1); ret = 0; break;
    case SYSCALL_UPTIME: ret = ticks * (1000 / PIT_HZ); break;
    case SYSCALL_EXIT:
        if (current && current->pid != 0) { task_exit(); }
        ret = 0;
        break;
    default: break;
    }
    f->eax = ret;
    return ret;
}
static inline u32 do_syscall(u32 n, u32 a, u32 b, u32 c) {
    u32 r;
    __asm__ volatile("int $0x80" : "=a"(r) : "a"(n), "b"(a), "c"(b), "d"(c) : "memory");
    return r;
}

/* =========================================================== exceptions ==== */
static const char *exception_names[32] = {
    "Divide-by-zero", "Debug", "Non-maskable interrupt", "Breakpoint", "Overflow",
    "Bound range exceeded", "Invalid opcode", "Device not available", "Double fault",
    "Coprocessor segment overrun", "Invalid TSS", "Segment not present", "Stack fault",
    "General protection fault", "Page fault", "Reserved", "x87 floating-point",
    "Alignment check", "Machine check", "SIMD floating-point", "Virtualization",
    "Control protection", "Reserved", "Reserved", "Reserved", "Reserved", "Reserved",
    "Reserved", "Reserved", "VMM communication", "Security exception", "Reserved" };

void kernel_panic(const char *msg, interrupt_frame_t *f) {
    disable_interrupts();
    set_color(VGA_WHITE, VGA_RED);
    printf("\n *** KERNEL PANIC: %s ***\n", msg);
    if (f) {
        printf(" int=%u err=0x%x eip=0x%08x cs=0x%x eflags=0x%08x\n",
               f->int_no, f->err_code, f->eip, f->cs, f->eflags);
        printf(" eax=%08x ebx=%08x ecx=%08x edx=%08x\n", f->eax, f->ebx, f->ecx, f->edx);
        printf(" esi=%08x edi=%08x ebp=%08x esp=%08x\n", f->esi, f->edi, f->ebp, f->esp);
        if (f->int_no == 14) {
            u32 cr2 = get_cr2();
            printf(" page fault at 0x%08x (%s, %s, %s)\n", cr2,
                   (f->err_code & 1) ? "protection" : "not-present",
                   (f->err_code & 2) ? "write" : "read",
                   (f->err_code & 4) ? "user" : "kernel");
        }
    }
    printf(" task=%s pid=%u uptime=%u ticks\n", current ? current->name : "?",
           current ? current->pid : 0, ticks);
    printf(" System halted.\n");
    for (;;) halt();
}

void isr_handler(interrupt_frame_t *f) {
    if (f->int_no == 3) {                                   /* breakpoint: report & continue */
        printf("\n[BREAKPOINT] at eip=0x%08x\n", f->eip);
        return;
    }
    kernel_panic(f->int_no < 32 ? exception_names[f->int_no] : "Unknown exception", f);
}

void irq_handler(interrupt_frame_t *f) {
    u32 irq = f->int_no - 32;
    if (irq == 7 && !(({ outb(PIC1_CMD, 0x0B); inb(PIC1_CMD); }) & 0x80)) return;  /* spurious */
    if (irq == 15 && !(({ outb(PIC2_CMD, 0x0B); inb(PIC2_CMD); }) & 0x80)) { outb(PIC1_CMD, PIC_EOI); return; }

    switch (irq) {
    case 0:
        ticks++;
        pic_eoi(0);
        if (tasking_on && current) {
            current->cpu_ticks++;
            if (current->quantum) current->quantum--;
            if (current->quantum == 0) schedule();     /* preempt (IF is clear here) */
        }
        return;
    case 1:
        keyboard_irq();
        break;
    default:
        break;
    }
    pic_eoi(irq);
}

/* ================================================================ shell ==== */
static void shell_prompt(void) {
    set_color(VGA_LIGHT_GREEN, VGA_BLACK); print("minios");
    set_color(VGA_WHITE, VGA_BLACK);       print(":/$ ");
    set_color(VGA_LIGHT_GREY, VGA_BLACK);
}
static const char *state_name(task_state_t s) {
    switch (s) { case TASK_READY: return "ready"; case TASK_RUNNING: return "running";
                 case TASK_SLEEPING: return "sleep"; default: return "zombie"; }
}

static void cmd_help(void) {
    print("Commands:\n"
          "  help              this text            clear      clear the screen\n"
          "  mem               memory map + heap    ps         task list\n"
          "  uptime            time since boot      cpuinfo    CPU information\n"
          "  echo <text>       print text           color <n>  text colour 0-15\n"
          "  alloc <bytes>     heap test            heaptest   allocator self-test\n"
          "  spawn [n]         start demo threads   kill <pid> stop a thread\n"
          "  syscall           INT 0x80 demo        sleep <ms> sleep current task\n"
          "  ticks             timer ticks          bp         trigger breakpoint\n"
          "  crash             divide by zero       ud         invalid opcode\n"
          "  drivers           driver list          date       CMOS clock\n"
          "  disk [lba]        read a disk sector   reboot     reset the machine\n"
          "  halt              stop the CPU\n");
}
static void cmd_mem(void) {
    printf("Loader   : %s\n", boot.loader);
    printf("Memory   : %u KiB low, %u KiB high (top 0x%08x, ~%u MiB)\n",
           boot.mem_lower_kb, boot.mem_upper_kb, boot.phys_top, boot.phys_top >> 20);
    if (boot.e820_count) {
        print("E820 map :\n");
        for (u32 i = 0; i < boot.e820_count; i++) {
            e820_entry_t *e = &boot.e820[i];
            static const char *types[] = { "?", "usable", "reserved", "ACPI reclaim", "ACPI NVS", "bad" };
            printf("  %08x%08x - %08x%08x  %s\n", (u32)(e->base >> 32), (u32)e->base,
                   (u32)((e->base + e->length) >> 32), (u32)(e->base + e->length),
                   e->type < 6 ? types[e->type] : "?");
        }
    }
    printf("Kernel   : 0x%08x - 0x%08x (%u KiB: text %u, rodata %u, data %u, bss %u)\n",
           (u32)_kernel_start, (u32)_kernel_end, ((u32)_kernel_end - (u32)_kernel_start) >> 10,
           ((u32)_text_end - (u32)_text_start) >> 10, ((u32)_rodata_end - (u32)_rodata_start) >> 10,
           ((u32)_data_end - (u32)_data_start) >> 10, ((u32)_bss_end - (u32)_bss_start) >> 10);
    printf("Heap     : 0x%08x - 0x%08x (%u KiB) used %u KiB, free %u KiB, peak %u KiB\n",
           heap_start, heap_end, (heap_end - heap_start) >> 10, heap_stats.bytes_used >> 10,
           heap_free_bytes() >> 10, heap_stats.peak >> 10);
    printf("           %u allocs, %u frees, integrity %s\n", heap_stats.allocs, heap_stats.frees,
           heap_check() ? "OK" : "BROKEN");
    printf("Frames   : %u x 4 KiB from 0x%08x, %u used\n", frame_count, frame_base, frames_used);
}
static void cmd_ps(void) {
    printf("  PID  STATE    TICKS   SWITCHES  NAME\n");
    task_t *t = current;
    for (int i = 0; i < MAX_TASKS; i++) {
        printf("  %3u  %-8s %6u  %8u  %s\n", t->pid, state_name(t->state), t->cpu_ticks, t->switches, t->name);
        t = t->next;
        if (t == current) break;
    }
    printf("  context switches: %u, background heartbeat: %u\n", context_switches, bg_counter);
}
static void cmd_cpuinfo(void) {
    printf("Vendor   : %s\n", boot.vendor);
    if (cpuid_available()) {
        u32 r[4];
        char brand[49]; brand[0] = 0;
        get_cpuid(0x80000000, r);
        if (r[0] >= 0x80000004) {
            for (u32 i = 0; i < 3; i++) { get_cpuid(0x80000002 + i, r); memcpy(brand + i * 16, r, 16); }
            brand[48] = 0;
            char *b = brand; while (*b == ' ') b++;
            printf("Brand    : %s\n", b);
        }
        get_cpuid(1, r);
        printf("Family   : %u model %u stepping %u\n", (r[0] >> 8) & 0xF, (r[0] >> 4) & 0xF, r[0] & 0xF);
        printf("Features :%s%s%s%s%s%s%s%s%s\n",
               (r[3] & (1u << 0))  ? " FPU"  : "", (r[3] & (1u << 4))  ? " TSC"   : "",
               (r[3] & (1u << 5))  ? " MSR"  : "", (r[3] & (1u << 9))  ? " APIC"  : "",
               (r[3] & (1u << 23)) ? " MMX"  : "", (r[3] & (1u << 25)) ? " SSE"   : "",
               (r[3] & (1u << 26)) ? " SSE2" : "", (r[2] & (1u << 0))  ? " SSE3"  : "",
               (r[2] & (1u << 28)) ? " AVX"  : "");
        get_cpuid(0x80000001, r);
        printf("Long mode: %s\n", (r[3] & (1u << 29)) ? "yes (x86-64 capable)" : "no");
    } else {
        print("CPUID    : not available\n");
    }
    if (cpu_mhz) printf("TSC rate : ~%u MHz\n", cpu_mhz);
    printf("CR0=0x%08x CR3=0x%08x CR4=0x%08x EFLAGS=0x%08x\n", get_cr0(), get_cr3(), get_cr4(), get_eflags());
}
static void cmd_heaptest(void) {
    void *p[16]; bool ok = true;
    for (int i = 0; i < 16; i++) { p[i] = kmalloc(64 * (i + 1)); if (!p[i]) ok = false; else memset(p[i], i, 64 * (i + 1)); }
    for (int i = 0; i < 16; i += 2) kfree(p[i]);
    void *big = kmalloc(4000);            /* must fit in coalesced space or tail */
    if (!big) ok = false;
    for (int i = 1; i < 16; i += 2) kfree(p[i]);
    kfree(big);
    void *al = kmalloc_aligned(100, 4096);
    if (!al || ((u32)al & 4095)) ok = false;
    kfree(al);
    u32 fr = alloc_frame(), fr2 = alloc_frame();
    if (!fr || !fr2 || fr == fr2 || (fr & 4095)) ok = false;
    free_frame(fr); free_frame(fr2);
    if (!heap_check()) ok = false;
    printf("heap self-test: %s (free %u KiB, frames used %u)\n", ok ? "PASS" : "FAIL", heap_free_bytes() >> 10, frames_used);
}
static void demo_thread(void) {
    u32 id = current->pid;
    for (u32 i = 1; i <= 3; i++) {
        printf("\n[thread %u] step %u/3", id, i);
        sleep_ms(400);
    }
    printf("\n[thread %u] done\n", id);
    shell_prompt();
}
static void cmd_spawn(int n) {
    if (n < 1) n = 1;
    if (n > 8) n = 8;
    for (int i = 0; i < n; i++) {
        task_t *t = task_create("demo", demo_thread);
        if (!t) { WARN("no free task slot\n"); break; }
        printf("spawned pid %u\n", t->pid);
    }
}
static void cmd_kill(u32 pid) {
    if (pid == 0) { print("cannot kill the kernel task\n"); return; }
    u32 f = irq_save();
    task_t *t = current->next;
    bool found = false;
    for (int i = 0; i < MAX_TASKS && t != current; i++, t = t->next)
        if (t->pid == pid && t->state != TASK_ZOMBIE) { t->state = TASK_ZOMBIE; found = true; break; }
    irq_restore(f);
    printf(found ? "killed pid %u\n" : "no such pid %u\n", pid);
}
static void cmd_syscall(void) {
    const char *msg = "hello from INT 0x80 write()\n";
    u32 n = do_syscall(SYSCALL_WRITE, 1, (u32)msg, strlen(msg));
    printf("write returned %u, getpid() = %u, uptime() = %u ms\n",
           n, do_syscall(SYSCALL_GETPID, 0, 0, 0), do_syscall(SYSCALL_UPTIME, 0, 0, 0));
}
static void cmd_drivers(void) {
    int n = driver_manager_count();
    printf("%d driver(s) registered:\n", n);
    for (int i = 0; i < n; i++) printf("  %d. %s\n", i + 1, driver_manager_name(i));
}
static void cmd_date(void) {
    rtc_datetime_t d;
    if (!driver_rtc_read(&d)) { print("RTC not available\n"); return; }
    printf("%04u-%02u-%02u %02u:%02u:%02u (CMOS RTC)\n", d.year, d.month, d.day, d.hour, d.minute, d.second);
}
static void cmd_disk(const char *arg) {
    if (!driver_manager_present(DRIVER_ATA)) { print("no ATA disk detected on the primary bus\n"); return; }
    u32 lba = *arg ? (u32)atoi_simple(arg) : 0;
    u8 *buf = kmalloc(512);
    if (!buf) { print("out of memory\n"); return; }
    printf("disk: %s, %u sectors (%u MiB)\n", driver_disk_model(), driver_disk_sector_count(),
           driver_disk_sector_count() / 2048);
    if (!driver_disk_read(lba, buf)) { printf("read of LBA %u failed\n", lba); kfree(buf); return; }
    printf("LBA %u, first 64 bytes:\n", lba);
    for (int row = 0; row < 4; row++) {
        printf("  %04x: ", row * 16);
        for (int i = 0; i < 16; i++) printf("%02x ", buf[row * 16 + i]);
        print(" ");
        for (int i = 0; i < 16; i++) { char c = (char)buf[row * 16 + i]; putchar((c >= 32 && c < 127) ? c : '.'); }
        putchar('\n');
    }
    if (lba == 0) printf("  boot signature: %02x%02x %s\n", buf[510], buf[511],
                         (buf[510] == 0x55 && buf[511] == 0xAA) ? "(valid)" : "(missing)");
    kfree(buf);
}
static void reboot(void) {
    disable_interrupts();
    u8 t = 0x02;
    while (t & 0x02) t = inb(0x64);
    outb(0x64, 0xFE);                    /* keyboard-controller reset */
    for (;;) halt();
}
static void shell_execute(char *line) {
    while (*line == ' ') line++;
    if (!*line) return;
    char *arg = line;
    while (*arg && *arg != ' ') arg++;
    if (*arg) { *arg++ = 0; while (*arg == ' ') arg++; }

    if (!strcmp(line, "help")) cmd_help();
    else if (!strcmp(line, "clear")) clear_screen();
    else if (!strcmp(line, "mem") || !strcmp(line, "meminfo")) cmd_mem();
    else if (!strcmp(line, "ps")) cmd_ps();
    else if (!strcmp(line, "cpuinfo")) cmd_cpuinfo();
    else if (!strcmp(line, "uptime")) { char b[9]; format_uptime(b); printf("up %s (%u ticks @ %u Hz)\n", b, ticks, PIT_HZ); }
    else if (!strcmp(line, "ticks")) printf("%u\n", ticks);
    else if (!strcmp(line, "echo")) { print(arg); putchar('\n'); }
    else if (!strcmp(line, "color")) { int c = atoi_simple(arg) & 15; set_color((u8)c, VGA_BLACK); printf("colour %d\n", c); }
    else if (!strcmp(line, "alloc")) {
        int n = atoi_simple(arg); if (n <= 0) n = 1024;
        void *p = kmalloc((size_t)n);
        printf("kmalloc(%d) = %p\n", n, p);
        if (p) { kfree(p); print("freed\n"); }
    }
    else if (!strcmp(line, "heaptest")) cmd_heaptest();
    else if (!strcmp(line, "spawn")) cmd_spawn(*arg ? atoi_simple(arg) : 1);
    else if (!strcmp(line, "kill")) cmd_kill((u32)atoi_simple(arg));
    else if (!strcmp(line, "syscall")) cmd_syscall();
    else if (!strcmp(line, "sleep")) { u32 ms = (u32)atoi_simple(arg); if (!ms) ms = 1000; sleep_ms(ms); printf("slept %u ms\n", ms); }
    else if (!strcmp(line, "bp")) __asm__ volatile("int3");
    else if (!strcmp(line, "crash")) { u32 r; __asm__ volatile("xorl %%ecx, %%ecx; divl %%ecx" : "=a"(r) : "a"(1) : "ecx", "edx"); printf("%u\n", r); }
    else if (!strcmp(line, "ud")) __asm__ volatile("ud2");
    else if (!strcmp(line, "drivers")) cmd_drivers();
    else if (!strcmp(line, "date")) cmd_date();
    else if (!strcmp(line, "disk")) cmd_disk(arg);
    else if (!strcmp(line, "reboot")) reboot();
    else if (!strcmp(line, "halt")) { print("halted.\n"); disable_interrupts(); for (;;) halt(); }
    else printf("unknown command '%s' (try 'help')\n", line);
}
static void shell_run(void) {
    char line[SHELL_LINE_MAX];
    u32 len = 0;
    shell_prompt();
    for (;;) {
        char c = kb_getc();
        if (c == '\n') {
            putchar('\n');
            line[len] = 0;
            shell_execute(line);
            len = 0;
            shell_prompt();
        } else if (c == '\b') {
            if (len) { len--; putchar('\b'); }
        } else if (c == 12) {                         /* Ctrl-L */
            clear_screen(); len = 0; shell_prompt();
        } else if (c == 3) {                          /* Ctrl-C */
            print("^C\n"); len = 0; shell_prompt();
        } else if (c >= 32 && c < 127 && len < SHELL_LINE_MAX - 1) {
            line[len++] = c;
            putchar(c);
        }
    }
}

/* ============================================================== startup ==== */
static void banner(void) {
    set_color(VGA_LIGHT_CYAN, VGA_BLACK);
    print("  __  __ _       _  ___  ____  \n"
          " |  \\/  (_)_ __ (_)/ _ \\/ ___| \n"
          " | |\\/| | | '_ \\| | | | \\___ \\ \n"
          " | |  | | | | | | | |_| |___) |\n"
          " |_|  |_|_|_| |_|_|\\___/|____/   v" KERNEL_VERSION "\n\n");
    set_color(VGA_LIGHT_GREY, VGA_BLACK);
}

static void measure_cpu(void) {
    if (!cpuid_available()) return;
    u32 r[4]; get_cpuid(1, r);
    if (!(r[3] & (1u << 4))) return;             /* no TSC */
    u32 t0 = ticks;
    while (ticks == t0) halt();
    u64 c0 = read_tsc();
    u32 t1 = ticks;
    while ((ticks - t1) < 5) halt();             /* 50 ms */
    u64 c1 = read_tsc();
    u64 d = c1 - c0;
    if (d >> 32) return;                          /* absurd; skip */
    cpu_mhz = (u32)d / 50000;
}

void kernel_main(u32 magic, void *info) {
    serial_init();
    set_color(VGA_LIGHT_GREY, VGA_BLACK);
    clear_screen();
    status_fill(make_color(VGA_BLACK, VGA_LIGHT_GREY));
    status_write(1, " MiniOS " KERNEL_VERSION " | F1: help  Ctrl-L: clear ", make_color(VGA_BLACK, VGA_LIGHT_GREY));
    banner();

    parse_boot_info(magic, info);
    LOG("BOOT", "%s, magic 0x%08x\n", boot.loader, magic);
    LOG("MEM ", "%u KiB low, %u KiB high, %u E820 entries, top 0x%08x\n",
        boot.mem_lower_kb, boot.mem_upper_kb, boot.e820_count, boot.phys_top);
    LOG("KRNL", "0x%08x - 0x%08x (%u KiB)\n", (u32)_kernel_start, (u32)_kernel_end,
        ((u32)_kernel_end - (u32)_kernel_start) >> 10);

    gdt_install();      OK("GDT loaded (5 entries)\n");
    idt_install();      OK("IDT loaded (32 exceptions, 16 IRQs, INT 0x80)\n");
    pic_remap();        OK("PIC remapped to vectors 32-47\n");
    pit_init(PIT_HZ);   OK("PIT at %u Hz\n", PIT_HZ);
    keyboard_init();    OK("PS/2 keyboard ready\n");

    /* heap directly after the kernel image, frames after the heap */
    u32 hs = ((u32)_kernel_end + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1);
    u32 avail = boot.phys_top > hs ? boot.phys_top - hs : 0;
    u32 hsize = avail / 2;
    if (hsize > HEAP_MAX_SIZE) hsize = HEAP_MAX_SIZE;
    if (hsize < HEAP_MIN_SIZE) hsize = avail < HEAP_MIN_SIZE ? avail : HEAP_MIN_SIZE;
    if (hsize < 64 * 1024) kernel_panic("not enough memory for the kernel heap", NULL);
    heap_init(hs, hs + hsize);
    OK("heap 0x%08x - 0x%08x (%u KiB)\n", heap_start, heap_end, hsize >> 10);
    frames_init(heap_end, boot.phys_top);
    OK("frame allocator: %u x 4 KiB frames (%u MiB)\n", frame_count, (frame_count * PAGE_SIZE) >> 20);

    if (driver_manager_init_rtc()) { rtc_datetime_t d; if (driver_rtc_read(&d))
        OK("RTC: %04u-%02u-%02u %02u:%02u:%02u\n", d.year, d.month, d.day, d.hour, d.minute, d.second); }
    if (driver_manager_init_disk())
        OK("ATA: %s (%u MiB)\n", driver_disk_model(), driver_disk_sector_count() / 2048);
    else
        WARN("ATA: no disk on primary master (PIO)\n");

    tasking_init();
    enable_interrupts();
    OK("interrupts enabled, preemptive scheduler on (quantum %u ticks)\n", QUANTUM_TICKS);

    measure_cpu();
    if (cpu_mhz) OK("CPU: %s ~%u MHz\n", boot.vendor, cpu_mhz);
    else         OK("CPU: %s\n", boot.vendor);

    task_create("status", status_task);
    OK("background status thread started\n");

    set_color(VGA_YELLOW, VGA_BLACK);
    print("\nSystem ready. Type 'help' for a list of commands.\n\n");
    set_color(VGA_LIGHT_GREY, VGA_BLACK);

    shell_run();
    for (;;) halt();
}

/* -------------------------------------------------------- stack protector -- */
u32 __stack_chk_guard = 0xDEADC0DE;
void __stack_chk_fail(void) { kernel_panic("stack smashing detected", NULL); }
