// kernel_v4_ultimate.c - MiniOS v4.0 ULTIMATE Complete Kernel
// Compile: gcc -m32 -c kernel_v4_ultimate.c -o kernel.o -ffreestanding -fno-pie -O2 -Wall -Wextra

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

// ========== Type Definitions ==========
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef int8_t i8;
typedef int16_t i16;
typedef int32_t i32;
typedef int64_t i64;

// ========== Magic Numbers ==========
__attribute__((section(".text.boot")))
const u32 kernel_magic = 0xDEADBEEF;
const u32 kernel_version = 0x00040000; // v4.0.0

// ========== VGA & Graphics ==========
#define VGA_MEMORY ((volatile u16*)0xB8000)
#define VGA_WIDTH 80
#define VGA_HEIGHT 25
#define VGA_CTRL_REG 0x3D4
#define VGA_DATA_REG 0x3D5

enum vga_color {
    VGA_BLACK = 0, VGA_BLUE = 1, VGA_GREEN = 2, VGA_CYAN = 3,
    VGA_RED = 4, VGA_MAGENTA = 5, VGA_BROWN = 6, VGA_LIGHT_GREY = 7,
    VGA_DARK_GREY = 8, VGA_LIGHT_BLUE = 9, VGA_LIGHT_GREEN = 10,
    VGA_LIGHT_CYAN = 11, VGA_LIGHT_RED = 12, VGA_LIGHT_MAGENTA = 13,
    VGA_YELLOW = 14, VGA_WHITE = 15
};

// ========== Memory Management ==========
#define PAGE_SIZE 4096
#define HEAP_START 0x00400000
#define HEAP_SIZE (32 * 1024 * 1024)  // 32MB heap
#define MAX_MEMORY_BLOCKS 16384
#define KERNEL_STACK_SIZE 16384

typedef struct {
    void *address;
    size_t size;
    bool used;
    u32 magic;
    struct memory_block *next;
    struct memory_block *prev;
} memory_block_t;

typedef struct {
    u32 *bitmap;
    u32 total_frames;
    u32 used_frames;
    u32 free_frames;
    u32 first_free;
} page_frame_allocator_t;

typedef struct {
    u32 *page_directory;
    u32 *page_tables[1024];
    u32 mapped_pages;
} virtual_memory_t;

// ========== Process Management ==========
#define MAX_PROCESSES 256
#define PROCESS_NAME_LEN 64
#define MAX_FILE_DESCRIPTORS 64
#define QUANTUM_MS 20

typedef enum {
    PROC_STATE_NEW,
    PROC_STATE_READY,
    PROC_STATE_RUNNING,
    PROC_STATE_BLOCKED,
    PROC_STATE_WAITING,
    PROC_STATE_ZOMBIE,
    PROC_STATE_TERMINATED
} process_state_t;

typedef struct {
    u32 eax, ebx, ecx, edx;
    u32 esi, edi, ebp, esp;
    u32 eip, eflags;
    u32 cs, ds, es, fs, gs, ss;
    u32 cr3;
} registers_t;

typedef struct process {
    u32 pid;
    u32 ppid;
    char name[PROCESS_NAME_LEN];
    process_state_t state;
    i32 priority;
    i32 nice;
    u32 quantum;
    u64 cpu_time;
    u64 start_time;
    u64 sleep_until;
    registers_t regs;
    void *kernel_stack;
    void *user_stack;
    u32 *page_directory;
    struct process *parent;
    struct process *next;
    struct process *prev;
    struct process *children;
    u32 exit_code;
    void *heap_start;
    void *heap_end;
    u32 uid, gid;
    u32 open_files[MAX_FILE_DESCRIPTORS];
    char cwd[256];
    u32 signals_pending;
    u32 signals_blocked;
} process_t;

// ========== Interrupt Handling ==========
#define IDT_ENTRIES 256
#define PIC1_COMMAND 0x20
#define PIC1_DATA 0x21
#define PIC2_COMMAND 0xA0
#define PIC2_DATA 0xA1

