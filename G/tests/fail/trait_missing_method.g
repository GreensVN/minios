trait Sh { fn show(self) -> str
  fn size(self) -> int }
struct N { v: int }
impl Sh for N { fn show(self) -> str { return "n" } }
fn main() -> int { return 0 }
