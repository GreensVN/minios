#!/bin/bash
################################################################################
# MiniOS v3.0 - All-in-One Setup Script
# Description: Creates all files and builds a bootable OS in one go!
# Usage: curl -sSL <url> | bash
#        or: bash setup_minios.sh
################################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
cat << "EOF"
╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║     ███╗   ███╗██╗███╗   ██╗██╗     ██████╗ ███████╗         ║
║     ████╗ ████║██║████╗  ██║██║    ██╔═══██╗██╔════╝         ║
║     ██╔████╔██║██║██╔██╗ ██║██║    ██║   ██║███████╗         ║
║     ██║╚██╔╝██║██║██║╚██╗██║██║    ██║   ██║╚════██║         ║
║     ██║ ╚═╝ ██║██║██║ ╚████║██║    ╚██████╔╝███████║         ║
║     ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝╚═╝     ╚═════╝ ╚══════╝         ║
║                                                                ║
║              All-in-One Setup Script v3.0                      ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

echo -e "${GREEN}This script will:${NC}"
echo "  1. Check and install dependencies"
echo "  2. Create all required source files"
echo "  3. Build the operating system"
echo "  4. Run it in QEMU"
echo ""
echo -e "${YELLOW}Press Enter to continue or Ctrl+C to cancel...${NC}"
read

# Check OS
if [ "$(uname)" == "Darwin" ]; then
    OS_TYPE="macos"
    PACKAGE_MANAGER="brew"
elif [ -f /etc/debian_version ]; then
    OS_TYPE="debian"
    PACKAGE_MANAGER="apt"
elif [ -f /etc/arch-release ]; then
    OS_TYPE="arch"
    PACKAGE_MANAGER="pacman"
else
    OS_TYPE="unknown"
fi

echo -e "${BLUE}[*] Detected OS: $OS_TYPE${NC}"

# Check and install dependencies
echo -e "${BLUE}[*] Checking dependencies...${NC}"

DEPS_MISSING=0

if ! command -v nasm &> /dev/null; then
    echo -e "${YELLOW}  - nasm: NOT FOUND${NC}"
    DEPS_MISSING=1
else
    echo -e "${GREEN}  ✓ nasm: $(nasm --version | head -1)${NC}"
fi

if ! command -v gcc &> /dev/null; then
    echo -e "${YELLOW}  - gcc: NOT FOUND${NC}"
    DEPS_MISSING=1
else
    echo -e "${GREEN}  ✓ gcc: $(gcc --version | head -1)${NC}"
fi

if ! command -v ld &> /dev/null; then
    echo -e "${YELLOW}  - ld: NOT FOUND${NC}"
    DEPS_MISSING=1
else
    echo -e "${GREEN}  ✓ ld: $(ld --version | head -1)${NC}"
fi

if ! command -v qemu-system-i386 &> /dev/null && ! command -v qemu-system-x86_64 &> /dev/null; then
    echo -e "${YELLOW}  - qemu: NOT FOUND${NC}"
    DEPS_MISSING=1
else
    echo -e "${GREEN}  ✓ qemu: FOUND${NC}"
fi

if [ $DEPS_MISSING -eq 1 ]; then
    echo ""
    echo -e "${YELLOW}Some dependencies are missing. Install them? (y/n)${NC}"
    read -r install_deps
    
    if [ "$install_deps" = "y" ]; then
        echo -e "${BLUE}[*] Installing dependencies...${NC}"
        
        case $PACKAGE_MANAGER in
            apt)
                sudo apt update
                sudo apt install -y build-essential nasm gcc binutils qemu-system-x86
                ;;
            pacman)
                sudo pacman -S --noconfirm base-devel nasm gcc qemu
                ;;
            brew)
                brew install nasm qemu
                ;;
            *)
                echo -e "${RED}Please install manually: nasm, gcc, ld, qemu-system-i386${NC}"
                exit 1
                ;;
        esac
        
        echo -e "${GREEN}✓ Dependencies installed${NC}"
    else
        echo -e "${RED}Cannot proceed without dependencies${NC}"
        exit 1
    fi
fi

# Create project directory
PROJECT_DIR="minios_v3"
echo ""
echo -e "${BLUE}[*] Creating project directory: $PROJECT_DIR${NC}"
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