typedef struct {
    u16 base_low;
    u16 selector;
    u8 always0;
    u8 flags;
    u16 base_high;
} __attribute__((packed)) idt_entry_t;

typedef struct {
    u16 limit;
    u32 base;
} __attribute__((packed)) idt_ptr_t;

typedef struct {
    u32 ds;
    u32 edi, esi, ebp, esp, ebx, edx, ecx, eax;
    u32 int_no, err_code;
    u32 eip, cs, eflags, useresp, ss;
} __attribute__((packed)) interrupt_frame_t;

// ========== System Calls ==========
#define SYSCALL_EXIT 1
#define SYSCALL_FORK 2
#define SYSCALL_READ 3
#define SYSCALL_WRITE 4
#define SYSCALL_OPEN 5
#define SYSCALL_CLOSE 6
#define SYSCALL_WAIT 7
#define SYSCALL_EXEC 8
#define SYSCALL_GETPID 9
#define SYSCALL_SLEEP 10
#define SYSCALL_YIELD 11
#define SYSCALL_KILL 12
#define SYSCALL_SIGNAL 13
#define SYSCALL_MMAP 14
#define SYSCALL_MUNMAP 15
#define SYSCALL_BRK 16

// ========== Global Variables ==========
static volatile u16 *vga_buffer = VGA_MEMORY;
static u8 cursor_x = 0;
static u8 cursor_y = 0;
static u8 current_color = 0x0F;

static u8 *heap_start = (u8*)HEAP_START;
static memory_block_t *memory_blocks_head = NULL;
static size_t total_allocated = 0;
static size_t allocation_count = 0;

static process_t *process_list[MAX_PROCESSES] = {NULL};
static process_t *current_process = NULL;
static process_t *idle_process = NULL;
static process_t *ready_queue = NULL;
static u32 next_pid = 1;
static volatile u64 system_ticks = 0;
static volatile u64 system_time_ms = 0;

static idt_entry_t idt[IDT_ENTRIES];
static idt_ptr_t idt_ptr;

static page_frame_allocator_t frame_allocator;
static virtual_memory_t kernel_vm;

static u8 keyboard_buffer[256];
static volatile int kb_read_pos = 0;
static volatile int kb_write_pos = 0;
static bool shift_pressed = false;
static bool ctrl_pressed = false;
static bool alt_pressed = false;
static bool caps_lock = false;

// Statistics
static struct {
    u64 context_switches;
    u64 interrupts_handled;
    u64 page_faults;
    u64 syscalls;
    u64 memory_allocations;
    u64 memory_frees;
    u64 kernel_time;
    u64 user_time;
} kernel_stats = {0};

// ========== Port I/O ==========
static inline void outb(u16 port, u8 val) {
    __asm__ volatile("outb %0, %1" : : "a"(val), "Nd"(port));
}

static inline u8 inb(u16 port) {
    u8 ret;
    __asm__ volatile("inb %1, %0" : "=a"(ret) : "Nd"(port));
    return ret;
}

static inline void outw(u16 port, u16 val) {
    __asm__ volatile("outw %0, %1" : : "a"(val), "Nd"(port));
}

static inline u16 inw(u16 port) {
    u16 ret;
    __asm__ volatile("inw %1, %0" : "=a"(ret) : "Nd"(port));
    return ret;
}

static inline void outl(u16 port, u32 val) {
    __asm__ volatile("outl %0, %1" : : "a"(val), "Nd"(port));
}

static inline u32 inl(u16 port) {
    u32 ret;
    __asm__ volatile("inl %1, %0" : "=a"(ret) : "Nd"(port));
    return ret;
}

static inline void io_wait(void) {
    outb(0x80, 0);
}

// ========== String Functions ==========
void *memset(void *dest, int val, size_t len) {
    u8 *ptr = (u8*)dest;
    while (len--) *ptr++ = val;
    return dest;
}

void *memcpy(void *dest, const void *src, size_t len) {
    u8 *d = (u8*)dest;
    const u8 *s = (const u8*)src;
    while (len--) *d++ = *s++;
    return dest;
}

