// 'mut' tuỳ chọn trước tham số (gồm 'mut self') — mang tính tài liệu (tham số
// trong G vốn đã khả biến). Báo hiệu rõ method/hàm sẽ GHI vào đối số.
struct Acc { sum: int, count: int }
impl Acc {
    fn push(mut self, v: int) { self.sum += v; self.count += 1 }
    fn mean(self) -> int { if self.count == 0 { return 0 } return self.sum / self.count }
}
fn scaled_sum(mut total: int, xs: *int, n: int, k: int) -> int {
    for i in 0..n { total += xs[i] * k }
    return total
}
fn main() -> int {
    let mut a = Acc { sum: 0, count: 0 }
    a.push(10)
    a.push(20)
    a.push(30)
    println("sum={} count={} mean={}", a.sum, a.count, a.mean())  // 60 3 20
    let xs = [1, 2, 3]
    println("scaled={}", scaled_sum(100, xs, 3, 10))              // 160
    return 0
}
