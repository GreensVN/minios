; =============================================================================
;  interrupts.asm - ISR/IRQ/syscall stubs, context switch and CPU helpers
;
;  Assemble: nasm -f elf32 interrupts.asm -o interrupts.o
;
;  Stack frame handed to the C handlers (matches interrupt_frame_t in
;  kernel.h, lowest address first):
;      gs, fs, es, ds
;      edi, esi, ebp, esp, ebx, edx, ecx, eax     (pusha)
;      int_no, err_code
;      eip, cs, eflags, [useresp, ss]              (CPU)
; =============================================================================

[BITS 32]

extern isr_handler
extern irq_handler
extern syscall_handler

KERNEL_DS equ 0x10

; ------------------------------------------------------------------ macros ---
%macro ISR_NOERRCODE 1
    global isr%1
    isr%1:
        push dword 0                    ; dummy error code
        push dword %1
        jmp isr_common_stub
%endmacro

%macro ISR_ERRCODE 1
    global isr%1
    isr%1:
        push dword %1                   ; CPU already pushed the error code
        jmp isr_common_stub
%endmacro

%macro IRQ 2
    global irq%1
    irq%1:
        push dword 0
        push dword %2
        jmp irq_common_stub
%endmacro

section .text

; ---------------------------------------------------- CPU exceptions 0..31 ---
ISR_NOERRCODE 0     ; #DE Divide-by-zero
ISR_NOERRCODE 1     ; #DB Debug
ISR_NOERRCODE 2     ;     NMI
ISR_NOERRCODE 3     ; #BP Breakpoint
ISR_NOERRCODE 4     ; #OF Overflow
ISR_NOERRCODE 5     ; #BR Bound range
ISR_NOERRCODE 6     ; #UD Invalid opcode
ISR_NOERRCODE 7     ; #NM Device not available
ISR_ERRCODE   8     ; #DF Double fault
ISR_NOERRCODE 9     ;     Coprocessor segment overrun
ISR_ERRCODE   10    ; #TS Invalid TSS
ISR_ERRCODE   11    ; #NP Segment not present
ISR_ERRCODE   12    ; #SS Stack fault
ISR_ERRCODE   13    ; #GP General protection
ISR_ERRCODE   14    ; #PF Page fault
ISR_NOERRCODE 15    ;     reserved
ISR_NOERRCODE 16    ; #MF x87 FP
ISR_ERRCODE   17    ; #AC Alignment check
ISR_NOERRCODE 18    ; #MC Machine check
ISR_NOERRCODE 19    ; #XM SIMD FP
ISR_NOERRCODE 20    ; #VE Virtualization
ISR_ERRCODE   21    ; #CP Control protection
ISR_NOERRCODE 22
ISR_NOERRCODE 23
ISR_NOERRCODE 24
ISR_NOERRCODE 25
ISR_NOERRCODE 26
ISR_NOERRCODE 27
ISR_NOERRCODE 28
ISR_ERRCODE   29    ; #VC VMM communication
ISR_ERRCODE   30    ; #SX Security
ISR_NOERRCODE 31

; -------------------------------------------------- hardware IRQs 32..47 ---
IRQ 0, 32           ; PIT timer
IRQ 1, 33           ; keyboard
IRQ 2, 34           ; cascade
IRQ 3, 35           ; COM2
IRQ 4, 36           ; COM1
IRQ 5, 37           ; LPT2
IRQ 6, 38           ; floppy
IRQ 7, 39           ; LPT1 / spurious
IRQ 8, 40           ; RTC
IRQ 9, 41
IRQ 10, 42
IRQ 11, 43
IRQ 12, 44          ; PS/2 mouse
IRQ 13, 45          ; FPU
IRQ 14, 46          ; primary ATA
IRQ 15, 47          ; secondary ATA

; ------------------------------------------------------------ common stubs ---
%macro SAVE_CONTEXT 0
    pusha
    push ds
    push es
    push fs
    push gs
    mov ax, KERNEL_DS
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
%endmacro

%macro RESTORE_CONTEXT 0
    pop gs
    pop fs
    pop es
    pop ds
    popa
    add esp, 8                          ; int_no + err_code
%endmacro

isr_common_stub:
    SAVE_CONTEXT
    push esp                            ; interrupt_frame_t *
    call isr_handler
    add esp, 4
    RESTORE_CONTEXT
    iret

irq_common_stub:
    SAVE_CONTEXT
    push esp
    call irq_handler
    add esp, 4
    RESTORE_CONTEXT
    iret

