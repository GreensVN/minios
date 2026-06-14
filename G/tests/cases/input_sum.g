import std
fn main() -> int {
    let n = read_int()
    let mut sum: i64 = 0
    for _i in 0..n { sum = sum + read_int() }
    println("sum = {}", sum)
    return 0
}