void *memmove(void *dest, const void *src, size_t len) {
    u8 *d = (u8*)dest;
    const u8 *s = (const u8*)src;
    if (d < s) {
        while (len--) *d++ = *s++;
    } else {
        d += len; s += len;
        while (len--) *--d = *--s;
    }
    return dest;
}

int memcmp(const void *s1, const void *s2, size_t n) {
    const u8 *p1 = s1, *p2 = s2;
    while (n--) {
        if (*p1 != *p2) return *p1 - *p2;
        p1++; p2++;
    }
    return 0;
}

size_t strlen(const char *str) {
    size_t len = 0;
    while (str[len]) len++;
    return len;
}

int strcmp(const char *s1, const char *s2) {
    while (*s1 && (*s1 == *s2)) { s1++; s2++; }
    return *(const u8*)s1 - *(const u8*)s2;
}

char *strcpy(char *dest, const char *src) {
    char *ret = dest;
    while ((*dest++ = *src++));
    return ret;
}

char *strcat(char *dest, const char *src) {
    char *ret = dest;
    while (*dest) dest++;
    while ((*dest++ = *src++));
    return ret;
}

// ========== VGA Functions ==========
static inline u8 vga_entry_color(enum vga_color fg, enum vga_color bg) {
    return fg | bg << 4;
}

static inline u16 vga_entry(u8 c, u8 color) {
    return (u16)c | (u16)color << 8;
}

void set_color(enum vga_color fg, enum vga_color bg) {
    current_color = vga_entry_color(fg, bg);
}

void clear_screen(void) {
    for (size_t i = 0; i < VGA_WIDTH * VGA_HEIGHT; i++)
        vga_buffer[i] = vga_entry(' ', current_color);
    cursor_x = 0;
    cursor_y = 0;
}

void scroll(void) {
    for (size_t y = 0; y < VGA_HEIGHT - 1; y++) {
        for (size_t x = 0; x < VGA_WIDTH; x++) {
            vga_buffer[y * VGA_WIDTH + x] = vga_buffer[(y + 1) * VGA_WIDTH + x];
        }
    }
    for (size_t x = 0; x < VGA_WIDTH; x++) {
        vga_buffer[(VGA_HEIGHT - 1) * VGA_WIDTH + x] = vga_entry(' ', current_color);
    }
    cursor_y = VGA_HEIGHT - 1;
}

void update_cursor(void) {
    u16 pos = cursor_y * VGA_WIDTH + cursor_x;
    outb(VGA_CTRL_REG, 0x0F);
    outb(VGA_DATA_REG, (u8)(pos & 0xFF));
    outb(VGA_CTRL_REG, 0x0E);
    outb(VGA_DATA_REG, (u8)((pos >> 8) & 0xFF));
}

void putchar(char c) {
    if (c == '\n') {
        cursor_x = 0;
        cursor_y++;
    } else if (c == '\r') {
        cursor_x = 0;
    } else if (c == '\t') {
        cursor_x = (cursor_x + 8) & ~7;
    } else if (c == '\b') {
        if (cursor_x > 0) {
            cursor_x--;
            vga_buffer[cursor_y * VGA_WIDTH + cursor_x] = vga_entry(' ', current_color);
        }
    } else {
        vga_buffer[cursor_y * VGA_WIDTH + cursor_x] = vga_entry(c, current_color);
        cursor_x++;
    }
    
    if (cursor_x >= VGA_WIDTH) {
        cursor_x = 0;
        cursor_y++;
    }
    
    if (cursor_y >= VGA_HEIGHT) scroll();
    update_cursor();
}

void print(const char *str) {
    while (*str) putchar(*str++);
}

void print_hex(u32 n) {
    char hex[] = "0123456789ABCDEF";
    print("0x");
    for (int i = 28; i >= 0; i -= 4)
        putchar(hex[(n >> i) & 0xF]);
}

void print_dec(u32 n) {
    if (n == 0) { putchar('0'); return; }
    char buffer[12];
    int i = 0;
    while (n > 0) {
        buffer[i++] = '0' + (n % 10);
        n /= 10;
    }
    while (i > 0) putchar(buffer[--i]);
}

