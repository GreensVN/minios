// match trên bool với đủ true/false là vét cạn: hàm không cần return thừa.
fn f(b: bool) -> int {
    match b {
        true => { return 1 }
        false => { return 0 }
    }
}
fn g(b: bool) -> str {
    match b {
        false => { return "no" }
        _ => { return "yes" }
    }
}
fn main() -> int {
    println("{} {} {} {}", f(true), f(false), g(true), g(false))
    return 0
}
