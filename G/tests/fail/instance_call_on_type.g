struct P { x: int }
impl P { fn get(self) -> int { return self.x } }
fn main() -> int { let v = P.get(); return 0 }
