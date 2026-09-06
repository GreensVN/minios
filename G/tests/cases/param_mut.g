// 'mut' trước tên tham số cho phép GHI vào tham số (bản sao cục bộ), nhất quán
// với 'let'/'let mut'. Không có 'mut' thì tham số là binding chỉ đọc.
struct C { n: int }
impl C {
    fn add(self, mut k: int) -> int {
        k *= 2              // sửa bản sao, không ảnh hưởng nơi gọi
        self.n += k
        return k
    }
}
fn norm(mut x: int, lo: int) -> int {
    if x < lo { x = lo }
    return x
}
fn main() -> int {
    println("{} {}", norm(3, 5), norm(9, 5))
    let mut a = 7
    println("{}", norm(a, 5))
    println("{}", a)          // đối số nơi gọi KHÔNG đổi
    let mut c = C{n: 1}
    println("{} {}", c.add(10), c.n)
    return 0
}
