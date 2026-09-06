/* kernel.h - shared kernel definitions for MiniOS v4.1 */
#ifndef MINIOS_KERNEL_H
#define MINIOS_KERNEL_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

typedef uint8_t  u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef int8_t   i8;
typedef int16_t  i16;
typedef int32_t  i32;
typedef int64_t  i64;

/* ------------------------------------------------------------------ boot -- */
#define BOOT_MAGIC_MINIOS    0x4D494E49u   /* 'MINI' – Bootloader.asm       */
#define BOOT_MAGIC_MULTIBOOT 0x2BADB002u   /* GRUB / Multiboot 1            */

/* Handed over by Bootloader.asm in EBX (keep in sync with `boot_info:`). */
typedef struct {
    u32 magic;
    u32 drive;
    u32 mem_lower;      /* KiB below 1 MiB               */
    u32 mem_upper;      /* usable KiB above 1 MiB        */
    u32 e820_count;
    u32 e820_addr;      /* physical address of the entries */
    u32 cpu_flags;      /* bit0 CPUID, bit1 SSE, bit2 SSE2, bit3 AVX, bit4 LM */
    char vendor[13];
    u8  _pad[3];
} __attribute__((packed)) boot_info_t;

typedef struct {
    u64 base;
    u64 length;
    u32 type;           /* 1 = usable RAM */
    u32 acpi;
} __attribute__((packed)) e820_entry_t;

/* Subset of the Multiboot 1 info structure we care about. */
typedef struct {
    u32 flags;
    u32 mem_lower;
    u32 mem_upper;
    u32 boot_device;
    u32 cmdline;
    u32 mods_count;
    u32 mods_addr;
    u32 syms[4];
    u32 mmap_length;
    u32 mmap_addr;
} __attribute__((packed)) multiboot_info_t;

typedef struct {
    u32 size;
    u64 base;
    u64 length;
    u32 type;
} __attribute__((packed)) multiboot_mmap_t;

/* ------------------------------------------------------------ interrupts -- */
typedef struct {
    u32 gs, fs, es, ds;
    u32 edi, esi, ebp, esp, ebx, edx, ecx, eax;
    u32 int_no, err_code;
    u32 eip, cs, eflags, useresp, ss;
} __attribute__((packed)) interrupt_frame_t;

typedef struct {
    u16 base_low;
    u16 selector;
    u8  always0;
    u8  flags;
    u16 base_high;
} __attribute__((packed)) idt_entry_t;

typedef struct {
    u16 limit;
    u32 base;
} __attribute__((packed)) idt_ptr_t;

/* ------------------------------------------------------- linker symbols -- */
extern u8 _kernel_start[], _kernel_end[];
extern u8 _text_start[], _text_end[];
extern u8 _rodata_start[], _rodata_end[];
extern u8 _data_start[], _data_end[];
extern u8 _bss_start[], _bss_end[];
extern u8 _stack_bottom[], _stack_top[];
extern u8 _load_end[];

/* --------------------------------------------- provided by interrupts.asm - */
typedef struct { u32 esp; } cpu_context_t;

void switch_context(cpu_context_t *old, cpu_context_t *new_ctx);
u32  atomic_increment(volatile u32 *p);
u32  atomic_decrement(volatile u32 *p);
u32  atomic_exchange(volatile u32 *p, u32 v);
u32  atomic_compare_exchange(volatile u32 *p, u32 expected, u32 desired);
void spinlock_acquire(volatile u32 *lock);
void spinlock_release(volatile u32 *lock);
void enable_interrupts(void);
void disable_interrupts(void);
void halt(void);
u32  get_eflags(void);
void set_eflags(u32 f);
u32  cpuid_available(void);
void get_cpuid(u32 leaf, u32 out[4]);
u64  read_tsc(void);
u32  get_cr0(void); void set_cr0(u32);
u32  get_cr2(void);
u32  get_cr3(void); void set_cr3(u32);
u32  get_cr4(void); void set_cr4(u32);
void flush_tlb(void);
void flush_tlb_single(u32 addr);
void load_idt(idt_ptr_t *p);
void fast_memcpy(void *d, const void *s, u32 n);
void fast_memset(void *d, u8 v, u32 n);

/* ---------------------------------------------------------- Kernel.c API -- */
void  kernel_main(u32 magic, void *info) __attribute__((noreturn));
void  kernel_panic(const char *msg, interrupt_frame_t *frame) __attribute__((noreturn));

void *kmalloc(size_t size);
void *kmalloc_aligned(size_t size, u32 alignment);
void *kcalloc(size_t nmemb, size_t size);
void *krealloc(void *ptr, size_t size);
void  kfree(void *ptr);

void  putchar(char c);
void  print(const char *s);
void  printf(const char *fmt, ...);
void  set_color(u8 fg, u8 bg);
void  clear_screen(void);

void *memset(void *dest, int val, size_t len);
void *memcpy(void *dest, const void *src, size_t len);
void *memmove(void *dest, const void *src, size_t len);
int   memcmp(const void *a, const void *b, size_t n);
size_t strlen(const char *s);
int   strcmp(const char *a, const char *b);
int   strncmp(const char *a, const char *b, size_t n);
char *strcpy(char *d, const char *s);
char *strncpy(char *d, const char *s, size_t n);
char *strcat(char *d, const char *s);
char *strchr(const char *s, int c);

/* -------------------------------------------------------------- syscalls -- */
enum {
    SYSCALL_EXIT = 1, SYSCALL_FORK, SYSCALL_READ, SYSCALL_WRITE, SYSCALL_OPEN,
    SYSCALL_CLOSE, SYSCALL_WAIT, SYSCALL_EXEC, SYSCALL_GETPID, SYSCALL_SLEEP,
    SYSCALL_YIELD, SYSCALL_KILL, SYSCALL_SIGNAL, SYSCALL_MMAP, SYSCALL_MUNMAP,
    SYSCALL_BRK, SYSCALL_UPTIME, SYSCALL_COUNT
};

#endif /* MINIOS_KERNEL_H */
