# Đầu vào Multiboot 1 cho kernel G (32-bit, GRUB/QEMU -kernel nạp được).
        .set MB_MAGIC,    0x1BADB002
        .set MB_FLAGS,    0x00000003          # căn trang + cung cấp mem info
        .set MB_CHECKSUM, -(MB_MAGIC + MB_FLAGS)

        .section .multiboot, "a"
        .align 4
        .long MB_MAGIC
        .long MB_FLAGS
        .long MB_CHECKSUM

# Ngăn xếp nằm trong section riêng (KHÔNG thuộc .bss) để clear_bss() của kernel
# không xoá chính ngăn xếp đang dùng.
        .section .stack, "aw", @nobits
        .align 16
stack_bottom:
        .skip 16384
stack_top:

        .section .text
        .global _start
        .type _start, @function
_start:
        cli
        mov $stack_top, %esp
        xor %ebp, %ebp
        push %ebx                 # con trỏ Multiboot info
        push %eax                 # magic
        call kmain
1:      cli
        hlt
        jmp 1b
        .size _start, . - _start

        .section .note.GNU-stack, "", @progbits
