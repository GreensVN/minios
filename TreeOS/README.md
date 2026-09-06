# MiniOS (TreeOS) v4.1 — a small educational x86 operating system

MiniOS is a from-scratch 32-bit x86 kernel written in C and NASM assembly, small
enough to read in an afternoon but complete enough to *actually boot*: it has its
own two-stage bootloader, a protected-mode kernel with interrupts, a heap, a
physical frame allocator, preemptive multithreading, system calls and an
interactive shell.

It boots two ways:

* from its own bootloader (`output/minios.img` — a raw disk image; `dd` it to a
  USB stick or give it to QEMU as a hard disk), or
* from any Multiboot 1 loader such as GRUB (`build/kernel.elf`, or `make iso`).

The other files in this directory (`minios_shell.py`, `FileSystemSimulator.java`,
`NetworkStackSimulator.cs`, `Terminal.html`, `desktop.js`) are **host-side
simulators** written in different languages that demonstrate OS concepts (shells,
inode file systems, TCP/IP framing, a desktop UI). They are *not* part of the
kernel image.

---

## Quick start

```bash
# Debian / Ubuntu
sudo apt install build-essential gcc-multilib nasm qemu-system-x86
# Arch:  sudo pacman -S base-devel nasm qemu-system-x86 (gcc has multilib via lib32-gcc-libs)
# macOS: brew install nasm qemu x86_64-elf-gcc  → make CROSS=x86_64-elf-  (or i686-elf-)

cd TreeOS
make            # → output/minios.img (bootable), build/kernel.elf (Multiboot)
make test       # sanity checks on the produced binaries
make run        # boot in QEMU (window)
make run-serial # boot in QEMU with the console mirrored on your terminal (Ctrl-A X quits)
```

`./build.sh [run|serial|test|clean]` wraps the same targets and checks that
your toolchain can produce 32-bit code first.

### What you should see

```
MiniOS v4.1.0 - 32-bit protected mode kernel
[BOOT] MiniOS bootloader, magic 0x4d494e49
[MEM ] 639 KiB low, 261120 KiB high, 5 E820 entries, top 0x10000000
[KRNL] 0x00100000 - 0x00112000 (72 KiB)
[ OK ] GDT loaded (5 entries)
[ OK ] IDT loaded (32 exceptions, 16 IRQs, INT 0x80)
[ OK ] PIC remapped to vectors 32-47
[ OK ] PIT at 100 Hz
[ OK ] PS/2 keyboard ready
[ OK ] heap 0x00112000 - 0x02112000 (32768 KiB)
[ OK ] frame allocator: 57070 x 4 KiB frames (222 MiB)
[ OK ] RTC: 2026-09-05 11:41:18
[ OK ] ATA: QEMU HARDDISK (8 MiB)
[ OK ] interrupts enabled, preemptive scheduler on (quantum 5 ticks)
[ OK ] CPU: GenuineIntel ~2994 MHz
[ OK ] background status thread started

System ready. Type 'help' for a list of commands.

minios:/$
```

The bottom line of the screen is a status bar with the uptime clock, updated by
a background kernel thread — proof that preemption works while you type.

---

## Shell commands

| Command | What it does |
|---|---|
| `help` | list commands |
| `clear` | clear the screen |
| `mem` | boot loader, E820 memory map, kernel layout, heap and frame statistics |
| `ps` | task table (pid, state, ticks, stack) |
| `uptime`, `ticks` | uptime from the PIT |
| `cpuinfo` | CPUID vendor, family/model, feature flags |
| `date` | CMOS real-time clock |
| `drivers` | drivers registered with the C++ driver manager |
| `disk [lba]` | identify the ATA disk and hex-dump one sector (`disk 0` shows the boot sector, `disk 8` the kernel header) |
| `echo <text>` | print text |
| `color <fg> [bg]` | change the console colours (0–15) |
| `alloc <bytes>`, `heaptest` | exercise `kmalloc`/`kfree`; `heaptest` runs a self-check |
| `spawn [n]` | start *n* demo threads that print interleaved output |
| `kill <pid>` | terminate a thread |
| `syscall` | demonstrate the `INT 0x80` interface from kernel mode |
| `sleep <ms>` | block the shell (other threads keep running) |
| `bp` | trigger `INT 3` — the breakpoint handler prints the frame and resumes |
| `crash` | divide by zero → kernel panic screen with register dump |
| `ud` | execute an invalid opcode → panic screen |
| `reboot`, `halt` | via the keyboard controller / `hlt` |

