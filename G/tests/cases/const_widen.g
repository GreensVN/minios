// Biểu thức hằng vượt 32-bit tự nâng lên i64; 'step' là định danh bình thường.
const CAP: int = 100000
fn main() -> int {
    let w = 100000 * 100000
    println("{} {}", w, typeof(w))
    let big = CAP * CAP + 1
    println("{} {}", big, typeof(big))
    let small = 1000 * 1000
    println("{} {}", small, typeof(small))
    let step = 3
    let mut acc = 0
    for i in 0..10 step step { acc += i }
    println("{} {}", acc, step)
    static_assert(sizeof(int) == 4, "int 32-bit")
    static_assert(CAP > 0)
    return 0
}