void printf(const char *fmt, ...) {
    __builtin_va_list args;
    __builtin_va_start(args, fmt);
    
    while (*fmt) {
        if (*fmt == '%') {
            fmt++;
            switch (*fmt) {
                case 'd': case 'i': {
                    int val = __builtin_va_arg(args, int);
                    if (val < 0) { putchar('-'); val = -val; }
                    print_dec(val);
                    break;
                }
                case 'u': print_dec(__builtin_va_arg(args, unsigned int)); break;
                case 'x': case 'X': print_hex(__builtin_va_arg(args, unsigned int)); break;
                case 'c': putchar(__builtin_va_arg(args, int)); break;
                case 's': print(__builtin_va_arg(args, const char*)); break;
                case '%': putchar('%'); break;
                default: putchar('%'); putchar(*fmt); break;
            }
        } else {
            putchar(*fmt);
        }
        fmt++;
    }
    
    __builtin_va_end(args);
}

// ========== Memory Management ==========
void init_memory(void) {
    memory_blocks_head = NULL;
    total_allocated = 0;
    allocation_count = 0;
    
    printf("[MEM] Initializing memory manager...\n");
    printf("[MEM] Heap at 0x%x - 0x%x (%d MB)\n", 
           HEAP_START, HEAP_START + HEAP_SIZE, HEAP_SIZE / (1024*1024));
}

void *kmalloc_aligned(size_t size, u32 alignment) {
    if (size == 0) return NULL;
    
    size = (size + alignment - 1) & ~(alignment - 1);
    size += sizeof(memory_block_t);
    
    memory_block_t *block = memory_blocks_head;
    memory_block_t *prev = NULL;
    
    while (block) {
        if (!block->used && block->size >= size) {
            if (block->size > size + sizeof(memory_block_t) + 64) {
                memory_block_t *new_block = (memory_block_t*)((u8*)block + size);
                new_block->address = (u8*)new_block + sizeof(memory_block_t);
                new_block->size = block->size - size;
                new_block->used = false;
                new_block->magic = 0xDEADBEEF;
                new_block->next = block->next;
                new_block->prev = block;
                
                if (block->next) block->next->prev = new_block;
                block->next = new_block;
                block->size = size;
            }
            
            block->used = true;
            total_allocated += block->size;
            allocation_count++;
            kernel_stats.memory_allocations++;
            
            return block->address;
        }
        prev = block;
        block = block->next;
    }
    
    if (total_allocated + size > HEAP_SIZE) return NULL;
    
    block = (memory_block_t*)((u8*)heap_start + total_allocated);
    block->address = (u8*)block + sizeof(memory_block_t);
    block->size = size;
    block->used = true;
    block->magic = 0xDEADBEEF;
    block->next = NULL;
    block->prev = prev;
    
    if (prev) prev->next = block;
    else memory_blocks_head = block;
    
    total_allocated += size;
    allocation_count++;
    kernel_stats.memory_allocations++;
    
    return block->address;
}

void *kmalloc(size_t size) {
    return kmalloc_aligned(size, 16);
}

void *kcalloc(size_t nmemb, size_t size) {
    size_t total = nmemb * size;
    void *ptr = kmalloc(total);
    if (ptr) memset(ptr, 0, total);
    return ptr;
}

void kfree(void *ptr) {
    if (!ptr) return;
    
    memory_block_t *block = (memory_block_t*)((u8*)ptr - sizeof(memory_block_t));
    if (block->magic != 0xDEADBEEF) {
        printf("[MEM] Invalid free: magic mismatch at %x\n", ptr);
        return;
    }
    
    block->used = false;
    kernel_stats.memory_frees++;
    
    if (block->next && !block->next->used) {
        block->size += block->next->size;
        block->next = block->next->next;
        if (block->next) block->next->prev = block;
    }
    
    if (block->prev && !block->prev->used) {
        block->prev->size += block->size;
        block->prev->next = block->next;
        if (block->next) block->next->prev = block->prev;
    }
}

