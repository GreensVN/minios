const CAP: int = 16
fn main() -> int { static_assert(sizeof(i64) == 8 && CAP > 100, "CAP quá nhỏ"); return 0 }
