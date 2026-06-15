// Hồi quy: đối số hàm/print/method được đánh giá TRÁI-SANG-PHẢI (C không quy
// định thứ tự; G ép thứ tự ổn định để có hành vi tất định kiểu Rust).
let mut n = 0
fn nx() -> int { n += 1; return n }
fn show3(a: int, b: int, c: int) { println("{} {} {}", a, b, c) }

struct Acc { sum: int }
impl Acc {
    fn add2(self, a: int, b: int) -> int { self.sum = self.sum + a + b; return self.sum }
}

fn main() -> int {
    n = 0
    show3(nx(), nx(), nx())                 // 1 2 3
    n = 0
    println("{} {} {}", nx(), nx(), nx())   // 1 2 3
    n = 5
    show3(n, nx(), n)                       // 5 6 6 (đọc n, tăng n, đọc n)
    let mut acc = Acc { sum: 0 }
    n = 0
    println("{}", acc.add2(nx(), nx()))     // a=1, b=2 -> 3
    return 0
}
