// alignof — bổ trợ sizeof cho lập trình hệ thống
struct Mixed { a: i8, b: i64, c: i16 }
fn main() -> int {
    println("{} {}", sizeof(i8), alignof(i8))
    println("{} {}", sizeof(i64), alignof(i64))
    println("{}", alignof(*int))
    println("{}", sizeof(Mixed) % alignof(Mixed) == 0)
    return 0
}
