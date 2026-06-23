// Kiểm tra: intrinsics điều khiển CPU/MMU/MSR (đặc quyền, ring 0) BIÊN DỊCH được
// ở chế độ freestanding. Các lệnh này (mov cr*, invlpg, wbinvd, rd/wrmsr) chỉ
// chạy ở kernel nên file này chỉ biên dịch (-c), KHÔNG chạy.
//   gc cpu_control_fs.g --freestanding -c

// Bật phân trang: nạp gốc bảng trang (PML4) vào CR3 rồi đặt bit PG của CR0.
fn enable_paging(pml4: u64) {
    write_cr3(pml4)
    write_cr0(read_cr0() | (1 << 31))
}

// Địa chỉ gây lỗi trang nằm trong CR2 (chỉ-đọc).
fn page_fault_addr() -> u64 { return read_cr2() }

// Vô hiệu một mục TLB cho trang chứa địa chỉ.
fn flush_tlb_page(addr: u64) { invlpg(addr) }

// Bật SSE qua CR4 rồi đẩy/vô hiệu cache.
fn enable_sse() {
    write_cr4(read_cr4() | (1 << 9))
    wbinvd()
}

// Bật long mode: đặt bit LME (8) của MSR EFER (0xC0000080).
fn enable_long_mode() {
    let efer: u64 = rdmsr(0xC0000080)
    wrmsr(0xC0000080, efer | (1 << 8))
}
