fn bad<T>(a: T) -> T { return a + 1 }
fn main() -> int { return bad("x") as int }
