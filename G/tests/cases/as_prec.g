// 'as' ràng buộc lỏng hơn tiền tố: '&x as *T' = '(&x) as *T', '-x as int' = '(-x) as int'
fn main() -> int {
    let mut x: i32 = 0x01020304
    let p = &x as *u8
    println("{}", p[0] as int)
    let f: f64 = 3.9
    println("{}", -f as int)
    let y: int = 300
    println("{}", y as u8)
    return 0
}
