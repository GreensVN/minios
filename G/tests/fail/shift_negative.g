// Dịch một lượng âm là UB.
fn main() -> int {
    let x: i64 = 4
    let y = x >> -1
    return y as int
}
