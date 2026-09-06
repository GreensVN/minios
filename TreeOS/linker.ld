/* linker.ld - MiniOS v4.1 kernel layout
 *
 * The kernel is linked at 1 MiB.  Both boot paths place it there:
 *   - Bootloader.asm copies kernel.bin (flat) to 0x00100000
 *   - GRUB loads kernel.elf via the Multiboot header in entry.asm
 *
 * kernel.bin must start with the header from entry.asm, so .text.boot is
 * forced to be first.  Only .text/.rodata/.data are in the file image;
 * .bss and the kernel stack are cleared/created at runtime by entry.asm.
 */
OUTPUT_FORMAT("elf32-i386")
OUTPUT_ARCH("i386")
ENTRY(_start)

KERNEL_BASE = 0x00100000;

SECTIONS
{
    . = KERNEL_BASE;
    _kernel_start = .;

    .text : ALIGN(4K) {
        _text_start = .;
        KEEP(*(.text.boot))         /* header + _start must come first */
        *(.text .text.*)
        _text_end = .;
    }

    .rodata : ALIGN(4K) {
        _rodata_start = .;
        *(.rodata .rodata.*)
        _rodata_end = .;
    }

    .data : ALIGN(4K) {
        _data_start = .;
        *(.data .data.*)
        _data_end = .;
    }
    _load_end = .;                  /* end of what is stored in kernel.bin */

    .bss (NOLOAD) : ALIGN(4K) {
        _bss_start = .;
        *(COMMON)
        *(.bss .bss.*)
        . = ALIGN(16);
        _stack_bottom = .;
        . += 32K;                   /* kernel stack */
        _stack_top = .;
        . = ALIGN(4K);
        _bss_end = .;
    }

    _kernel_end = .;
    _kernel_size = _kernel_end - _kernel_start;

    /DISCARD/ : {
        *(.comment)
        *(.eh_frame)
        *(.eh_frame_hdr)
        *(.note.gnu.build-id)
        *(.note.GNU-stack)
        *(.gcc_except_table)
        *(.rel.*)
        *(.rela.*)
    }
}

ASSERT(_kernel_start == KERNEL_BASE, "kernel must be linked at 1 MiB")
ASSERT(_load_end - _kernel_start <= 448K, "kernel image too large for the bootloader (448 KiB)")
