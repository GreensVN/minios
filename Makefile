# Makefile for MiniOS v4.0 ULTIMATE
# Complete build system with all features

# ========== Toolchain ==========
ASM := nasm
CC := gcc
CXX := g++
LD := ld
JAVAC := javac
PYTHON := python3
CSC := mcs
QEMU := qemu-system-i386
GRUB_MKRESCUE := grub-mkrescue
OBJCOPY := objcopy
OBJDUMP := objdump

# ========== Flags ==========
ASMFLAGS := -f bin
ASMFLAGS_ELF := -f elf32
CFLAGS := -m32 -c -ffreestanding -fno-pie -fno-stack-protector \
          -O2 -Wall -Wextra -nostdlib -nostdinc -fno-builtin \
          -mno-red-zone -mno-mmx -mno-sse -mno-sse2 \
          -fno-strict-aliasing -fno-common
CXXFLAGS := $(CFLAGS) -fno-exceptions -fno-rtti
LDFLAGS := -m elf_i386 -nostdlib -T linker.ld
QEMUFLAGS := -m 256M -rtc base=localtime -boot d

# ========== Directories ==========
BUILD_DIR := build
OUTPUT_DIR := output
ISO_DIR := iso
ISO_BOOT := $(ISO_DIR)/boot
ISO_GRUB := $(ISO_BOOT)/grub
DOCS_DIR := docs
TESTS_DIR := tests
SRC_DIR := src

# ========== Source Files ==========
BOOTLOADER_SRC := bootloader_ultimate.asm
KERNEL_SRC := kernel_v4_ultimate.c
INTERRUPTS_SRC := interrupts_complete.asm
LINKER_SCRIPT := linker.ld

# ========== Build Targets ==========
BOOTLOADER_BIN := $(BUILD_DIR)/bootloader.bin
KERNEL_OBJ := $(BUILD_DIR)/kernel.o
INTERRUPTS_OBJ := $(BUILD_DIR)/interrupts.o
KERNEL_ELF := $(BUILD_DIR)/kernel.elf
KERNEL_BIN := $(BUILD_DIR)/kernel.bin
DISK_IMAGE := $(OUTPUT_DIR)/minios.img
ISO_IMAGE := $(OUTPUT_DIR)/minios.iso

