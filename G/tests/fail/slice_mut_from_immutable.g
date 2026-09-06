fn fill(xs: mut slice<int>) { xs[0] = 1 }
fn main() -> int {
    let a: [3]int = [1, 2, 3]
    fill(a)
    return 0
}
