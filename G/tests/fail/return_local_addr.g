fn f() -> *int { let x: int = 5; return &x }
fn main() -> int { return *f() }
