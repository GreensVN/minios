; =============================================================================
;  Bootloader.asm - MiniOS two-stage BIOS bootloader
;
;  Layout on disk (512-byte sectors):
;     LBA 0        : stage 1  (this sector, ends with 0xAA55)
;     LBA 1..7     : stage 2  (loaded by stage 1 to 0x7E00, right after us)
;     LBA 8..      : kernel.bin (flat binary, linked at 1 MiB)
;
;  Boot flow:
;     stage1 : set up segments/stack, detect INT 13h extensions + geometry,
;              load stage 2 with LBA (fallback: CHS), jump to it.
;     stage2 : banner, A20, E820 memory map, CPUID features, load the kernel
;              header, validate magic, load the rest of the image into a bounce
;              buffer (0x10000), enter protected mode, copy image to 1 MiB and
;              jump to it with  EAX = BOOT_MAGIC, EBX = &boot_info.
;
;  Assemble:  nasm -f bin Bootloader.asm -o bootloader.bin   (exactly 4096 B)
; =============================================================================

[BITS 16]
[ORG 0x7C00]

; ---------------------------------------------------------------- constants --
STAGE2_LBA      equ 1
STAGE2_SECTORS  equ 7                   ; 3.5 KiB, loaded at 0x7E00
STAGE2_ADDR     equ 0x7E00
KERNEL_LBA      equ 8
KERNEL_BOUNCE   equ 0x10000             ; real-mode load buffer (64 KiB..512 KiB)
KERNEL_BOUNCE_SEG equ (KERNEL_BOUNCE >> 4)
KERNEL_ADDR     equ 0x00100000          ; final address (1 MiB)
KERNEL_MAX_SECT equ 896                 ; 448 KiB fits below 0x80000
KERNEL_MAGIC    equ 0xDEADBEEF          ; at image offset 8 (see entry.asm)
E820_BUF        equ 0xA000              ; memory map storage (24-byte entries)
E820_MAX        equ 64
BOOT_MAGIC      equ 0x4D494E49          ; 'MINI' – handed to the kernel in EAX
PM_STACK        equ 0x90000

; =============================================================================
;                                   STAGE 1
; =============================================================================
stage1:
    cli
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7C00
    cld
    sti

    mov [boot_drive], dl

    mov si, msg_stage1
    call print16

    ; --- INT 13h extensions (LBA) available? -------------------------------
    mov ah, 0x41
    mov bx, 0x55AA
    mov dl, [boot_drive]
    int 0x13
    jc .no_lba
    cmp bx, 0xAA55
    jne .no_lba
    test cx, 1
    jz .no_lba
    mov byte [has_lba], 1
.no_lba:

    ; --- drive geometry for the CHS fallback --------------------------------
    mov ah, 0x08
    mov dl, [boot_drive]
    xor di, di
    int 0x13
    jc .geo_done
    and cl, 0x3F
    jz .geo_done
    mov [spt], cl
    inc dh
    mov [heads], dh
.geo_done:
    xor ax, ax
    mov es, ax                          ; INT 13h/08h clobbers ES:DI

    ; --- load stage 2 -------------------------------------------------------
    mov eax, STAGE2_LBA
    mov cx, STAGE2_SECTORS
    mov bx, STAGE2_ADDR
    call read_sectors
    jc disk_error

    jmp stage2

; -----------------------------------------------------------------------------
; read_sectors: EAX = first LBA, CX = count, ES:BX = destination.
;               Reads one sector per BIOS call (robust on every BIOS), retries
;               3 times with a controller reset.  CF set on failure.
; -----------------------------------------------------------------------------
read_sectors:
    pushad
.next:
    mov byte [retries], 3
.try:
    pushad
    cmp byte [has_lba], 0
    je .chs
    ; ---- LBA via disk address packet ----
    mov [dap_lba], eax
    mov [dap_off], bx
    mov [dap_seg], es
    mov si, dap
    mov ah, 0x42
    mov dl, [boot_drive]
    int 0x13
    jmp .after
.chs:
    ; ---- LBA -> CHS ----
    xor edx, edx
    movzx ecx, byte [spt]
    div ecx                             ; EAX = LBA / SPT, EDX = LBA % SPT
    inc dl
    mov [tmp_sector], dl
    xor edx, edx
    movzx ecx, byte [heads]
    div ecx                             ; EAX = cylinder, EDX = head
    mov dh, dl                          ; head
    mov ch, al                          ; cylinder low 8 bits
    mov cl, ah
    shl cl, 6                           ; cylinder high 2 bits
    or  cl, [tmp_sector]
    mov dl, [boot_drive]
    mov ax, 0x0201
    int 0x13
