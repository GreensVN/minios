struct S { v: int }
fn g() -> *int { let s: S = S{v: 1}; return &s.v }
fn main() -> int { return *g() }
