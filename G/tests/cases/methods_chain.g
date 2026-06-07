// Kiểm tra gọi method chuỗi (receiver là rvalue -> vật hoá vào biến tạm),
// method trên 'let' bất biến (không-sửa), và đánh giá tác dụng phụ đúng 1 lần.

let mut builds: int = 0

struct Vec2 { x: int, y: int }

impl Vec2 {
    fn add(self, dx: int, dy: int) -> Vec2 {
        return Vec2 { x: self.x + dx, y: self.y + dy }
    }
    fn scale(self, k: int) -> Vec2 {
        return Vec2 { x: self.x * k, y: self.y * k }
    }
    fn sum(self) -> int { return self.x + self.y }
}

fn origin() -> Vec2 {
    builds += 1
    return Vec2 { x: 0, y: 0 }
}

fn main() -> int {
    // chuỗi method trên rvalue (origin() trả về giá trị)
    let r = origin().add(3, 4).scale(2).sum()
    println("r = {}", r)
    println("builds = {}", builds)   // origin() chỉ chạy 1 lần

    // method không-sửa trên binding 'let' bất biến -> hợp lệ
    let v = Vec2 { x: 5, y: 5 }
    println("v.sum() = {}", v.sum())
    println("v.scale(3).sum() = {}", v.scale(3).sum())
    return 0
}