# Create build directories
mkdir -p build output iso/boot/grub

echo -e "${GREEN}✓ Directories created${NC}"

# Create bootloader.asm
echo -e "${BLUE}[*] Creating bootloader.asm...${NC}"
cat > bootloader.asm << 'BOOTLOADER_EOF'
; MiniOS Real Bootloader v3.0
[BITS 16]
[ORG 0x7C00]

KERNEL_OFFSET equ 0x1000
KERNEL_SECTOR equ 2
KERNEL_SECTORS equ 64

boot_start:
    cli
    cld
    mov [boot_drive], dl
    
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7C00
    sti
    
    call clear_screen
    mov si, msg_banner
    call print_string
    
    call enable_a20
    
    mov si, msg_loading
    call print_string
    call load_kernel
    jc disk_error
    
    mov si, msg_kernel_ok
    call print_string
    
    lgdt [gdt_descriptor]
    
    cli
    mov eax, cr0
    or eax, 1
    mov cr0, eax
    
    jmp 0x08:protected_mode_entry

enable_a20:
    mov ax, 0x2401
    int 0x15
    ret

load_kernel:
    mov si, msg_loading
    call print_string
    
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
    jc .error
    
    pop es
    clc
    ret

.error:
    pop es
    stc
    ret

disk_error:
    mov si, msg_disk_error
    call print_string
    cli
    hlt
    jmp $

clear_screen:
    pusha
    mov ah, 0x06
    xor al, al
    xor cx, cx
    mov dx, 0x184F
    mov bh, 0x0F
    int 0x10
    
    mov ah, 0x02
    xor bh, bh
    xor dx, dx
    int 0x10
    popa
    ret

print_string:
    pusha
    mov ah, 0x0E
    mov bh, 0
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

boot_drive: db 0

msg_banner:     db 0x0A, 0x0D, '  MiniOS v3.0 Bootloader', 0x0A, 0x0D, 0
msg_loading:    db '[*] Loading kernel...', 0x0A, 0x0D, 0
msg_kernel_ok:  db '[OK] Kernel loaded', 0x0A, 0x0D, 0
msg_disk_error: db '[FAIL] Disk read error!', 0x0A, 0x0D, 0

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

CODE_SEG equ gdt_code - gdt_start
DATA_SEG equ gdt_data - gdt_start

[BITS 32]
protected_mode_entry:
    mov ax, DATA_SEG
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov ss, ax
    mov esp, 0x90000
    
    mov edi, 0xB8000
    mov ecx, 2000
    mov ax, 0x0F20
    rep stosw
    
    mov esi, pm_message
    mov edi, 0xB8000
    mov ah, 0x0A

.print_loop:
    lodsb
    test al, al
    jz .done
    stosw
    jmp .print_loop

.done:
    call KERNEL_OFFSET
    cli
    hlt
    jmp $

pm_message: db 'Protected Mode - Starting Kernel...', 0

times 510-($-$$) db 0
dw 0xAA55
BOOTLOADER_EOF

echo -e "${GREEN}✓ bootloader.asm created${NC}"

# Create kernel.c (simplified version for quick setup)
echo -e "${BLUE}[*] Creating kernel.c...${NC}"
cat > kernel.c << 'KERNEL_EOF'
/* MiniOS Real Kernel v3.0 */
#include <stdint.h>
#include <stddef.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;

#define VGA_MEMORY ((volatile u16*)0xB8000)
#define VGA_WIDTH 80
#define VGA_HEIGHT 25

static u8 cursor_x = 0;
static u8 cursor_y = 0;
static u8 terminal_color = 0x0F;

static inline void outb(u16 port, u8 val) {
    __asm__ volatile ("outb %0, %1" : : "a"(val), "Nd"(port));
}

static inline u8 inb(u16 port) {
    u8 ret;
    __asm__ volatile ("inb %1, %0" : "=a"(ret) : "Nd"(port));
    return ret;
}

void *memset(void *dest, int val, size_t len) {
    u8 *ptr = (u8*)dest;
    while (len--) *ptr++ = val;
    return dest;
}

size_t strlen(const char *str) {
    size_t len = 0;
    while (str[len]) len++;
    return len;
}

