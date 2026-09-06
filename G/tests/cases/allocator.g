// Allocator thay thế được (0.20.0): 'alloc/free' dùng allocator mặc định;
// 'alloc_in/free_in' nhận một allocator tường minh. Xem docs/MEMORY.md.
struct Node { v: int, next: *Node }

fn tong(p: *int, n: int) -> int {
    let mut s = 0
    for i in 0..n { s += p[i] }
    return s
}

fn main() -> int {
    // --- allocator mặc định (heap) ---
    let p = alloc(int, 4)
    for i in 0..4 { p[i] = (i + 1) * 10 }
    println("{} {}", tong(p, 4), p[3])
    let q = realloc(p, int, 8)
    q[7] = 80
    println("{} {}", q[0], q[7])
    free(q)

    // --- arena: bộ đệm do NGƯỜI DÙNG cấp, không cần libc ---
    let mut backing: [1024]u8 = [0; 1024]
    let mut a = arena_allocator(backing)
    let xs = alloc_in(a, int, 3)
    xs[0] = 1
    xs[2] = 3
    let ns = alloc_in(a, Node, 2)
    ns[0].v = 42
    ns[1].v = 7
    println("{} {} {} {}", xs[0], xs[2], ns[0].v, ns[1].v)
    // free của arena là no-op có chủ ý: cả vùng chết cùng 'backing'
    free_in(a, xs)

    // arena thứ hai trên bộ đệm khác -> độc lập
    let mut b2: [64]u8 = [0; 64]
    let mut a2 = arena_allocator(b2)
    let y = alloc_in(a2, u32, 2)
    y[0] = 5
    println("{}", y[0])

    // heap_allocator() tường minh = như alloc()
    let mut h = heap_allocator()
    let z = alloc_in(h, int, 2)
    z[1] = 9
    println("{}", z[1])
    free_in(h, z)
    return 0
}