.after:
    popad
    jnc .ok
    ; reset controller and retry
    push ax
    xor ah, ah
    mov dl, [boot_drive]
    int 0x13
    pop ax
    dec byte [retries]
    jnz .try
    popad
    stc
    ret
.ok:
    inc eax
    add bx, 512
    jnc .no_wrap
    mov dx, es                          ; crossed a 64 KiB boundary
    add dx, 0x1000
    mov es, dx
.no_wrap:
    dec cx
    jnz .next
    popad
    clc
    ret

; -----------------------------------------------------------------------------
; print16: DS:SI = zero-terminated string (BIOS teletype)
; -----------------------------------------------------------------------------
print16:
    pusha
    mov ah, 0x0E
    xor bh, bh
.loop:
    lodsb
    test al, al
    jz .done
    int 0x10
    jmp .loop
.done:
    popa
    ret

disk_error:
    mov si, msg_disk_error
    jmp fatal16
kernel_error:
    mov si, msg_bad_kernel
    jmp fatal16
a20_error:
    mov si, msg_a20_fail
fatal16:
    call print16
    mov si, msg_halt
    call print16
.hang:
    cli
    hlt
    jmp .hang

; ---------------------------------------------------------------- stage1 data
boot_drive  db 0
has_lba     db 0
spt         db 63
heads       db 16
retries     db 0
tmp_sector  db 0

align 4
dap:
    db 0x10, 0
dap_count:  dw 1
dap_off:    dw 0
dap_seg:    dw 0
dap_lba:    dd 0
            dd 0

msg_stage1     db 'MiniOS stage1', 13, 10, 0
msg_disk_error db 13, 10, '[FAIL] Disk read error', 13, 10, 0
msg_bad_kernel db 13, 10, '[FAIL] Kernel image invalid', 13, 10, 0
msg_a20_fail   db 13, 10, '[FAIL] A20 line could not be enabled', 13, 10, 0
msg_halt       db '[HALT] System halted', 13, 10, 0

times 510-($-$$) db 0
dw 0xAA55

; =============================================================================
;                                   STAGE 2                       (at 0x7E00)
; =============================================================================
stage2:
    mov si, msg_banner
    call print16

    ; ---- A20 ---------------------------------------------------------------
    mov si, msg_a20
    call print16
    call enable_a20
    jc a20_error
    mov si, msg_ok
    call print16

    ; ---- memory ------------------------------------------------------------
    call detect_memory

    ; ---- CPU ---------------------------------------------------------------
    call detect_cpu

    ; ---- kernel header (first sector) --------------------------------------
    mov si, msg_loading
    call print16
    mov ax, KERNEL_BOUNCE_SEG
    mov es, ax
    xor bx, bx
    mov eax, KERNEL_LBA
    mov cx, 1
    call read_sectors
    jc disk_error

    cmp dword [es:8], KERNEL_MAGIC      ; entry.asm header: +8 magic
    jne kernel_error

    mov eax, [es:16]                    ; +16 physical end of image
    sub eax, KERNEL_ADDR
    jbe kernel_error
    mov [kernel_bytes], eax
    add eax, 511
    shr eax, 9                          ; -> sectors
    cmp eax, KERNEL_MAX_SECT
    ja  kernel_error
    mov [kernel_sectors], ax

    ; ---- rest of the image -------------------------------------------------
    mov cx, ax
    dec cx                              ; header sector already loaded
    jz .loaded
    mov ax, KERNEL_BOUNCE_SEG
    mov es, ax
    mov bx, 512
    mov eax, KERNEL_LBA + 1
    call read_sectors
    jc disk_error
.loaded:
    xor ax, ax
    mov es, ax

    mov si, msg_ok
    call print16
    mov si, msg_kernel_info
    call print16
    movzx eax, word [kernel_sectors]
    call print_dec
    mov si, msg_sectors
    call print16

    ; ---- boot info ---------------------------------------------------------
    movzx eax, byte [boot_drive]
    mov [boot_info.drive], eax

    ; ---- protected mode ----------------------------------------------------
    mov si, msg_pm
    call print16
    cli
    lgdt [gdt_descriptor]
    mov eax, cr0
    or  eax, 1
    mov cr0, eax
    jmp 0x08:pm_entry

; -----------------------------------------------------------------------------
; A20 gate: BIOS -> keyboard controller -> fast A20, verified after each try.
; -----------------------------------------------------------------------------
enable_a20:
    call check_a20
    jnc .done
    mov ax, 0x2401                      ; BIOS
    int 0x15
    call check_a20
    jnc .done
    call a20_kbc                        ; keyboard controller
    call check_a20
    jnc .done
    in  al, 0x92                        ; fast A20
    test al, 2
    jnz .fast_done
    or  al, 2
    and al, 0xFE
    out 0x92, al
