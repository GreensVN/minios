//! accept x86_64-linux
//! reject wasm32 vượt giới hạn kiểu 'usize'
// Biên giá trị của 'usize' theo target: 5 tỉ vừa 64-bit nhưng tràn 32-bit.
fn main() -> int {
    let n: usize = 5000000000
    println("{}", n)
    return 0
}
