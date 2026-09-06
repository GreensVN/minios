"""
Lớp TARGET / HAL của G.

VẤN ĐỀ ĐANG SỬA
===============
Trước đây các intrinsic phát triển hệ điều hành (`inb`, `outb`, `cli`, `sti`,
`rdtsc`, `read_cr3`, `rdmsr`...) là built-in TOÀN CỤC: chúng qua được checker
trên MỌI kiến trúc. Tệ hơn, runtime C định nghĩa chúng thành **no-op im lặng**
ngoài x86. Hệ quả cụ thể:

    fn uart_putc(c: u8) { outb(0x3F8, c) }      // aarch64: biên dịch SẠCH,
                                                 // chạy KHÔNG LÀM GÌ CẢ

Một driver không hoạt động mà không có bất kỳ cảnh báo nào — đúng loại lỗi tốn
nhiều giờ nhất để tìm, vì mã nguồn "trông đúng".

CÁCH TIẾP CẬN
=============
Mỗi intrinsic được gắn với một **năng lực (capability)**, và mỗi target khai báo
tập năng lực nó có. Checker từ chối intrinsic mà target không hỗ trợ, kèm gợi ý
thay thế. Đây là quan hệ dữ liệu, không phải chuỗi `if arch == "x86"` rải rác.

Vì sao là "năng lực" chứ không phải tên kiến trúc: `rdtsc` và `port_io` đều là
x86, nhưng bộ đếm chu kỳ có tương đương trên aarch64 (`cntvct_el0`) còn cổng I/O
thì **không tồn tại**. Gộp cả hai vào "x86" sẽ chặn nhầm khi thêm aarch64 sau
này. Năng lực tách chúng ra một cách tự nhiên.

MỞ RỘNG
=======
Thêm kiến trúc = thêm một `Target` vào `TARGETS`. Không đụng checker, không đụng
codegen. Backend/runtime tra cứu qua cùng bảng đó.
"""

from dataclasses import dataclass, field


# ----------------------------------------------------------------------
# Năng lực phần cứng
# ----------------------------------------------------------------------
#: Cổng I/O riêng biệt (chỉ x86 có; ARM/RISC-V dùng MMIO thay thế).
CAP_PORT_IO = "port_io"
#: Lệnh đặc quyền dừng/bật-tắt ngắt (hlt/cli/sti hoặc tương đương).
CAP_PRIV = "privileged"
#: Bộ đếm chu kỳ đọc được (rdtsc / cntvct_el0 / rdcycle).
CAP_CYCLE_COUNTER = "cycle_counter"
#: Thanh ghi điều khiển kiểu x86 (CR0/CR2/CR3/CR4).
CAP_CONTROL_REGS = "control_regs"
#: Thanh ghi đặc thù model (MSR) — rdmsr/wrmsr.
CAP_MSR = "msr"
#: Vô hiệu hoá TLB theo trang / dọn cache (invlpg, wbinvd).
CAP_TLB = "tlb"
#: Gợi ý vòng lặp bận (pause / yield / nop).
CAP_SPIN_HINT = "spin_hint"
#: Điểm dừng gỡ lỗi (int3 / brk).
CAP_BREAKPOINT = "breakpoint"

ALL_CAPS = {
    CAP_PORT_IO, CAP_PRIV, CAP_CYCLE_COUNTER, CAP_CONTROL_REGS,
    CAP_MSR, CAP_TLB, CAP_SPIN_HINT, CAP_BREAKPOINT,
}


@dataclass(frozen=True)
class Target:
    """Một bộ ba kiến trúc/HĐH/ABI cùng tập năng lực của nó."""
    name: str
    arch: str                       # x86_64 | aarch64 | riscv64 | wasm32
    os: str = "linux"               # linux | none (bare metal) | ...
    ptr_bits: int = 64
    caps: frozenset = field(default_factory=frozenset)
    #: bộ ba GCC/Clang (--target=...) khi cross-compile
    triple: str = ""

    def has(self, cap) -> bool:
        return cap in self.caps

    def __str__(self):
        return self.name


# ----------------------------------------------------------------------
# Các target đã biết
# ----------------------------------------------------------------------
_X86_CAPS = frozenset({
    CAP_PORT_IO, CAP_PRIV, CAP_CYCLE_COUNTER, CAP_CONTROL_REGS,
    CAP_MSR, CAP_TLB, CAP_SPIN_HINT, CAP_BREAKPOINT,
})

#: aarch64 KHÔNG có cổng I/O riêng biệt và không có CR/MSR kiểu x86.
#: Nó có bộ đếm chu kỳ (cntvct_el0), lệnh đặc quyền (wfi/msr daifset),
#: gợi ý spin (yield), breakpoint (brk), và quản lý TLB (tlbi) — nhưng runtime
#: hiện chưa cài, nên chỉ khai báo những gì THỰC SỰ dùng được.
_AARCH64_CAPS = frozenset({
    CAP_PRIV, CAP_CYCLE_COUNTER, CAP_SPIN_HINT, CAP_BREAKPOINT,
})

_RISCV_CAPS = frozenset({
    CAP_PRIV, CAP_CYCLE_COUNTER, CAP_SPIN_HINT, CAP_BREAKPOINT,
})

#: WebAssembly: không có gì thuộc phần cứng thô.
_WASM_CAPS = frozenset()

