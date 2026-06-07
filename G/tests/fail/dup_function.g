// Định nghĩa hàm hai lần.
fn foo() -> int { return 1 }
fn foo() -> int { return 2 }
fn main() -> int { return foo() }