void terminal_initialize(void) {
    for (size_t y = 0; y < VGA_HEIGHT; y++) {
        for (size_t x = 0; x < VGA_WIDTH; x++) {
            VGA_MEMORY[y * VGA_WIDTH + x] = 0x0F20;
        }
    }
    cursor_x = 0;
    cursor_y = 0;
}

void terminal_scroll(void) {
    for (size_t y = 0; y < VGA_HEIGHT - 1; y++) {
        for (size_t x = 0; x < VGA_WIDTH; x++) {
            VGA_MEMORY[y * VGA_WIDTH + x] = VGA_MEMORY[(y + 1) * VGA_WIDTH + x];
        }
    }
    for (size_t x = 0; x < VGA_WIDTH; x++) {
        VGA_MEMORY[(VGA_HEIGHT - 1) * VGA_WIDTH + x] = 0x0F20;
    }
    cursor_y = VGA_HEIGHT - 1;
}

void terminal_putchar(char c) {
    if (c == '\n') {
        cursor_x = 0;
        if (++cursor_y >= VGA_HEIGHT)
            terminal_scroll();
    } else {
        VGA_MEMORY[cursor_y * VGA_WIDTH + cursor_x] = (terminal_color << 8) | c;
        if (++cursor_x >= VGA_WIDTH) {
            cursor_x = 0;
            if (++cursor_y >= VGA_HEIGHT)
                terminal_scroll();
        }
    }
}

void terminal_writestring(const char *data) {
    for (size_t i = 0; i < strlen(data); i++)
        terminal_putchar(data[i]);
}

void terminal_writeline(const char *data) {
    terminal_writestring(data);
    terminal_putchar('\n');
}

void kernel_main(void) {
    terminal_initialize();
    
    terminal_color = 0x0B;
    terminal_writeline("================================================================");
    terminal_writeline("           MiniOS v3.0 Real Kernel - Hardware Ready            ");
    terminal_writeline("================================================================");
    terminal_color = 0x0F;
    terminal_putchar('\n');
    
    terminal_color = 0x0A;
    terminal_writeline("[OK] Kernel initialized");
    terminal_writeline("[OK] VGA text mode active");
    terminal_writeline("[OK] System ready!");
    
    terminal_color = 0x0E;
    terminal_putchar('\n');
    terminal_writeline("Successfully booted MiniOS on real hardware!");
    terminal_writeline("This is a real operating system running in protected mode.");
    terminal_putchar('\n');
    
    terminal_color = 0x07;
    terminal_writestring("Kernel address: 0x00001000\n");
    terminal_writestring("VGA buffer: 0xB8000\n");
    
    while (1) {
        __asm__ volatile ("hlt");
    }
}

void __stack_chk_fail(void) {
    terminal_color = 0x4F;
    terminal_writeline("\n[PANIC] Stack smashing detected!");
    __asm__ volatile ("cli; hlt");
    for(;;);
}

void *__stack_chk_guard = (void*)0xDEADBEEF;
KERNEL_EOF

echo -e "${GREEN}✓ kernel.c created${NC}"

# Create linker.ld
echo -e "${BLUE}[*] Creating linker.ld...${NC}"
cat > linker.ld << 'LINKER_EOF'
OUTPUT_FORMAT("elf32-i386")
OUTPUT_ARCH("i386")
ENTRY(kernel_main)

SECTIONS
{
    . = 0x1000;
    _kernel_start = .;
    
    .text ALIGN(4K) : {
        *(.multiboot)
        *(.text)
        *(.text.*)
    }
    
    .rodata ALIGN(4K) : {
        *(.rodata)
        *(.rodata.*)
    }
    
    .data ALIGN(4K) : {
        *(.data)
        *(.data.*)
    }
    
    .bss ALIGN(4K) : {
        _bss_start = .;
        *(COMMON)
        *(.bss)
        *(.bss.*)
        _bss_end = .;
    }
    
    _kernel_end = .;
    
    /DISCARD/ : {
        *(.comment)
        *(.eh_frame)
        *(.note.gnu.build-id)
    }
}
LINKER_EOF

echo -e "${GREEN}✓ linker.ld created${NC}"

# Create Makefile
echo -e "${BLUE}[*] Creating Makefile...${NC}"
cat > Makefile << 'MAKEFILE_EOF'
ASM = nasm
CC = gcc
LD = ld
QEMU = qemu-system-i386

