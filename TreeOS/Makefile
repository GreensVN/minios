# =============================================================================
#  Makefile - MiniOS v4.1
#
#  make            build bootloader + kernel + disk image (output/minios.img)
#  make run        boot the image in QEMU
#  make run-serial boot with the console mirrored to your terminal (-nographic)
#  make iso        GRUB ISO (needs grub-mkrescue + xorriso)
#  make test       sanity checks on the produced binaries
#  make debug      QEMU + GDB stub on :1234
# =============================================================================

# ---------------------------------------------------------------- toolchain --
CROSS    ?=
ASM      := nasm
CC       := $(CROSS)gcc
LD       := $(CROSS)ld
OBJCOPY  := $(CROSS)objcopy
OBJDUMP  := $(CROSS)objdump
QEMU     ?= qemu-system-i386
GRUB_MKRESCUE ?= grub-mkrescue

# ---------------------------------------------------------------- flags ------
ASMFLAGS_BIN := -f bin
ASMFLAGS_ELF := -f elf32
COMMONFLAGS := -m32 -ffreestanding -fno-pie -fno-pic -fno-stack-protector \
            -fno-builtin -nostdlib -fno-common -fno-strict-aliasing \
            -fno-asynchronous-unwind-tables -mno-red-zone -mno-mmx -mno-sse -mno-sse2 \
            -O2 -Wall -Wextra -MMD -MP
CFLAGS   := $(COMMONFLAGS) -std=gnu11
CXXFLAGS := $(COMMONFLAGS) -std=gnu++17 -fno-exceptions -fno-rtti -fno-threadsafe-statics \
            -fno-use-cxa-atexit -Wno-sized-deallocation
LDFLAGS  := -m elf_i386 -nostdlib -T linker.ld --no-warn-rwx-segments -z noexecstack
QEMUFLAGS ?= -m 256M -serial stdio -no-reboot

# ---------------------------------------------------------------- files ------
BUILD  := build
OUT    := output
ISO    := iso

BOOT_SRC   := Bootloader.asm
ENTRY_SRC  := entry.asm
INTR_SRC   := interrupts.asm
KERNEL_SRC := Kernel.c
DRIVER_SRC := driver_manager.cpp

BOOT_BIN   := $(BUILD)/bootloader.bin
OBJS       := $(BUILD)/entry.o $(BUILD)/kernel.o $(BUILD)/interrupts.o $(BUILD)/driver_manager.o
KERNEL_ELF := $(BUILD)/kernel.elf
KERNEL_BIN := $(BUILD)/kernel.bin
DISK_IMAGE := $(OUT)/minios.img
ISO_IMAGE  := $(OUT)/minios.iso

KERNEL_LBA   := 8          # must match KERNEL_LBA in Bootloader.asm
IMAGE_SECTORS := 16384     # 8 MiB

