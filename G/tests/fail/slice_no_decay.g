fn takes_ptr(p: *int) -> int { return *p }
fn main() -> int {
    let mut a: [3]int = [1, 2, 3]
    let s = a[0..2]
    return takes_ptr(s)
}
