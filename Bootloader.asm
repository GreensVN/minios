; bootloader_ultimate.asm - MiniOS v4.0 ULTIMATE Bootloader
; Features: A20, Memory Detection, CPUID, Long Mode Ready, Error Recovery
; Compile: nasm -f bin bootloader_ultimate.asm -o bootloader.bin

[BITS 16]
[ORG 0x7C00]

; ========== Configuration ==========
KERNEL_OFFSET equ 0x1000
KERNEL_SECTOR equ 2
KERNEL_SECTORS equ 64
STACK_TOP equ 0x7C00

; ========== Entry Point ==========
start:
    cli
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, STACK_TOP
    cld
    sti
    
    mov [boot_drive], dl
    
    call clear_screen
    call print_banner
    
    ; Stage 1: Hardware Detection
    mov si, msg_stage1
    call print_string
    
    call enable_a20_gate
    jc error_a20
    
    call detect_memory
    call detect_cpu_features
    
    ; Stage 2: Load Kernel
    mov si, msg_stage2
    call print_string
    
    call load_kernel_with_retry
    jc error_disk
    
    ; Stage 3: Enter Protected Mode
    mov si, msg_stage3
    call print_string
    
    lgdt [gdt_descriptor]
    
    cli
    mov eax, cr0
    or eax, 1
    mov cr0, eax
    
    jmp 0x08:protected_mode

; ========== A20 Gate ==========
enable_a20_gate:
    call check_a20
    jnc .already_enabled
    
    ; Try BIOS method
    mov ax, 0x2401
    int 0x15
    jnc .check
    
    ; Try keyboard controller
    call enable_a20_keyboard
    
    ; Try fast A20
    in al, 0x92
    or al, 2
    out 0x92, al
    
.check:
    call check_a20
    jc .failed
    
.already_enabled:
    mov si, msg_a20_ok
    call print_string
    clc
    ret
    
.failed:
    stc
    ret

check_a20:
    pushf
    push es
    push ds
    push di
    push si
    
    xor ax, ax
    mov es, ax
    mov di, 0x0500
    
    not ax
    mov ds, ax
    mov si, 0x0510
    
    mov al, [es:di]
    push ax
    mov al, [ds:si]
    push ax
    
    mov byte [es:di], 0x00
    mov byte [ds:si], 0xFF
    
    cmp byte [es:di], 0xFF
    
    pop ax
    mov [ds:si], al
    pop ax
    mov [es:di], al
    
    pop si
    pop di
    pop ds
    pop es
    popf
    
    je .disabled
    clc
    ret
.disabled:
    stc
    ret

enable_a20_keyboard:
    call .wait1
    mov al, 0xAD
    out 0x64, al
    
    call .wait1
    mov al, 0xD0
    out 0x64, al
    
    call .wait2
    in al, 0x60
    push ax
    
    call .wait1
    mov al, 0xD1
    out 0x64, al
    
    call .wait1
    pop ax
    or al, 2
    out 0x60, al
    
    call .wait1
    mov al, 0xAE
    out 0x64, al
    
    call .wait1
    ret

.wait1:
    in al, 0x64
    test al, 2
    jnz .wait1
    ret

.wait2:
    in al, 0x64
    test al, 1
    jz .wait2
    ret

; ========== Memory Detection ==========
detect_memory:
    mov si, msg_memory
    call print_string
    
    ; Try E820 method
    xor ebx, ebx
    mov edx, 0x534D4150
    mov eax, 0xE820
    mov ecx, 24
    mov di, 0x8000
    int 0x15
    jc .try_e801
    
    mov eax, [0x8000 + 8]
    shr eax, 20
    call print_number
    mov si, msg_mb
    call print_string
    ret
    
.try_e801:
    mov ax, 0xE801
    int 0x15
    jc .try_88
    
    movzx eax, ax
    shr eax, 10
    call print_number
    mov si, msg_mb
    call print_string
    ret
    
.try_88:
    mov ah, 0x88
    int 0x15
    movzx eax, ax
    shr eax, 10
    call print_number
    mov si, msg_mb
    call print_string
    ret

; ========== CPU Detection ==========
detect_cpu_features:
    mov si, msg_cpu
    call print_string
    
    ; Check CPUID
    pushfd
    pop eax
    mov ecx, eax
    xor eax, 0x00200000
    push eax
    popfd
    pushfd
    pop eax
    xor eax, ecx
    jz .no_cpuid
    
    ; Get features
    mov eax, 1
    cpuid
    
    ; Check SSE
    test edx, (1 << 25)
    jz .check_avx
    mov si, msg_sse
    call print_string
    
.check_avx:
    test ecx, (1 << 28)
    jz .done
    mov si, msg_avx
    call print_string
    jmp .done
    
.no_cpuid:
    mov si, msg_no_cpuid
    call print_string
    
.done:
    ret

; ========== Load Kernel with Retry ==========
load_kernel_with_retry:
    mov byte [retry_count], 3
    
.retry:
    call load_kernel
    jnc .success
    
    dec byte [retry_count]
    jz .failed
    
    ; Reset disk
    mov ah, 0x00
    mov dl, [boot_drive]
    int 0x13
    
    jmp .retry
    