// ========== Paging ==========
void init_paging(void) {
    printf("[MEM] Initializing paging...\n");
    
    frame_allocator.total_frames = (128 * 1024 * 1024) / PAGE_SIZE;
    frame_allocator.used_frames = 0;
    frame_allocator.free_frames = frame_allocator.total_frames;
    frame_allocator.first_free = 0;
    
    u32 bitmap_size = (frame_allocator.total_frames + 31) / 32;
    frame_allocator.bitmap = (u32*)kmalloc(bitmap_size * sizeof(u32));
    memset(frame_allocator.bitmap, 0, bitmap_size * sizeof(u32));
    
    kernel_vm.page_directory = (u32*)kmalloc_aligned(PAGE_SIZE, PAGE_SIZE);
    memset(kernel_vm.page_directory, 0, PAGE_SIZE);
    kernel_vm.mapped_pages = 0;
    
    printf("[MEM] Paging initialized: %d frames\n", frame_allocator.total_frames);
}

u32 alloc_frame(void) {
    for (u32 i = frame_allocator.first_free; i < frame_allocator.total_frames; i++) {
        u32 idx = i / 32;
        u32 bit = i % 32;
        
        if (!(frame_allocator.bitmap[idx] & (1 << bit))) {
            frame_allocator.bitmap[idx] |= (1 << bit);
            frame_allocator.used_frames++;
            frame_allocator.free_frames--;
            frame_allocator.first_free = i + 1;
            return i * PAGE_SIZE;
        }
    }
    return 0;
}

void free_frame(u32 frame) {
    u32 i = frame / PAGE_SIZE;
    u32 idx = i / 32;
    u32 bit = i % 32;
    
    if (frame_allocator.bitmap[idx] & (1 << bit)) {
        frame_allocator.bitmap[idx] &= ~(1 << bit);
        frame_allocator.used_frames--;
        frame_allocator.free_frames++;
        if (i < frame_allocator.first_free) frame_allocator.first_free = i;
    }
}

// ========== IDT Setup ==========
void idt_set_gate(u8 num, u32 base, u16 sel, u8 flags) {
    idt[num].base_low = base & 0xFFFF;
    idt[num].base_high = (base >> 16) & 0xFFFF;
    idt[num].selector = sel;
    idt[num].always0 = 0;
    idt[num].flags = flags;
}

extern void isr0(void), isr1(void), isr2(void), isr3(void);
extern void isr4(void), isr5(void), isr6(void), isr7(void);
extern void isr8(void), isr9(void), isr10(void), isr11(void);
extern void isr12(void), isr13(void), isr14(void), isr15(void);
extern void isr16(void), isr17(void), isr18(void), isr19(void);
extern void irq0(void), irq1(void), irq2(void), irq3(void);
extern void irq4(void), irq5(void), irq6(void), irq7(void);

void idt_install(void) {
    idt_ptr.limit = sizeof(idt) - 1;
    idt_ptr.base = (u32)&idt;
    
    memset(&idt, 0, sizeof(idt));
    
    // Install ISRs
    idt_set_gate(0, (u32)isr0, 0x08, 0x8E);
    idt_set_gate(1, (u32)isr1, 0x08, 0x8E);
    idt_set_gate(13, (u32)isr13, 0x08, 0x8E);
    idt_set_gate(14, (u32)isr14, 0x08, 0x8E);
    
    // Install IRQs
    idt_set_gate(32, (u32)irq0, 0x08, 0x8E);
    idt_set_gate(33, (u32)irq1, 0x08, 0x8E);
    
    __asm__ volatile("lidt %0" : : "m"(idt_ptr));
    
    printf("[IDT] Installed %d entries\n", IDT_ENTRIES);
}

// ========== PIC Remap ==========
void pic_remap(void) {
    outb(PIC1_COMMAND, 0x11);
    io_wait();
    outb(PIC2_COMMAND, 0x11);
    io_wait();
    
    outb(PIC1_DATA, 0x20);
    io_wait();
    outb(PIC2_DATA, 0x28);
    io_wait();
    
    outb(PIC1_DATA, 0x04);
    io_wait();
    outb(PIC2_DATA, 0x02);
    io_wait();
    
    outb(PIC1_DATA, 0x01);
    io_wait();
    outb(PIC2_DATA, 0x01);
    io_wait();
    
    outb(PIC1_DATA, 0xFD);
    outb(PIC2_DATA, 0xFF);
    
    printf("[PIC] Remapped to 0x20-0x2F\n");
}

