ENTRY(_start)
OUTPUT_FORMAT(elf32-i386)

SECTIONS
{
    . = 1M;

    .text : ALIGN(4K) {
        KEEP(*(.multiboot))
        *(.text.boot)
        *(.text .text.*)
    }
    .rodata : ALIGN(4K) { *(.rodata .rodata.*) }
    .data   : ALIGN(4K) { *(.data .data.*) }
    .bss    : ALIGN(4K) {
        _bss_start = .;
        *(COMMON)
        *(.bss .bss.*)
        _bss_end = .;
    }
    .stack  : ALIGN(16) { *(.stack) }

    /DISCARD/ : { *(.comment) *(.note.gnu.build-id) *(.eh_frame) }
}
