// Tên G trùng với ký hiệu libc/libm (runtime luôn link -lm) phải được đổi tên
// tự động ở tầng C. Trước đây 'let mut log' sinh ra 'static int log;' và va vào
// log() của <math.h> -> lỗi C thô lộ ra người dùng.
let mut log: int = 0
let mut exp: int = 2
struct V { exp: int, log: int, index: int }
enum E { sin, cos }
fn bump() -> int {
    defer log += 100
    return log + 1
}
fn f(round: int, index: int) -> int {
    let log2 = round + index
    let pow = log2 * 2
    return pow
}
fn main() -> int {
    println("{} {}", bump(), log)
    let v = V{exp: 1, log: 2, index: 3}
    let e = sin
    println("{} {} {} {}", v.exp, v.log, v.index, e)
    println("{} {}", exp, f(1, 2))
    let sqrt = 16
    let floor = 3.5
    println("{} {}", sqrt, floor)
    return 0
}
