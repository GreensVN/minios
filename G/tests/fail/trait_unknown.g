fn f<T: Nope>(a: T) -> int { let _ = a return 0 }
fn main() -> int { return f(1) }