# ========== Colors ==========
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[1;33m
BLUE := \033[0;34m
CYAN := \033[0;36m
MAGENTA := \033[0;35m
NC := \033[0m

# ========== Default Target ==========
.PHONY: all
all: banner check-deps directories bootloader kernel disk-image success

# ========== Banner ==========
.PHONY: banner
banner:
	@echo "$(CYAN)"
	@echo "╔════════════════════════════════════════════════════════════════╗"
	@echo "║                                                                ║"
	@echo "║     ███╗   ███╗██╗███╗   ██╗██╗     ██████╗ ███████╗         ║"
	@echo "║     ████╗ ████║██║████╗  ██║██║    ██╔═══██╗██╔════╝         ║"
	@echo "║     ██╔████╔██║██║██╔██╗ ██║██║    ██║   ██║███████╗         ║"
	@echo "║     ██║╚██╔╝██║██║██║╚██╗██║██║    ██║   ██║╚════██║         ║"
	@echo "║     ██║ ╚═╝ ██║██║██║ ╚████║██║    ╚██████╔╝███████║         ║"
	@echo "║     ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝╚═╝     ╚═════╝ ╚══════╝         ║"
	@echo "║                                                                ║"
	@echo "║              Build System v4.0 ULTIMATE                        ║"
	@echo "║                                                                ║"
	@echo "╚════════════════════════════════════════════════════════════════╝"
	@echo "$(NC)"

# ========== Check Dependencies ==========
.PHONY: check-deps
check-deps:
	@echo "$(BLUE)[*] Checking dependencies...$(NC)"
	@command -v $(ASM) >/dev/null 2>&1 || { echo "$(RED)[✗] nasm not found$(NC)"; exit 1; }
	@command -v $(CC) >/dev/null 2>&1 || { echo "$(RED)[✗] gcc not found$(NC)"; exit 1; }
	@command -v $(LD) >/dev/null 2>&1 || { echo "$(RED)[✗] ld not found$(NC)"; exit 1; }
	@command -v $(QEMU) >/dev/null 2>&1 || echo "$(YELLOW)[!] qemu not found (optional)$(NC)"
	@echo "$(GREEN)[✓] All required dependencies found$(NC)"

# ========== Create Directories ==========
.PHONY: directories
directories:
	@mkdir -p $(BUILD_DIR) $(OUTPUT_DIR) $(ISO_DIR) $(ISO_BOOT) $(ISO_GRUB)
	@mkdir -p $(DOCS_DIR) $(TESTS_DIR)

# ========== Bootloader ==========
.PHONY: bootloader
bootloader: $(BOOTLOADER_BIN)

$(BOOTLOADER_BIN): $(BOOTLOADER_SRC) | directories
	@echo "$(BLUE)[*] Assembling bootloader...$(NC)"
	@$(ASM) $(ASMFLAGS) $< -o $@
	@echo "$(GREEN)[✓] Bootloader: $@ ($(shell ls -lh $@ | awk '{print $$5}'))$(NC)"

# ========== Kernel ==========
.PHONY: kernel
kernel: $(KERNEL_BIN)

$(INTERRUPTS_OBJ): $(INTERRUPTS_SRC) | directories
	@echo "$(BLUE)[*] Assembling interrupt handlers...$(NC)"
	@$(ASM) $(ASMFLAGS_ELF) $< -o $@
	@echo "$(GREEN)[✓] Interrupts: $@$(NC)"

$(KERNEL_OBJ): $(KERNEL_SRC) | directories
	@echo "$(BLUE)[*] Compiling kernel...$(NC)"
	@$(CC) $(CFLAGS) $< -o $@
	@echo "$(GREEN)[✓] Kernel object: $@$(NC)"

$(KERNEL_ELF): $(KERNEL_OBJ) $(INTERRUPTS_OBJ) $(LINKER_SCRIPT) | directories
	@echo "$(BLUE)[*] Linking kernel...$(NC)"
	@$(LD) $(LDFLAGS) $(KERNEL_OBJ) $(INTERRUPTS_OBJ) -o $@
	@echo "$(GREEN)[✓] Kernel ELF: $@$(NC)"

$(KERNEL_BIN): $(KERNEL_ELF)
	@echo "$(BLUE)[*] Creating kernel binary...$(NC)"
	@$(OBJCOPY) -O binary $< $@
	@echo "$(GREEN)[✓] Kernel binary: $@ ($(shell ls -lh $@ | awk '{print $$5}'))$(NC)"

# ========== Disk Image ==========
.PHONY: disk-image
disk-image: $(DISK_IMAGE)

$(DISK_IMAGE): $(BOOTLOADER_BIN) $(KERNEL_BIN) | directories
	@echo "$(BLUE)[*] Creating disk image...$(NC)"
	@dd if=/dev/zero of=$@ bs=512 count=40960 status=none 2>/dev/null
	@dd if=$(BOOTLOADER_BIN) of=$@ conv=notrunc bs=512 count=1 status=none 2>/dev/null
	@dd if=$(KERNEL_BIN) of=$@ seek=2 conv=notrunc bs=512 status=none 2>/dev/null
	@echo "$(GREEN)[✓] Disk image: $@ (20 MB)$(NC)"

# ========== ISO Image ==========
.PHONY: iso
iso: $(ISO_IMAGE)

$(ISO_GRUB)/grub.cfg: | directories
	@echo "$(BLUE)[*] Creating GRUB configuration...$(NC)"
	@echo "set timeout=5" > $@
	@echo "set default=0" >> $@
	@echo "" >> $@
	@echo "menuentry \"MiniOS v4.0 ULTIMATE\" {" >> $@
	@echo "    multiboot /boot/kernel.bin" >> $@
	@echo "    boot" >> $@
	@echo "}" >> $@

$(ISO_IMAGE): $(KERNEL_BIN) $(ISO_GRUB)/grub.cfg | directories
	@echo "$(BLUE)[*] Creating ISO image...$(NC)"
	@cp $(KERNEL_BIN) $(ISO_BOOT)/kernel.bin
	@$(GRUB_MKRESCUE) -o $@ $(ISO_DIR) 2>/dev/null || \
		echo "$(YELLOW)[!] grub-mkrescue not available$(NC)"
	@echo "$(GREEN)[✓] ISO image: $@$(NC)"

# ========== Run Targets ==========
.PHONY: run
run: $(DISK_IMAGE)
	@echo "$(CYAN)[*] Starting QEMU...$(NC)"
	@echo "$(YELLOW)[!] Press Ctrl+Alt+G to release mouse$(NC)"
	@echo "$(YELLOW)[!] Close window to exit$(NC)"
	@echo ""
	@$(QEMU) -drive file=$(DISK_IMAGE),format=raw $(QEMUFLAGS)

.PHONY: run-iso
run-iso: $(ISO_IMAGE)
	@echo "$(CYAN)[*] Starting QEMU with ISO...$(NC)"
	@$(QEMU) -cdrom $(ISO_IMAGE) $(QEMUFLAGS)

.PHONY: run-debug
run-debug: $(DISK_IMAGE)
	@echo "$(CYAN)[*] Starting QEMU in debug mode...$(NC)"
	@echo "$(YELLOW)[!] Connect GDB to localhost:1234$(NC)"
	@$(QEMU) -drive file=$(DISK_IMAGE),format=raw $(QEMUFLAGS) -s -S

.PHONY: run-serial
run-serial: $(DISK_IMAGE)
	@echo "$(CYAN)[*] Starting QEMU with serial output...$(NC)"
	@$(QEMU) -drive file=$(DISK_IMAGE),format=raw $(QEMUFLAGS) -serial stdio

.PHONY: run-vnc
run-vnc: $(DISK_IMAGE)
	@echo "$(CYAN)[*] Starting QEMU with VNC on :0...$(NC)"
	@$(QEMU) -drive file=$(DISK_IMAGE),format=raw $(QEMUFLAGS) -vnc :0

# ========== Debug Targets ==========
.PHONY: debug
debug: $(KERNEL_ELF)
	@echo "$(CYAN)[*] Starting GDB...$(NC)"
	@gdb -ex "target remote localhost:1234" \
	     -ex "symbol-file $(KERNEL_ELF)" \
	     -ex "break kernel_main" \
	     -ex "layout src"

.PHONY: disassemble
disassemble: $(KERNEL_ELF)
	@echo "$(CYAN)[*] Disassembling kernel...$(NC)"
	@$(OBJDUMP) -d $(KERNEL_ELF) > $(BUILD_DIR)/kernel.asm
	@echo "$(GREEN)[✓] Disassembly: $(BUILD_DIR)/kernel.asm$(NC)"

.PHONY: symbols
symbols: $(KERNEL_ELF)
	@echo "$(CYAN)[*] Extracting symbols...$(NC)"
	@nm $(KERNEL_ELF) > $(BUILD_DIR)/kernel.sym
	@echo "$(GREEN)[✓] Symbols: $(BUILD_DIR)/kernel.sym$(NC)"

.PHONY: hexdump
hexdump: $(DISK_IMAGE)
	@echo "$(CYAN)[*] Hex dump of boot sector:$(NC)"
	@hexdump -C $(DISK_IMAGE) | head -n 32

# ========== USB Boot ==========
.PHONY: usb-info
usb-info:
	@echo "$(YELLOW)╔════════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(YELLOW)║              USB Boot Instructions                            ║$(NC)"
	@echo "$(YELLOW)╚════════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(RED)⚠️  WARNING: This will ERASE all data on the USB drive!$(NC)"
	@echo ""
	@echo "1. Find your USB device:"
	@echo "   $(CYAN)lsblk$(NC) or $(CYAN)sudo fdisk -l$(NC)"
	@echo ""
	@echo "2. Write image (replace /dev/sdX with your USB device):"
	@echo "   $(CYAN)sudo dd if=$(DISK_IMAGE) of=/dev/sdX bs=4M status=progress$(NC)"
	@echo "   $(CYAN)sudo sync$(NC)"
	@echo ""
	@echo "3. Boot from USB"
	@echo ""

.PHONY: usb-write
usb-write: $(DISK_IMAGE)
	@echo "$(RED)⚠️  This will write to USB device!$(NC)"
	@echo -n "Enter USB device (e.g., /dev/sdb): "
	@read device; \
	if [ -b "$$device" ]; then \
		echo "$(YELLOW)Writing to $$device...$(NC)"; \
		sudo dd if=$(DISK_IMAGE) of=$$device bs=4M status=progress && \
		sudo sync && \
		echo "$(GREEN)[✓] USB written successfully$(NC)"; \
	else \
		echo "$(RED)[✗] Invalid device: $$device$(NC)"; \
	fi

# ========== Statistics ==========
.PHONY: stats
stats: $(KERNEL_ELF)
	@echo "$(CYAN)╔════════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(CYAN)║                   Build Statistics                             ║$(NC)"
	@echo "$(CYAN)╚════════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(YELLOW)Bootloader:$(NC)"
	@ls -lh $(BOOTLOADER_BIN) 2>/dev/null | awk '{print "  Size: " $$5}'
	@echo ""
	@echo "$(YELLOW)Kernel:$(NC)"
	@size $(KERNEL_ELF) 2>/dev/null || true
	@ls -lh $(KERNEL_BIN) 2>/dev/null | awk '{print "  Binary size: " $$5}'
	@echo ""
	@echo "$(YELLOW)Disk Image:$(NC)"
	@ls -lh $(DISK_IMAGE) 2>/dev/null | awk '{print "  Size: " $$5}'
	@echo ""
	@echo "$(YELLOW)Source Files:$(NC)"
	@wc -l *.asm *.c *.h 2>/dev/null | tail -n 1 | awk '{print "  Total lines: " $$1}' || true
	@echo ""

# ========== Test ==========
.PHONY: test
test: $(DISK_IMAGE)
	@echo "$(CYAN)[*] Running tests...$(NC)"
	@echo "$(BLUE)[TEST] Boot signature...$(NC)"
	@hexdump -n 2 -s 510 -e '/1 "%02x"' $(BOOTLOADER_BIN) | grep -q "55aa" && \
		echo "$(GREEN)[✓] Boot signature valid$(NC)" || \
		echo "$(RED)[✗] Boot signature invalid$(NC)"
	@echo "$(BLUE)[TEST] Kernel magic...$(NC)"
	@hexdump -n 4 -e '/4 "%08x\n"' $(KERNEL_BIN) | grep -q "deadbeef" && \
		echo "$(GREEN)[✓] Kernel magic valid$(NC)" || \
		echo "$(YELLOW)[!] Kernel magic not found$(NC)"

# ========== Clean ==========
.PHONY: clean
clean:
	@echo "$(YELLOW)[*] Cleaning build files...$(NC)"
	@rm -rf $(BUILD_DIR) $(OUTPUT_DIR)
	@echo "$(GREEN)[✓] Clean complete$(NC)"

.PHONY: distclean
distclean: clean
	@echo "$(YELLOW)[*] Removing all generated files...$(NC)"
	@rm -rf $(ISO_DIR)
	@echo "$(GREEN)[✓] Distclean complete$(NC)"

# ========== Success Message ==========
.PHONY: success
success:
	@echo ""
	@echo "$(GREEN)╔════════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(GREEN)║                 BUILD SUCCESSFUL! 🎉                            ║$(NC)"
	@echo "$(GREEN)╚════════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(CYAN)Your OS is ready!$(NC)"
	@echo ""
	@echo "$(YELLOW)Quick Start:$(NC)"
	@echo "  $(CYAN)make run$(NC)         - Run in QEMU"
	@echo "  $(CYAN)make run-debug$(NC)   - Run with GDB"
	@echo "  $(CYAN)make stats$(NC)       - Show statistics"
	@echo "  $(CYAN)make usb-info$(NC)    - USB boot instructions"
	@echo ""

# ========== Help ==========
.PHONY: help
help:
	@echo "$(CYAN)╔════════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(CYAN)║                   MiniOS v4.0 ULTIMATE                         ║$(NC)"
	@echo "$(CYAN)╚════════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(YELLOW)Build Targets:$(NC)"
	@echo "  all             - Build everything"
	@echo "  bootloader      - Build bootloader only"
	@echo "  kernel          - Build kernel only"
	@echo "  disk-image      - Create disk image"
	@echo "  iso             - Create ISO image"
	@echo ""
	@echo "$(YELLOW)Run Targets:$(NC)"
	@echo "  run             - Run in QEMU"
	@echo "  run-iso         - Run ISO in QEMU"
	@echo "  run-debug       - Run with GDB support"
	@echo "  run-serial      - Run with serial output"
	@echo ""
	@echo "$(YELLOW)Debug Targets:$(NC)"
	@echo "  debug           - Start GDB session"
	@echo "  disassemble     - Disassemble kernel"
	@echo "  symbols         - Extract symbol table"
	@echo "  hexdump         - Hex dump of disk image"
	@echo ""
	@echo "$(YELLOW)Utility Targets:$(NC)"
	@echo "  stats           - Show build statistics"
	@echo "  test            - Run tests"
	@echo "  usb-info        - USB boot instructions"
	@echo "  clean           - Remove build files"
	@echo "  distclean       - Remove all generated files"
	@echo ""

.PHONY: info
info: help

.PHONY: version
version:
	@echo "MiniOS Build System v4.0 ULTIMATE"
	@echo "Copyright (c) 2024 MiniOS Project"