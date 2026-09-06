# minios

Two independent educational projects live in this repository:

| Directory | What it is | Start here |
|---|---|---|
| [`G/`](G/) | **The G programming language** — a small statically typed language whose compiler (Python) emits C and drives `gcc`. Includes a test suite and a freestanding mode for OS code. | [`G/README.md`](G/README.md) |
| [`TreeOS/`](TreeOS/) | **MiniOS** — a from-scratch 32-bit x86 kernel (NASM + C + a little C++) with its own bootloader, interrupts, heap, preemptive threads, syscalls and a shell. Boots in QEMU, from GRUB, or on real BIOS hardware. Also contains host-side simulators in Python/Java/C#/JS. | [`TreeOS/README.md`](TreeOS/README.md) |

```bash
# G
cd G && ./tests/run_tests.sh

# MiniOS
cd TreeOS && make && make run
```
