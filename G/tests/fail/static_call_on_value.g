struct P { x: int }
impl P { fn new(v: int) -> P { return P { x: v } } }
fn main() -> int { let p = P { x: 1 }; let q = p.new(2); return 0 }