---

## Layout

```
TreeOS/
├── Bootloader.asm        two-stage BIOS bootloader (4096 bytes: MBR + 7 sectors)
├── entry.asm             kernel entry: header, Multiboot header, BSS clear, stack, call kernel_main
├── interrupts.asm        ISR/IRQ stubs, INT 0x80 stub, context switch, GDT/IDT/TR loaders, atomics
├── kernel.h              shared types: boot_info_t, interrupt frame, syscall numbers, asm prototypes
├── Kernel.c              the kernel proper (console, GDT/IDT/PIC/PIT, heap, frames, tasks, syscalls, shell)
├── driver_manager.h/.cpp C++ driver framework with keyboard, ATA PIO, PIT and RTC drivers + C API
├── linker.ld             links everything at 1 MiB, exports the symbols used by the header
├── Makefile              build / run / test / iso / debug / disassemble
├── build.sh              friendly wrapper around the Makefile
│
├── minios_shell.py       host-side shell & system-monitor simulator (python3 minios_shell.py)
├── FileSystemSimulator.java  inode/block file-system simulator (javac + java FileSystemSimulator)
├── NetworkStackSimulator.cs  Ethernet/IP/TCP framing simulator (dotnet / csc)
├── Terminal.html         browser terminal UI
└── desktop.js            browser desktop UI (loaded by Terminal.html)
```

### Boot protocol

| LBA | Contents | Loaded to |
|---|---|---|
| 0 | stage 1 (MBR) | `0x7C00` |
| 1–7 | stage 2 | `0x7E00` |
| 8… | `kernel.bin` (flat binary) | `0x100000` via a bounce buffer at `0x10000` |

Stage 2 enables A20, collects the E820 map (at `0xA000`), reads the kernel size
from its header, copies it above 1 MiB with unreal mode, builds a GDT, enters
protected mode and jumps to the kernel with `EAX = 0x4D494E49` (`'MINI'`) and
`EBX` pointing to a `boot_info_t`. When GRUB loads `kernel.elf` the same entry
point receives `EAX = 0x2BADB002` and a Multiboot info pointer; `Kernel.c`
normalises both into the same structure.

The kernel header at the start of the image:

| offset | field |
|---|---|
| +0 | `jmp` to entry |
| +8 | magic `0xDEADBEEF` |
| +12 | version `0x00040100` (4.1.0) |
| +16 | end of the loaded image (`_load_end`) |
| +20 | end of BSS (`_bss_end`) |
| +24 | Multiboot 1 header |

### Memory map at run time

```
0x00000000  IVT / BIOS data
0x00007C00  stage 1, 0x7E00 stage 2, 0xA000 E820 map (boot only)
0x00010000  bounce buffer (boot only)
0x000B8000  VGA text buffer
0x00100000  kernel .text / .rodata / .data / .bss (+ 32 KiB kernel stack)
_kernel_end kernel heap (first-fit with coalescing, up to 32 MiB)
heap end    bitmap-managed 4 KiB frames up to the top of usable RAM
```

There is **no paging** and no user mode: this is a single-address-space kernel,
which keeps the code small enough to follow. System calls still go through a
real `INT 0x80` gate so the mechanism is demonstrated end to end.

---

## Other targets

```bash
make iso        # GRUB ISO from kernel.elf (needs grub-mkrescue + xorriso)
make run-iso
make debug      # QEMU paused with a GDB stub; then: gdb build/kernel.elf -ex 'target remote :1234'
make disassemble  # build/kernel.dis
make symbols      # build/kernel.sym
make stats        # section sizes
make clean
```

To write the image to a USB stick: `sudo dd if=output/minios.img of=/dev/sdX bs=1M
&& sync` — double-check `/dev/sdX`, this destroys whatever is on it. The machine
must boot in legacy BIOS/CSM mode.

---

## Known limitations

* No paging / virtual memory, no user mode, no real file system on the kernel
  side (the ATA driver reads raw sectors).
* PS/2 keyboard only (USB keyboards work through BIOS legacy emulation on most
  machines); US layout.
* Text mode 80×25 only; no networking.
* Single CPU.

These are deliberate: each would double the size of the code base. The
simulators in the same directory cover file-system and network-stack concepts
at a higher level.

## License

MIT.
