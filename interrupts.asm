; interrupts_complete.asm - Complete Interrupt Handlers for MiniOS v4.0
; Compile: nasm -f elf32 interrupts_complete.asm -o interrupts.o

[BITS 32]

extern isr_handler
extern irq_handler
extern syscall_handler

; ========== ISR Macros ==========
%macro ISR_NOERRCODE 1
    global isr%1
    isr%1:
        cli
        push byte 0
        push byte %1
        jmp isr_common_stub
%endmacro

%macro ISR_ERRCODE 1
    global isr%1
    isr%1:
        cli
        push byte %1
        jmp isr_common_stub
%endmacro

%macro IRQ 2
    global irq%1
    irq%1:
        cli
        push byte 0
        push byte %2
        jmp irq_common_stub
%endmacro

; ========== CPU Exceptions (0-31) ==========
ISR_NOERRCODE 0   ; Division By Zero
ISR_NOERRCODE 1   ; Debug
ISR_NOERRCODE 2   ; NMI
ISR_NOERRCODE 3   ; Breakpoint
ISR_NOERRCODE 4   ; Overflow
ISR_NOERRCODE 5   ; Bound Range
ISR_NOERRCODE 6   ; Invalid Opcode
ISR_NOERRCODE 7   ; Device Not Available
ISR_ERRCODE   8   ; Double Fault
ISR_NOERRCODE 9   ; Coprocessor Segment Overrun
ISR_ERRCODE   10  ; Invalid TSS
ISR_ERRCODE   11  ; Segment Not Present
ISR_ERRCODE   12  ; Stack Segment Fault
ISR_ERRCODE   13  ; General Protection Fault
ISR_ERRCODE   14  ; Page Fault
ISR_NOERRCODE 15  ; Reserved
ISR_NOERRCODE 16  ; x87 FPU Error
ISR_ERRCODE   17  ; Alignment Check
ISR_NOERRCODE 18  ; Machine Check
ISR_NOERRCODE 19  ; SIMD Floating Point
ISR_NOERRCODE 20  ; Virtualization
ISR_NOERRCODE 21  ; Reserved
ISR_NOERRCODE 22  ; Reserved
ISR_NOERRCODE 23  ; Reserved
ISR_NOERRCODE 24  ; Reserved
ISR_NOERRCODE 25  ; Reserved
ISR_NOERRCODE 26  ; Reserved
ISR_NOERRCODE 27  ; Reserved
ISR_NOERRCODE 28  ; Reserved
ISR_NOERRCODE 29  ; Reserved
ISR_ERRCODE   30  ; Security Exception
ISR_NOERRCODE 31  ; Reserved

; ========== Hardware IRQs (32-47) ==========
IRQ 0, 32   ; Timer
IRQ 1, 33   ; Keyboard
IRQ 2, 34   ; Cascade
IRQ 3, 35   ; COM2
IRQ 4, 36   ; COM1
IRQ 5, 37   ; LPT2
IRQ 6, 38   ; Floppy
IRQ 7, 39   ; LPT1
IRQ 8, 40   ; RTC
IRQ 9, 41   ; Free
IRQ 10, 42  ; Free
IRQ 11, 43  ; Free
IRQ 12, 44  ; PS/2 Mouse
IRQ 13, 45  ; FPU
IRQ 14, 46  ; Primary ATA
IRQ 15, 47  ; Secondary ATA

; ========== Common ISR Handler ==========
isr_common_stub:
    pusha
    
    push ds
    push es
    push fs
    push gs
    
    mov ax, 0x10
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    
    push esp
    call isr_handler
    add esp, 4
    
    pop gs
    pop fs
    pop es
    pop ds
    
    popa
    add esp, 8
    
    iret

; ========== Common IRQ Handler ==========
irq_common_stub:
    pusha
    
    push ds
    push es
    push fs
    push gs
    
    mov ax, 0x10
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    
    push esp
    call irq_handler
    add esp, 4
    
    pop gs
    pop fs
    pop es
    pop ds
    
    popa
    add esp, 8
    
    iret