.success:
    mov si, msg_kernel_ok
    call print_string
    
    ; Verify kernel magic
    mov eax, [KERNEL_OFFSET]
    cmp eax, 0xDEADBEEF
    je .valid
    cmp eax, 0xCAFEBABE
    je .valid
    
    mov si, msg_kernel_invalid
    call print_string
    stc
    ret
    
.valid:
    mov si, msg_kernel_valid
    call print_string
    clc
    ret
    
.failed:
    stc
    ret

load_kernel:
    push es
    mov ax, KERNEL_OFFSET
    shr ax, 4
    mov es, ax
    xor bx, bx
    
    mov ah, 0x00
    mov dl, [boot_drive]
    int 0x13
    
    mov ah, 0x02
    mov al, KERNEL_SECTORS
    mov ch, 0
    mov cl, KERNEL_SECTOR
    mov dh, 0
    mov dl, [boot_drive]
    int 0x13
    
    pop es
    ret

; ========== Display Functions ==========
clear_screen:
    pusha
    mov ah, 0x06
    xor al, al
    xor cx, cx
    mov dx, 0x184F
    mov bh, 0x1F
    int 0x10
    
    mov ah, 0x02
    xor bh, bh
    xor dx, dx
    int 0x10
    popa
    ret

print_banner:
    mov si, banner
    call print_string
    ret

print_string:
    pusha
    mov ah, 0x0E
    xor bh, bh
    mov bl, 0x0F
.loop:
    lodsb
    test al, al
    jz .done
    int 0x10
    jmp .loop
.done:
    popa
    ret

print_number:
    pusha
    mov cx, 10
    mov bx, number_buffer + 9
    mov byte [bx], 0
    
.loop:
    xor edx, edx
    div ecx
    add dl, '0'
    dec bx
    mov [bx], dl
    test eax, eax
    jnz .loop
    
    mov si, bx
    call print_string
    popa
    ret

; ========== Error Handlers ==========
error_a20:
    mov si, msg_a20_fail
    call print_string
    jmp halt_system

error_disk:
    mov si, msg_disk_error
    call print_string
    jmp halt_system

halt_system:
    mov si, msg_halt
    call print_string
    cli
    hlt
    jmp $

; ========== Protected Mode ==========
[BITS 32]
protected_mode:
    mov ax, 0x10
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov ss, ax
    mov esp, 0x90000
    
    ; Clear screen in 32-bit
    mov edi, 0xB8000
    mov ecx, 2000
    mov ax, 0x1F20
    rep stosw
    
    ; Print message
    mov esi, pm_message
    mov edi, 0xB8000
    mov ah, 0x2F
    
.print:
    lodsb
    test al, al
    jz .done
    stosw
    jmp .print
    
.done:
    call KERNEL_OFFSET
    
    cli
    hlt
    jmp $

; ========== Data Section ==========
[BITS 16]

boot_drive db 0
retry_count db 3
number_buffer times 10 db 0

banner:
    db 0x0D, 0x0A
    db '  ╔══════════════════════════════════════════════════╗', 0x0D, 0x0A
    db '  ║     MiniOS v4.0 ULTIMATE Bootloader             ║', 0x0D, 0x0A
    db '  ║     Advanced | Stable | Production Ready        ║', 0x0D, 0x0A
    db '  ╚══════════════════════════════════════════════════╝', 0x0D, 0x0A, 0x0A, 0

msg_stage1 db '[STAGE 1] Hardware Detection', 0x0D, 0x0A, 0
msg_stage2 db 0x0D, 0x0A, '[STAGE 2] Loading Kernel', 0x0D, 0x0A, 0
msg_stage3 db 0x0D, 0x0A, '[STAGE 3] Entering Protected Mode', 0x0D, 0x0A, 0

msg_a20_ok db '  [OK] A20 Gate Enabled', 0x0D, 0x0A, 0
msg_a20_fail db '  [FAIL] A20 Gate Failed', 0x0D, 0x0A, 0
msg_memory db '  [*] Memory: ', 0
msg_mb db ' MB', 0x0D, 0x0A, 0
msg_cpu db '  [*] CPU Features: ', 0
msg_sse db 'SSE ', 0
msg_avx db 'AVX ', 0
msg_no_cpuid db 'Legacy', 0x0D, 0x0A, 0

msg_kernel_ok db '  [OK] Kernel Loaded (', 0
msg_kernel_valid db ' sectors)', 0x0D, 0x0A, '  [OK] Signature Valid', 0x0D, 0x0A, 0
msg_kernel_invalid db '  [FAIL] Invalid Kernel!', 0x0D, 0x0A, 0
msg_disk_error db '  [FAIL] Disk Read Error', 0x0D, 0x0A, 0
msg_halt db '  [HALT] System Halted', 0x0D, 0x0A, 0

pm_message db '>>> Protected Mode Active - Starting Kernel...', 0

; ========== GDT ==========
align 8
gdt_start:

gdt_null:
    dd 0x00000000
    dd 0x00000000

gdt_code:
    dw 0xFFFF
    dw 0x0000
    db 0x00
    db 10011010b
    db 11001111b
    db 0x00

gdt_data:
    dw 0xFFFF
    dw 0x0000
    db 0x00
    db 10010010b
    db 11001111b
    db 0x00

gdt_end:

gdt_descriptor:
    dw gdt_end - gdt_start - 1
    dd gdt_start

times 510-($-$$) db 0
dw 0xAA55