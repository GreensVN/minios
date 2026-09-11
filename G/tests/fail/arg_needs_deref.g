struct S { v: int }
fn take(s: S) -> int { return s.v }
fn main() -> int { let s = S{v:1} let p = &s return take(p) }
