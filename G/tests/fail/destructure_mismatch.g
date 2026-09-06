struct P { x: int }
struct Q { x: int }
fn main() -> int { let q = Q{x:1} let P{x} = q return x }
