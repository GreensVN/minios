// 'self' trong 'impl' là con trỏ; '.field' đã tự deref nên '==' cũng phải tự
// deref (trước đây 'match self' chạy còn 'self == Red' báo '*Color' vs 'Color').
enum Color { Red, Green, Blue }
impl Color {
    fn name(self) -> str {
        match self { Red => return "đỏ" Green => return "lục" _ => return "lam" }
    }
    fn is_red(self) -> bool { return self == Red }
    fn not_blue(self) -> bool { return self != Blue }
}
fn main() -> int {
    let c = Green
    println("{} {} {}", c.name(), c.is_red(), c.not_blue())
    println("{} {}", Red.is_red(), Blue.not_blue())
    return 0
}