; ------------------------------------------------- INT 0x80 system call -----
; Convention: EAX = number, EBX, ECX, EDX, ESI, EDI = args, EAX = result.
global syscall_int
syscall_int:
    push dword 0
    push dword 0x80
    SAVE_CONTEXT
    push esp                            ; syscall_handler(frame) reads the
    call syscall_handler                ; args from the frame and stores the
    add esp, 4                          ; result into frame->eax
    RESTORE_CONTEXT
    iret

; ------------------------------------------------------ context switching ---
; void switch_context(cpu_context_t *old, cpu_context_t *new)
;   cpu_context_t { u32 esp; }  – we only need to save the kernel ESP: all
;   callee-saved registers and the return address live on the stack.
global switch_context
switch_context:
    mov eax, [esp + 4]                  ; old
    mov edx, [esp + 8]                  ; new
    push ebp
    push ebx
    push esi
    push edi
    pushfd
    test eax, eax
    jz .load
    mov [eax], esp
.load:
    mov esp, [edx]
    popfd
    pop edi
    pop esi
    pop ebx
    pop ebp
    ret

; ------------------------------------------------------------ atomics -------
global atomic_increment                 ; u32 atomic_increment(u32 *p)
atomic_increment:
    mov edx, [esp + 4]
    mov eax, 1
    lock xadd [edx], eax
    inc eax
    ret

global atomic_decrement                 ; u32 atomic_decrement(u32 *p)
atomic_decrement:
    mov edx, [esp + 4]
    mov eax, -1
    lock xadd [edx], eax
    dec eax
    ret

global atomic_exchange                  ; u32 atomic_exchange(u32 *p, u32 v)
atomic_exchange:
    mov ecx, [esp + 4]
    mov eax, [esp + 8]
    xchg [ecx], eax
    ret

global atomic_compare_exchange          ; bool (u32 *p, u32 expected, u32 desired)
atomic_compare_exchange:
    mov edx, [esp + 4]
    mov eax, [esp + 8]
    mov ecx, [esp + 12]
    lock cmpxchg [edx], ecx
    setz al
    movzx eax, al
    ret

; ------------------------------------------------------------ spinlocks -----
global spinlock_acquire
spinlock_acquire:
    mov edx, [esp + 4]
.retry:
    lock bts dword [edx], 0
    jnc .done
.spin:
    pause
    test dword [edx], 1
    jnz .spin
    jmp .retry
.done:
    ret

global spinlock_release
spinlock_release:
    mov edx, [esp + 4]
    mov dword [edx], 0
    ret

; ------------------------------------------------------------ CPU control ---
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
    pushfd
    pop eax
    ret

global set_eflags
set_eflags:
    push dword [esp + 4]
    popfd
    ret

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
    push ecx
    popfd
    xor eax, ecx
    setnz al
    movzx eax, al
    ret

global get_cpuid                        ; void get_cpuid(u32 leaf, u32 out[4])
get_cpuid:
    push ebx
    push edi
    mov eax, [esp + 12]
    mov edi, [esp + 16]
    xor ecx, ecx
    cpuid
    mov [edi], eax
    mov [edi + 4], ebx
    mov [edi + 8], ecx
    mov [edi + 12], edx
    pop edi
    pop ebx
    ret

global read_tsc                         ; u64 read_tsc(void)  -> EDX:EAX
read_tsc:
    rdtsc
    ret

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

global load_gdt                         ; void load_gdt(gdt_ptr_t *p)
load_gdt:
    mov eax, [esp + 4]
    lgdt [eax]
    mov ax, KERNEL_DS
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov ss, ax
    jmp 0x08:.flush
.flush:
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

; ------------------------------------------------------------ memory ops ----
global fast_memcpy                      ; void fast_memcpy(void *d, const void *s, u32 n)
fast_memcpy:
    push edi
    push esi
    mov edi, [esp + 12]
    mov esi, [esp + 16]
    mov ecx, [esp + 20]
    cld
    mov edx, ecx
    shr ecx, 2
    rep movsd
    mov ecx, edx
    and ecx, 3
    rep movsb
    pop esi
    pop edi
    ret

global fast_memset                      ; void fast_memset(void *d, u8 v, u32 n)
fast_memset:
    push edi
    mov edi, [esp + 8]
    movzx eax, byte [esp + 12]
    mov ecx, [esp + 16]
    mov edx, ecx
    imul eax, 0x01010101
    cld
    shr ecx, 2
    rep stosd
    mov ecx, edx
    and ecx, 3
    rep stosb
    pop edi
    ret

section .note.GNU-stack noalloc noexec nowrite progbits
