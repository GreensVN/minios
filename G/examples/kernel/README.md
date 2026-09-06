# Kernel Multiboot bằng G

Ví dụ hoàn chỉnh về phần mềm chạy **trực tiếp trên phần cứng** viết bằng G:
không libc, không hệ điều hành, được GRUB/QEMU nạp qua chuẩn Multiboot 1.

| File | Vai trò |
|------|---------|
| `kernel.g` | Kernel: xoá BSS, console VGA + cổng nối tiếp, đọc thông tin Multiboot, `hlt` |
| `boot.s` | Header Multiboot, thiết lập ngăn xếp, gọi `kmain(magic, mbi)` |
| `linker.ld` | Bố cục bộ nhớ (nạp tại 1 MiB), ký hiệu `_bss_start/_bss_end` |
| `Makefile` | `make` → `kernel.elf`; `make run` → QEMU; `make iso` → ảnh GRUB |

```bash
make            # cần gcc -m32, ld
make run        # qemu-system-i386 -kernel kernel.elf -serial stdio
```

Điểm đáng chú ý trong `kernel.g`:
- `--freestanding -c`: runtime tự cài `memset/memcpy`, không cần `main`.
- MMIO qua `vol_read`/`vol_write` (VGA ở `0xB8000`), cổng I/O qua `inb`/`outb`.
- `@packed struct MultibootInfo` khớp bố cục bootloader; `@noreturn`, `@used`.
- Ngăn xếp đặt trong section `.stack` riêng — nằm **ngoài** `_bss_start.._bss_end`
  nên `clear_bss()` không xoá mất ngăn xếp đang chạy (lỗi kinh điển).
