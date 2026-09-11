struct N { v: int }
fn kmain() { let p = g_alloc(N, 1) g_free(p) }
fn main() -> int { kmain() return 0 }