TARGETS = {
    "x86_64-linux": Target("x86_64-linux", "x86_64", "linux", 64, _X86_CAPS,
                           "x86_64-linux-gnu"),
    "x86_64-none": Target("x86_64-none", "x86_64", "none", 64, _X86_CAPS,
                          "x86_64-elf"),
    "aarch64-linux": Target("aarch64-linux", "aarch64", "linux", 64,
                            _AARCH64_CAPS, "aarch64-linux-gnu"),
    "aarch64-none": Target("aarch64-none", "aarch64", "none", 64,
                           _AARCH64_CAPS, "aarch64-elf"),
    "riscv64-linux": Target("riscv64-linux", "riscv64", "linux", 64,
                            _RISCV_CAPS, "riscv64-linux-gnu"),
    "riscv64-none": Target("riscv64-none", "riscv64", "none", 64,
                           _RISCV_CAPS, "riscv64-elf"),
    "wasm32": Target("wasm32", "wasm32", "wasi", 32, _WASM_CAPS,
                     "wasm32-wasi"),
}


# ----------------------------------------------------------------------
# Intrinsic -> năng lực cần có
# ----------------------------------------------------------------------
#: Ánh xạ tên built-in của G sang năng lực bắt buộc. Built-in KHÔNG có trong
#: bảng này là độc lập kiến trúc (popcount, memcpy, ...) và luôn dùng được.
INTRINSIC_CAPS = {
    # cổng I/O x86
    "inb": CAP_PORT_IO, "outb": CAP_PORT_IO,
    "inw": CAP_PORT_IO, "outw": CAP_PORT_IO,
    "inl": CAP_PORT_IO, "outl": CAP_PORT_IO,
    "io_wait": CAP_PORT_IO,
    # lệnh đặc quyền
    "halt": CAP_PRIV, "cli": CAP_PRIV, "sti": CAP_PRIV,
    # đo thời gian
    "rdtsc": CAP_CYCLE_COUNTER,
    # thanh ghi điều khiển
    "read_cr0": CAP_CONTROL_REGS, "read_cr2": CAP_CONTROL_REGS,
    "read_cr3": CAP_CONTROL_REGS, "read_cr4": CAP_CONTROL_REGS,
    "write_cr0": CAP_CONTROL_REGS, "write_cr3": CAP_CONTROL_REGS,
    "write_cr4": CAP_CONTROL_REGS,
    # MSR
    "rdmsr": CAP_MSR, "wrmsr": CAP_MSR,
    # TLB / cache
    "invlpg": CAP_TLB, "wbinvd": CAP_TLB,
    # gợi ý & gỡ lỗi
    "pause": CAP_SPIN_HINT,
    "breakpoint": CAP_BREAKPOINT,
}

#: Gợi ý thay thế khi target thiếu năng lực — thông báo lỗi phải nói được
#: "làm gì thay thế", không chỉ "không dùng được".
CAP_HINTS = {
    CAP_PORT_IO: ("kiến trúc này không có cổng I/O riêng biệt (chỉ x86 có) — "
                  "dùng MMIO: 'vol_write(addr, val)' / 'vol_read(addr)'"),
    CAP_PRIV: ("target này không hỗ trợ lệnh đặc quyền — chúng chỉ có nghĩa "
               "ở chế độ bare-metal/kernel"),
    CAP_CYCLE_COUNTER: "target này không có bộ đếm chu kỳ đọc được",
    CAP_CONTROL_REGS: ("thanh ghi điều khiển CR0/CR2/CR3/CR4 là đặc thù x86 — "
                       "kiến trúc khác dùng thanh ghi hệ thống riêng"),
    CAP_MSR: "MSR (rdmsr/wrmsr) là đặc thù x86",
    CAP_TLB: ("invlpg/wbinvd là đặc thù x86 — kiến trúc khác có lệnh quản lý "
              "TLB/cache riêng"),
    CAP_SPIN_HINT: "target này không có lệnh gợi ý vòng lặp bận",
    CAP_BREAKPOINT: "target này không có lệnh breakpoint",
}


def default_target() -> Target:
    """Target mặc định = máy đang chạy trình biên dịch (biên dịch tại chỗ)."""
    import platform
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return TARGETS["x86_64-linux"]
    if m in ("aarch64", "arm64"):
        return TARGETS["aarch64-linux"]
    if m.startswith("riscv64"):
        return TARGETS["riscv64-linux"]
    # Kiến trúc lạ: giả định x86_64 để không chặn nhầm (hành vi CŨ), nhưng
    # người dùng vẫn có thể chỉ định --target tường minh.
    return TARGETS["x86_64-linux"]


def get(name) -> Target:
    """Tra target theo tên; chấp nhận vài bí danh thông dụng."""
    if not name:
        return default_target()
    key = name.strip().lower()
    alias = {
        "x86_64": "x86_64-linux", "amd64": "x86_64-linux",
        "x64": "x86_64-linux",
        "aarch64": "aarch64-linux", "arm64": "aarch64-linux",
        "riscv64": "riscv64-linux", "rv64": "riscv64-linux",
        "wasm": "wasm32",
        "native": default_target().name,
    }
    key = alias.get(key, key)
    if key not in TARGETS:
        raise KeyError(key)
    return TARGETS[key]


def available():
    return sorted(TARGETS)
