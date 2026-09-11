// 'alloc' KHÔNG có allocator tường minh dùng heap mặc định -> cần libc.
// Ở freestanding phải dùng 'alloc_in' với allocator tự cấp (vd arena).
fn kmain() {
    let p = alloc(int, 4)
    p[0] = 1
}
fn main() -> int { kmain() return 0 }