GREEN := \033[0;32m
BLUE  := \033[0;34m
YEL   := \033[1;33m
RED   := \033[0;31m
NC    := \033[0m

.PHONY: all
all: $(DISK_IMAGE)
	@printf "$(GREEN)[done]$(NC) %s  (kernel %s bytes)\n" "$(DISK_IMAGE)" "$$(stat -c %s $(KERNEL_BIN))"

# ---------------------------------------------------------------- rules ------
$(BUILD) $(OUT):
	@mkdir -p $@

$(BOOT_BIN): $(BOOT_SRC) | $(BUILD)
	@printf "$(BLUE)[asm]$(NC) %s\n" $<
	@$(ASM) $(ASMFLAGS_BIN) $< -o $@

$(BUILD)/%.o: %.asm | $(BUILD)
	@printf "$(BLUE)[asm]$(NC) %s\n" $<
	@$(ASM) $(ASMFLAGS_ELF) $< -o $@

$(BUILD)/kernel.o: $(KERNEL_SRC) kernel.h | $(BUILD)
	@printf "$(BLUE)[cc ]$(NC) %s\n" $<
	@$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/driver_manager.o: $(DRIVER_SRC) driver_manager.h kernel.h | $(BUILD)
	@printf "$(BLUE)[c++]$(NC) %s\n" $<
	@$(CC) $(CXXFLAGS) -c $< -o $@

$(KERNEL_ELF): $(OBJS) linker.ld
	@printf "$(BLUE)[ld ]$(NC) %s\n" $@
	@$(LD) $(LDFLAGS) $(OBJS) -o $@

$(KERNEL_BIN): $(KERNEL_ELF)
	@$(OBJCOPY) -O binary $< $@

$(DISK_IMAGE): $(BOOT_BIN) $(KERNEL_BIN) | $(OUT)
	@printf "$(BLUE)[img]$(NC) %s\n" $@
	@dd if=/dev/zero of=$@ bs=512 count=$(IMAGE_SECTORS) status=none
	@dd if=$(BOOT_BIN)   of=$@ conv=notrunc status=none
	@dd if=$(KERNEL_BIN) of=$@ bs=512 seek=$(KERNEL_LBA) conv=notrunc status=none

# ---------------------------------------------------------------- ISO --------
$(ISO)/boot/grub/grub.cfg:
	@mkdir -p $(dir $@)
	@printf 'set timeout=3\nset default=0\nmenuentry "MiniOS v4.1" {\n    multiboot /boot/kernel.elf\n    boot\n}\n' > $@

.PHONY: iso
iso: $(ISO_IMAGE)
$(ISO_IMAGE): $(KERNEL_ELF) $(ISO)/boot/grub/grub.cfg | $(OUT)
	@cp $(KERNEL_ELF) $(ISO)/boot/kernel.elf
	@$(GRUB_MKRESCUE) -o $@ $(ISO) 2>/dev/null || \
	    { printf "$(RED)[err]$(NC) grub-mkrescue failed (install grub-pc-bin + xorriso)\n"; exit 1; }
	@printf "$(GREEN)[iso]$(NC) %s\n" $@

# ---------------------------------------------------------------- run --------
.PHONY: run run-serial run-iso debug
run: $(DISK_IMAGE)
	$(QEMU) -drive file=$(DISK_IMAGE),format=raw $(QEMUFLAGS)

run-serial: $(DISK_IMAGE)
	$(QEMU) -drive file=$(DISK_IMAGE),format=raw -m 256M -nographic -no-reboot

run-iso: $(ISO_IMAGE)
	$(QEMU) -cdrom $(ISO_IMAGE) $(QEMUFLAGS)

debug: $(DISK_IMAGE)
	@printf "$(YEL)GDB:$(NC) gdb $(KERNEL_ELF) -ex 'target remote :1234'\n"
	$(QEMU) -drive file=$(DISK_IMAGE),format=raw $(QEMUFLAGS) -s -S

# ---------------------------------------------------------------- misc -------
.PHONY: test
test: $(DISK_IMAGE)
	@sig=$$(od -An -tx1 -j510 -N2 $(BOOT_BIN) | tr -d ' \n'); \
	 [ "$$sig" = "55aa" ] && printf "$(GREEN)[ok ]$(NC) boot signature\n" || { printf "$(RED)[!!]$(NC) boot signature $$sig\n"; exit 1; }
	@sz=$$(stat -c %s $(BOOT_BIN)); [ "$$sz" = 4096 ] && printf "$(GREEN)[ok ]$(NC) bootloader is 4096 bytes\n" || { printf "$(RED)[!!]$(NC) bootloader size $$sz\n"; exit 1; }
	@magic=$$(od -An -tx4 -j8 -N4 $(KERNEL_BIN) | tr -d ' \n'); \
	 [ "$$magic" = "deadbeef" ] && printf "$(GREEN)[ok ]$(NC) kernel magic\n" || { printf "$(RED)[!!]$(NC) kernel magic $$magic\n"; exit 1; }
	@mb=$$(od -An -tx4 -j24 -N4 $(KERNEL_BIN) | tr -d ' \n'); \
	 [ "$$mb" = "1badb002" ] && printf "$(GREEN)[ok ]$(NC) multiboot header\n" || { printf "$(RED)[!!]$(NC) multiboot header $$mb\n"; exit 1; }
	@sz=$$(stat -c %s $(KERNEL_BIN)); [ $$sz -le 458752 ] && printf "$(GREEN)[ok ]$(NC) kernel fits the loader window (%s bytes)\n" $$sz || { printf "$(RED)[!!]$(NC) kernel too big\n"; exit 1; }

.PHONY: disassemble symbols stats
disassemble: $(KERNEL_ELF)
	@$(OBJDUMP) -d $< > $(BUILD)/kernel.lst && printf "$(GREEN)[ok ]$(NC) %s\n" $(BUILD)/kernel.lst
symbols: $(KERNEL_ELF)
	@nm -n $< > $(BUILD)/kernel.sym && printf "$(GREEN)[ok ]$(NC) %s\n" $(BUILD)/kernel.sym
stats: $(KERNEL_ELF) $(BOOT_BIN) $(DISK_IMAGE)
	@size $(KERNEL_ELF)
	@ls -l $(BOOT_BIN) $(KERNEL_BIN) $(DISK_IMAGE)

.PHONY: usb-info
usb-info:
	@printf "$(YEL)WARNING: this erases the target drive!$(NC)\n"
	@printf "  lsblk\n  sudo dd if=$(DISK_IMAGE) of=/dev/sdX bs=4M status=progress conv=fsync\n"

.PHONY: clean distclean help
clean:
	@rm -rf $(BUILD) $(OUT)
distclean: clean
	@rm -rf $(ISO)
help:
	@printf "targets: all run run-serial iso run-iso debug test disassemble symbols stats usb-info clean\n"

-include $(OBJS:.o=.d)