// ========== Timer ==========
void timer_install(void) {
    u32 divisor = 1193180 / 100; // 100 Hz
    outb(0x43, 0x36);
    outb(0x40, divisor & 0xFF);
    outb(0x40, (divisor >> 8) & 0xFF);
    
    printf("[TMR] Initialized at 100 Hz\n");
}

void timer_handler(interrupt_frame_t *frame) {
    system_ticks++;
    system_time_ms = system_ticks * 10;
    kernel_stats.interrupts_handled++;
    
    if (current_process) {
        current_process->cpu_time++;
        if (--current_process->quantum == 0) {
            // Time slice expired
            schedule();
        }
    }
    
    outb(PIC1_COMMAND, 0x20);
}

// ========== Keyboard ==========
static const char scancode_to_ascii[] = {
    0, 0, '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '=', '\b',
    '\t', 'q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', '[', ']', '\n',
    0, 'a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', ';', '\'', '`',
    0, '\\', 'z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '/', 0, '*',
    0, ' '
};

void keyboard_handler(interrupt_frame_t *frame) {
    u8 scancode = inb(0x60);
    
    if (scancode < 128 && scancode < sizeof(scancode_to_ascii)) {
        char c = scancode_to_ascii[scancode];
        if (c) {
            keyboard_buffer[kb_write_pos] = c;
            kb_write_pos = (kb_write_pos + 1) % 256;
            putchar(c);
        }
    }
    
    kernel_stats.interrupts_handled++;
    outb(PIC1_COMMAND, 0x20);
}

// ========== Process Management ==========
void init_tasking(void) {
    printf("[TASK] Initializing multitasking...\n");
    
    idle_process = (process_t*)kmalloc(sizeof(process_t));
    memset(idle_process, 0, sizeof(process_t));
    idle_process->pid = 0;
    idle_process->state = PROC_STATE_RUNNING;
    strcpy(idle_process->name, "idle");
    
    current_process = idle_process;
    process_list[0] = idle_process;
    
    printf("[TASK] Created idle process (PID 0)\n");
}

void schedule(void) {
    if (!current_process) return;
    
    kernel_stats.context_switches++;
    
    // Simple round-robin scheduler
    process_t *next = current_process->next;
    if (!next) next = process_list[0];
    
    while (next && next->state != PROC_STATE_READY && next->state != PROC_STATE_RUNNING) {
        next = next->next;
        if (!next) next = process_list[0];
        if (next == current_process) break;
    }
    
    if (next && next != current_process) {
        process_t *prev = current_process;
        if (prev->state == PROC_STATE_RUNNING) prev->state = PROC_STATE_READY;
        
        current_process = next;
        current_process->state = PROC_STATE_RUNNING;
        current_process->quantum = QUANTUM_MS;
        
        // TODO: Switch page directory
        // switch_context(&prev->regs, &next->regs);
    }
}

// ========== System Call Handler ==========
u32 syscall_handler(u32 syscall_num, u32 arg1, u32 arg2, u32 arg3, u32 arg4) {
    kernel_stats.syscalls++;
    
    switch (syscall_num) {
        case SYSCALL_EXIT:
            if (current_process) {
                current_process->state = PROC_STATE_TERMINATED;
                current_process->exit_code = arg1;
                schedule();
            }
            return 0;
            
        case SYSCALL_GETPID:
            return current_process ? current_process->pid : 0;
            
        case SYSCALL_WRITE:
            if (arg1 == 1) { // stdout
                const char *str = (const char*)arg2;
                for (u32 i = 0; i < arg3; i++) putchar(str[i]);
                return arg3;
            }
            return -1;
            
        case SYSCALL_YIELD:
            schedule();
            return 0;
            
        default:
            printf("[SYSCALL] Unknown: %d\n", syscall_num);
            return -1;
    }
}

