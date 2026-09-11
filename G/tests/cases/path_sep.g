// 'Type::item' (kiểu Rust) đồng nghĩa 'Type.item': biến thể enum và method tĩnh.
enum Color { Red = 5, Green, Blue }
struct Counter { n: int }
impl Counter {
    fn new() -> Counter { return Counter{n: 0} }
    fn inc(self) { self.n += 1 }
}
fn main() -> int {
    println("{} {}", Color::Red as int, Color::Blue as int)
    let c = Color::Green
    match c { Color::Red => println("r") Color::Green => println("g") _ => println("b") }
    let mut k = Counter::new()
    k.inc() k.inc()
    println("{}", k.n)
    return 0
}