.fast_done:
    mov cx, 0xFFFF
.wait:
    call check_a20
    jnc .done
    loop .wait
    stc
    ret
.done:
    clc
    ret

; check_a20: CF clear if enabled. Compares 0000:0500 with FFFF:0510 (which
;            alias to the same byte when A20 is off).
check_a20:
    push ds
    push es
    push di
    push si
    push bx
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
    mov bl, [es:di]                     ; BL = 0xFF  -> wrapped (A20 off)
    pop ax
    mov [ds:si], al
    pop ax
    mov [es:di], al
    cmp bl, 0xFF
    pop bx
    pop si
    pop di
    pop es
    pop ds
    je .disabled
    clc
    ret
.disabled:
    stc
    ret

a20_kbc:
    call .wait_in
    mov al, 0xAD                        ; disable keyboard
    out 0x64, al
    call .wait_in
    mov al, 0xD0                        ; read output port
    out 0x64, al
    call .wait_out
    in  al, 0x60
    push ax
    call .wait_in
    mov al, 0xD1                        ; write output port
    out 0x64, al
    call .wait_in
    pop ax
    or  al, 2
    out 0x60, al
    call .wait_in
    mov al, 0xAE                        ; enable keyboard
    out 0x64, al
    call .wait_in
    ret
.wait_in:
    in  al, 0x64
    test al, 2
    jnz .wait_in
    ret
.wait_out:
    in  al, 0x64
    test al, 1
    jz .wait_out
    ret

; -----------------------------------------------------------------------------
; detect_memory: INT 15h E820 map -> E820_BUF, count + usable total in
;                boot_info. Fallbacks: E801, then 88h. Low memory via INT 12h.
; -----------------------------------------------------------------------------
detect_memory:
    int 0x12                            ; AX = KiB of conventional memory
    movzx eax, ax
    mov [boot_info.mem_lower], eax

    mov si, msg_memory
    call print16

    xor ebx, ebx
    mov di, E820_BUF
    xor bp, bp                          ; entry counter
.e820_loop:
    mov eax, 0xE820
    mov edx, 0x534D4150                 ; 'SMAP'
    mov ecx, 24
    mov dword [es:di + 20], 1           ; ACPI 3.0 "valid" bit
    int 0x15
    jc .e820_end
    cmp eax, 0x534D4150
    jne .e820_end
    jcxz .e820_skip
    cmp dword [es:di + 16], 1           ; type 1 = usable RAM
    jne .e820_next
    cmp dword [es:di + 4], 0            ; base >= 4 GiB: ignore
    jne .e820_next
    cmp dword [es:di], 0x100000         ; only count RAM above 1 MiB
    jb .e820_next
    mov eax, [es:di + 8]                ; length (low dword) -> KiB
    shr eax, 10
    add [boot_info.mem_upper], eax
.e820_next:
    inc bp
    add di, 24
    cmp bp, E820_MAX
    jae .e820_end
.e820_skip:
    test ebx, ebx
    jnz .e820_loop
.e820_end:
    mov [boot_info.e820_count], bp
    test bp, bp
    jnz .report

    ; ---- fallback: E801 ----
    xor cx, cx
    xor dx, dx
    mov ax, 0xE801
    int 0x15
    jc .try_88
    jcxz .use_ax
    mov ax, cx
    mov bx, dx
.use_ax:
    movzx eax, ax                       ; KiB between 1 MiB and 16 MiB
    movzx ebx, bx                       ; 64 KiB blocks above 16 MiB
    shl ebx, 6
    add eax, ebx
    mov [boot_info.mem_upper], eax
    jmp .report
.try_88:
    mov ah, 0x88
    int 0x15
    movzx eax, ax
    mov [boot_info.mem_upper], eax
.report:
    mov eax, [boot_info.mem_upper]
    add eax, 1024                       ; + first MiB
    shr eax, 10
    call print_dec
    mov si, msg_mb
    call print16
    ret

