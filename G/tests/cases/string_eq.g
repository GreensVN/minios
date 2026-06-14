// '==' / '!=' trên chuỗi so theo NỘI DUNG (g_str_eq), không so địa chỉ
fn main() -> int {
    let a: str = "hello"
    let b: str = "hello"
    let c: str = "world"
    println("{}", a == b)
    println("{}", a == c)
    println("{}", a != c)
    println("{}", a != b)
    return 0
}