; ========== System Call Handler (INT 0x80) ==========
global syscall_int
syscall_int:
    cli
    
    pusha
    push ds
    push es
    push fs
    push gs
    
    mov ax, 0x10
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    
    ; syscall(num, arg1, arg2, arg3, arg4)
    push edi
    push esi
    push edx
    push ecx
    push ebx
    push eax
    call syscall_handler
    add esp, 24
    
    mov [esp + 28], eax  ; Return value in EAX
    
    pop gs
    pop fs
    pop es
    pop ds
    popa
    
    iret

; ========== Context Switch ==========
global switch_context
switch_context:
    ; Parameters: old_regs (ESP+4), new_regs (ESP+8)
    
    mov eax, [esp + 4]  ; old_regs
    test eax, eax
    jz .load_new
    
    ; Save current context
    mov [eax + 0], ebx
    mov [eax + 4], ecx
    mov [eax + 8], edx
    mov [eax + 12], esi
    mov [eax + 16], edi
    mov [eax + 20], ebp
    mov [eax + 24], esp
    
    pushf
    pop dword [eax + 32]  ; EFLAGS
    
    mov ecx, [esp]
    mov [eax + 28], ecx   ; EIP (return address)
    
    mov cx, ds
    mov [eax + 36], cx
    mov cx, es
    mov [eax + 40], cx
    mov cx, fs
    mov [eax + 44], cx
    mov cx, gs
    mov [eax + 48], cx
    mov cx, ss
    mov [eax + 52], cx
    
.load_new:
    mov eax, [esp + 8]  ; new_regs
    
    ; Load segment registers
    mov cx, [eax + 36]
    mov ds, cx
    mov cx, [eax + 40]
    mov es, cx
    mov cx, [eax + 44]
    mov fs, cx
    mov cx, [eax + 48]
    mov gs, cx
    
    ; Load general registers
    mov ebx, [eax + 0]
    mov ecx, [eax + 4]
    mov edx, [eax + 8]
    mov esi, [eax + 12]
    mov edi, [eax + 16]
    mov ebp, [eax + 20]
    
    ; Load CR3 if present
    mov ecx, [eax + 56]
    test ecx, ecx
    jz .no_cr3
    mov cr3, ecx
.no_cr3:
    
    ; Prepare stack for iret
    mov esp, [eax + 24]
    
    push dword [eax + 52]  ; SS
    push dword [eax + 24]  ; ESP
    push dword [eax + 32]  ; EFLAGS
    push dword [eax + 36]  ; CS (use DS for now)
    push dword [eax + 28]  ; EIP
    
    ; Load EAX last
    mov eax, [eax + 0]
    
    iret

; ========== Atomic Operations ==========
global atomic_increment
atomic_increment:
    mov eax, [esp + 4]
    lock inc dword [eax]
    ret

global atomic_decrement
atomic_decrement:
    mov eax, [esp + 4]
    lock dec dword [eax]
    ret

global atomic_exchange
atomic_exchange:
    mov ecx, [esp + 4]
    mov eax, [esp + 8]
    xchg [ecx], eax
    ret

global atomic_compare_exchange
atomic_compare_exchange:
    mov edx, [esp + 4]
    mov eax, [esp + 8]
    mov ecx, [esp + 12]
    lock cmpxchg [edx], ecx
    setz al
    movzx eax, al
    ret

; ========== CPU Control ==========
global enable_interrupts
enable_interrupts:
    sti
    ret

global disable_interrupts
disable_interrupts:
    cli
    ret

global halt
halt:
    hlt
    ret

global get_eflags
get_eflags:
    pushf
    pop eax
    ret

global set_eflags
set_eflags:
    mov eax, [esp + 4]
    push eax
    popf
    ret

; ========== Memory Barriers ==========
global memory_barrier
memory_barrier:
    mfence
    ret

global read_barrier
read_barrier:
    lfence
    ret