ASMFLAGS = -f bin
CFLAGS = -m32 -c -ffreestanding -fno-pie -O2 -Wall -nostdlib -nostdinc -fno-builtin -fno-stack-protector
LDFLAGS = -m elf_i386 -nostdlib -T linker.ld

BOOTLOADER_BIN = build/bootloader.bin
KERNEL_OBJ = build/kernel.o
KERNEL_BIN = build/kernel.bin
DISK_IMAGE = output/minios.img

.PHONY: all clean run

all: $(DISK_IMAGE)
    @echo "✓ Build complete!"

$(BOOTLOADER_BIN): bootloader.asm
    @echo "[*] Assembling bootloader..."
    @$(ASM) $(ASMFLAGS) $< -o $@

$(KERNEL_OBJ): kernel.c
    @echo "[*] Compiling kernel..."
    @$(CC) $(CFLAGS) $< -o $@

$(KERNEL_BIN): $(KERNEL_OBJ) linker.ld
    @echo "[*] Linking kernel..."
    @$(LD) $(LDFLAGS) $(KERNEL_OBJ) -o $@

$(DISK_IMAGE): $(BOOTLOADER_BIN) $(KERNEL_BIN)
    @echo "[*] Creating disk image..."
    @dd if=/dev/zero of=$@ bs=512 count=40960 2>/dev/null
    @dd if=$(BOOTLOADER_BIN) of=$@ conv=notrunc bs=512 count=1 2>/dev/null
    @dd if=$(KERNEL_BIN) of=$@ seek=2 conv=notrunc bs=512 2>/dev/null

run: $(DISK_IMAGE)
    @echo "[*] Starting QEMU..."
    @$(QEMU) -drive file=$(DISK_IMAGE),format=raw -m 256M

clean:
    @rm -rf build output
    @echo "✓ Clean complete"
MAKEFILE_EOF

echo -e "${GREEN}✓ Makefile created${NC}"

# Create README
echo -e "${BLUE}[*] Creating README.md...${NC}"
cat > README.md << 'README_EOF'
# MiniOS v3.0 - Real Operating System

## Quick Start

```bash
make        # Build OS
make run    # Run in QEMU
```

## Boot to USB

```bash
# ⚠️ WARNING: Will erase USB drive!
sudo dd if=output/minios.img of=/dev/sdX bs=4M status=progress
sudo sync
```

Then boot from USB!

## Files

- `bootloader.asm` - Stage 1 bootloader (512 bytes)
- `kernel.c` - Main kernel
- `linker.ld` - Linker script
- `Makefile` - Build system

## Requirements

- nasm
- gcc (32-bit)
- ld
- qemu-system-i386

## Success!

You've built a real OS that boots on hardware! 🎉
README_EOF

echo -e "${GREEN}✓ README.md created${NC}"

# Build the OS
echo ""
echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                 Building MiniOS...                             ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

make

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                 BUILD SUCCESSFUL! 🎉                            ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

echo -e "${YELLOW}Your OS is ready! Here's what you can do:${NC}"
echo ""
echo -e "${CYAN}1. Run in QEMU:${NC}"
echo "   make run"
echo ""
echo -e "${CYAN}2. Create bootable USB:${NC}"
echo "   sudo dd if=output/minios.img of=/dev/sdX bs=4M"
echo "   (Replace /dev/sdX with your USB device)"
echo ""
echo -e "${CYAN}3. Boot on real hardware:${NC}"
echo "   - Write to USB (step 2)"
echo "   - Insert USB and restart PC"
echo "   - Enter BIOS (F2/F12/Del)"
echo "   - Boot from USB"
echo ""

echo -e "${YELLOW}Start QEMU now? (y/n)${NC}"
read -r start_qemu

if [ "$start_qemu" = "y" ]; then
    echo -e "${CYAN}Starting QEMU...${NC}"
    echo -e "${YELLOW}(Press Ctrl+Alt+G to release mouse, close window to exit)${NC}"
    sleep 2
    make run
fi

echo ""
echo -e "${GREEN}All done! Your OS is in: $(pwd)${NC}"
echo -e "${GREEN}Enjoy your operating system! 🚀${NC}"