; -----------------------------------------------------------------------------
; detect_cpu: CPUID presence, vendor, SSE / AVX / long mode flags.
;             boot_info.cpu_flags: bit0 CPUID, bit1 SSE, bit2 SSE2, bit3 AVX,
;                                  bit4 long mode
; -----------------------------------------------------------------------------
detect_cpu:
    mov si, msg_cpu
    call print16
    pushfd
    pop eax
    mov ecx, eax
    xor eax, 0x00200000                 ; toggle ID bit
    push eax
    popfd
    pushfd
    pop eax
    push ecx
    popfd
    xor eax, ecx
    jz .no_cpuid

    or byte [boot_info.cpu_flags], 1
    xor eax, eax
    cpuid
    mov [boot_info.vendor], ebx
    mov [boot_info.vendor + 4], edx
    mov [boot_info.vendor + 8], ecx
    mov si, boot_info.vendor
    call print16
    mov si, msg_space
    call print16

    mov eax, 1
    cpuid
    test edx, 1 << 25
    jz .sse2
    or byte [boot_info.cpu_flags], 2
    mov si, msg_sse
    call print16
.sse2:
    test edx, 1 << 26
    jz .avx
    or byte [boot_info.cpu_flags], 4
    mov si, msg_sse2
    call print16
.avx:
    test ecx, 1 << 28
    jz .lm
    or byte [boot_info.cpu_flags], 8
    mov si, msg_avx
    call print16
.lm:
    mov eax, 0x80000000
    cpuid
    cmp eax, 0x80000001
    jb .done
    mov eax, 0x80000001
    cpuid
    test edx, 1 << 29
    jz .done
    or byte [boot_info.cpu_flags], 16
    mov si, msg_lm
    call print16
.done:
    mov si, msg_crlf
    call print16
    ret
.no_cpuid:
    mov si, msg_no_cpuid
    call print16
    ret

; print_dec: EAX = unsigned number
print_dec:
    pushad
    mov ecx, 10
    mov bx, num_buf + 10
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
    call print16
    popad
    ret

; -----------------------------------------------------------------------------
;                              32-bit protected mode
; -----------------------------------------------------------------------------
[BITS 32]
pm_entry:
    mov ax, 0x10
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov ss, ax
    mov esp, PM_STACK

    ; copy kernel image: bounce buffer -> 1 MiB
    mov esi, KERNEL_BOUNCE
    mov edi, KERNEL_ADDR
    mov ecx, [kernel_bytes]
    add ecx, 3
    shr ecx, 2
    cld
    rep movsd

    mov eax, BOOT_MAGIC
    mov ebx, boot_info
    jmp KERNEL_ADDR                     ; never returns

; ---------------------------------------------------------------- stage2 data
[BITS 16]
kernel_bytes    dd 0
kernel_sectors  dw 0
num_buf         times 11 db 0

; Passed to the kernel (EBX). Keep in sync with boot_info_t in kernel.h.
align 4
boot_info:
.magic      dd BOOT_MAGIC
.drive      dd 0
.mem_lower  dd 0                        ; KiB below 1 MiB
.mem_upper  dd 0                        ; KiB above 1 MiB (usable)
.e820_count dd 0
.e820_addr  dd E820_BUF
.cpu_flags  dd 0
.vendor     times 13 db 0
            times 3 db 0

msg_banner      db 13, 10
                db '  +----------------------------------------+', 13, 10
                db '  |   MiniOS v4.1  -  two-stage bootloader  |', 13, 10
                db '  +----------------------------------------+', 13, 10, 0
msg_a20         db '  A20 line ........ ', 0
msg_memory      db '  Memory .......... ', 0
msg_cpu         db '  CPU ............. ', 0
msg_loading     db '  Kernel .......... ', 0
msg_kernel_info db '  Image ........... ', 0
msg_sectors     db ' sectors -> 0x00100000', 13, 10, 0
msg_pm          db '  Entering protected mode...', 13, 10, 0
msg_ok          db 'OK', 13, 10, 0
msg_mb          db ' MB', 13, 10, 0
msg_sse         db 'SSE ', 0
msg_sse2        db 'SSE2 ', 0
msg_avx         db 'AVX ', 0
msg_lm          db 'x86-64 ', 0
msg_no_cpuid    db 'legacy (no CPUID)', 13, 10, 0
msg_space       db ' ', 0
msg_crlf        db 13, 10, 0

; ---------------------------------------------------------------- GDT --------
align 8
gdt_start:
    dq 0                                ; null
    dw 0xFFFF, 0x0000                   ; 0x08: code, base 0, limit 4 GiB
    db 0x00, 10011010b, 11001111b, 0x00
    dw 0xFFFF, 0x0000                   ; 0x10: data
    db 0x00, 10010010b, 11001111b, 0x00
gdt_end:
gdt_descriptor:
    dw gdt_end - gdt_start - 1
    dd gdt_start

%if ($ - $$) > (512 * (STAGE2_SECTORS + 1))
    %error "stage 2 does not fit into STAGE2_SECTORS"
%endif
times 512*(STAGE2_SECTORS + 1) - ($-$$) db 0