global write_barrier
write_barrier:
    sfence
    ret

; ========== CPUID ==========
global cpuid_available
cpuid_available:
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
    mov eax, 1
    ret
.no_cpuid:
    xor eax, eax
    ret

global get_cpuid
get_cpuid:
    push ebx
    push ecx
    push edx
    push edi
    
    mov eax, [esp + 20]  ; function
    mov edi, [esp + 24]  ; output pointer
    
    cpuid
    
    mov [edi + 0], eax
    mov [edi + 4], ebx
    mov [edi + 8], ecx
    mov [edi + 12], edx
    
    pop edi
    pop edx
    pop ecx
    pop ebx
    ret

; ========== TSC ==========
global read_tsc
read_tsc:
    rdtsc
    ret

; ========== CR Registers ==========
global get_cr0
get_cr0:
    mov eax, cr0
    ret

global set_cr0
set_cr0:
    mov eax, [esp + 4]
    mov cr0, eax
    ret

global get_cr2
get_cr2:
    mov eax, cr2
    ret

global get_cr3
get_cr3:
    mov eax, cr3
    ret

global set_cr3
set_cr3:
    mov eax, [esp + 4]
    mov cr3, eax
    ret

global get_cr4
get_cr4:
    mov eax, cr4
    ret

global set_cr4
set_cr4:
    mov eax, [esp + 4]
    mov cr4, eax
    ret

; ========== TLB ==========
global flush_tlb
flush_tlb:
    mov eax, cr3
    mov cr3, eax
    ret

global flush_tlb_single
flush_tlb_single:
    mov eax, [esp + 4]
    invlpg [eax]
    ret

; ========== GDT/IDT ==========
global load_gdt
load_gdt:
    mov eax, [esp + 4]
    lgdt [eax]
    ret

global load_idt
load_idt:
    mov eax, [esp + 4]
    lidt [eax]
    ret

global load_tr
load_tr:
    mov ax, [esp + 4]
    ltr ax
    ret

; ========== Port I/O with Barriers ==========
global io_outb
io_outb:
    mov dx, [esp + 4]
    mov al, [esp + 8]
    out dx, al
    ret

global io_inb
io_inb:
    mov dx, [esp + 4]
    in al, dx
    ret

global io_outw
io_outw:
    mov dx, [esp + 4]
    mov ax, [esp + 8]
    out dx, ax
    ret

global io_inw
io_inw:
    mov dx, [esp + 4]
    in ax, dx
    ret

global io_outl
io_outl:
    mov dx, [esp + 4]
    mov eax, [esp + 8]
    out dx, eax
    ret

global io_inl
io_inl:
    mov dx, [esp + 4]
    in eax, dx
    ret

; ========== Fast Memcpy ==========
global fast_memcpy
fast_memcpy:
    push edi
    push esi
    
    mov edi, [esp + 12]  ; dest
    mov esi, [esp + 16]  ; src
    mov ecx, [esp + 20]  ; size
    
    cld
    rep movsb
    
    pop esi
    pop edi
    ret

; ========== Fast Memset ==========
global fast_memset
fast_memset:
    push edi
    
    mov edi, [esp + 8]   ; dest
    mov al, [esp + 12]   ; value
    mov ecx, [esp + 16]  ; size
    
    cld
    rep stosb
    
    pop edi
    ret

; ========== Spinlock ==========
global spinlock_acquire
spinlock_acquire:
    mov eax, [esp + 4]
.retry:
    lock bts dword [eax], 0
    jc .retry
    ret

global spinlock_release
spinlock_release:
    mov eax, [esp + 4]
    lock btr dword [eax], 0
    ret

; ========== Stack Switching ==========
global switch_to_kernel_stack
switch_to_kernel_stack:
    mov eax, [esp + 4]  ; new stack
    mov esp, eax
    ret

; ========== Panic Handler ==========
global kernel_panic
kernel_panic:
    cli
    hlt
    jmp $