// ========== Exception Handlers ==========
void exception_handler(interrupt_frame_t *frame) {
    set_color(VGA_WHITE, VGA_RED);
    printf("\n\n!!! KERNEL PANIC !!!\n");
    printf("Exception %d at EIP: 0x%x\n", frame->int_no, frame->eip);
    printf("Error Code: 0x%x\n", frame->err_code);
    printf("EAX: 0x%x  EBX: 0x%x  ECX: 0x%x  EDX: 0x%x\n",
           frame->eax, frame->ebx, frame->ecx, frame->edx);
    printf("ESI: 0x%x  EDI: 0x%x  EBP: 0x%x  ESP: 0x%x\n",
           frame->esi, frame->edi, frame->ebp, frame->esp);
    
    __asm__ volatile("cli; hlt");
    while(1);
}

void page_fault_handler(interrupt_frame_t *frame) {
    u32 faulting_address;
    __asm__ volatile("mov %%cr2, %0" : "=r" (faulting_address));
    
    kernel_stats.page_faults++;
    
    printf("\n[PAGE FAULT] at 0x%x\n", faulting_address);
    printf("Error code: 0x%x (", frame->err_code);
    if (!(frame->err_code & 0x1)) printf("not ");
    printf("present, ");
    if (frame->err_code & 0x2) printf("write, ");
    else printf("read, ");
    if (frame->err_code & 0x4) printf("user");
    else printf("kernel");
    printf(")\n");
    
    // TODO: Handle page fault properly
    exception_handler(frame);
}

// ========== Interrupt Dispatcher ==========
void isr_handler(interrupt_frame_t *frame) {
    if (frame->int_no == 14) {
        page_fault_handler(frame);
    } else if (frame->int_no == 13) {
        printf("\n[GPF] General Protection Fault at 0x%x\n", frame->eip);
        exception_handler(frame);
    } else {
        exception_handler(frame);
    }
}

void irq_handler(interrupt_frame_t *frame) {
    if (frame->int_no == 32) {
        timer_handler(frame);
    } else if (frame->int_no == 33) {
        keyboard_handler(frame);
    } else {
        kernel_stats.interrupts_handled++;
        outb(PIC1_COMMAND, 0x20);
        if (frame->int_no >= 40) outb(PIC2_COMMAND, 0x20);
    }
}

// ========== Main Kernel Entry ==========
void kernel_main(void) {
    clear_screen();
    
    set_color(VGA_LIGHT_CYAN, VGA_BLACK);
    print("================================================================\n");
    print("           MiniOS v4.0 ULTIMATE Kernel - Complete            \n");
    print("================================================================\n\n");
    
    set_color(VGA_LIGHT_GREEN, VGA_BLACK);
    print("[*] Kernel started at 0x");
    print_hex((u32)kernel_main);
    print("\n");
    
    init_memory();
    init_paging();
    
    print("[*] Installing IDT...\n");
    idt_install();
    
    print("[*] Remapping PIC...\n");
    pic_remap();
    
    print("[*] Installing timer...\n");
    timer_install();
    
    print("[*] Initializing multitasking...\n");
    init_tasking();
    
    print("[*] Enabling interrupts...\n");
    __asm__ volatile("sti");
    
    set_color(VGA_YELLOW, VGA_BLACK);
    print("\n=== System Ready ===\n");
    print("Press any key to interact...\n\n");
    
    set_color(VGA_WHITE, VGA_BLACK);
    
    // Main kernel loop
    while (1) {
        __asm__ volatile("hlt");
        
        if (kb_read_pos != kb_write_pos) {
            char c = keyboard_buffer[kb_read_pos];
            kb_read_pos = (kb_read_pos + 1) % 256;
        }
    }
}

// Stack protection
void __stack_chk_fail(void) {
    set_color(VGA_WHITE, VGA_RED);
    print("\n[PANIC] Stack smashing detected!\n");
    __asm__ volatile("cli; hlt");
    while(1);
}

void *__stack_chk_guard = (void*)0xDEADBEEF;