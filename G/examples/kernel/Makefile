# Kernel Multiboot viết bằng G. Cần: gcc (hỗ trợ -m32), ld, qemu-system-i386.
GC      ?= ../../gc
CC      ?= gcc
LD      ?= ld
QEMU    ?= qemu-system-i386

CFLAGS  := -m32 -O2 -fno-pic -fno-pie -fno-stack-protector -fno-asynchronous-unwind-tables -mno-red-zone -mno-sse -mno-mmx
LDFLAGS := -m elf_i386 -T linker.ld -nostdlib

all: kernel.elf

kernel.o: kernel.g
	$(GC) kernel.g --freestanding -c -o kernel.o $(CFLAGS)

boot.o: boot.s
	$(CC) -m32 -c boot.s -o boot.o

kernel.elf: boot.o kernel.o linker.ld
	$(LD) $(LDFLAGS) -o kernel.elf boot.o kernel.o

run: kernel.elf
	$(QEMU) -kernel kernel.elf -serial stdio

iso: kernel.elf
	mkdir -p iso/boot/grub
	cp kernel.elf iso/boot/kernel.elf
	printf 'set timeout=0\nmenuentry "G kernel" { multiboot /boot/kernel.elf }\n' > iso/boot/grub/grub.cfg
	grub-mkrescue -o kernel.iso iso

clean:
	rm -rf kernel.o boot.o kernel.elf kernel.iso iso

.PHONY: all run iso clean
