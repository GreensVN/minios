fn main() -> int { let mut x: int = 0; asm { "mov $1, %0" : "r"(x) }; return x }
