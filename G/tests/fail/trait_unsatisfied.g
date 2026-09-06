trait Ord2 { fn cmp(self, o: int) -> int }
struct N { v: int }
fn f<T: Ord2>(a: T) -> int { let _ = a return 0 }
fn main() -> int { return f(N{v:1}) }
