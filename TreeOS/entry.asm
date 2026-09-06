; =============================================================================
;  entry.asm - kernel entry point (first bytes of kernel.bin / kernel.elf)
;
;  Image header (read by Bootloader.asm from the first kernel sector):
;     +0   jmp _start32
;     +8   dd 0xDEADBEEF        kernel magic
;     +12  dd version           0x00MMmmpp
;     +16  dd _load_end         physical end of the loaded image (.data end)
;     +20  dd _bss_end          physical end incl. .bss (memory footprint)
;     +24  Multiboot 1 header   (so kernel.elf can also be booted by GRUB)
;
;  Both boot paths enter at _start32 in 32-bit protected mode with:
;     EAX = boot magic  (0x4D494E49 'MINI' from our loader, 0x2BADB002 from GRUB)
;     EBX = pointer to the loader's info structure
;  We clear .bss, set up the kernel stack and call kernel_main(magic, info).
; =============================================================================

[BITS 32]

MB_MAGIC    equ 0x1BADB002
MB_FLAGS    equ 0x00000003              ; page-align modules | provide mem info
MB_CHECKSUM equ -(MB_MAGIC + MB_FLAGS)

extern kernel_main
extern _load_end
extern _bss_start
extern _bss_end
extern _stack_top

section .text.boot
global _start
_start:
    jmp _start32
    times 8-($-$$) db 0
    dd 0xDEADBEEF                       ; +8  kernel magic
    dd 0x00040100                       ; +12 version 4.1.0
    dd _load_end                        ; +16 end of file image
    dd _bss_end                         ; +20 end of memory image

align 4
multiboot_header:                       ; +24
    dd MB_MAGIC
    dd MB_FLAGS
    dd MB_CHECKSUM

_start32:
    cli
    cld
    mov esi, eax                        ; keep boot magic
    mov ebp, ebx                        ; keep info pointer

    ; ---- clear .bss ----------------------------------------------------------
    mov edi, _bss_start
    mov ecx, _bss_end
    sub ecx, edi
    shr ecx, 2
    xor eax, eax
    rep stosd

    ; ---- kernel stack, call C -----------------------------------------------
    mov esp, _stack_top
    xor eax, eax
    push eax                            ; fake return address / frame terminator
    mov ebp, ebp
    push ebp                            ; arg 2: info pointer
    push esi                            ; arg 1: magic
    call kernel_main

.hang:                                  ; kernel_main must not return
    cli
    hlt
    jmp .hang

section .note.GNU-stack noalloc noexec nowrite progbits
