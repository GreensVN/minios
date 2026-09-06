// Trait (0.22.0) là RÀNG BUỘC LÚC BIÊN DỊCH cho generic: không vtable, không
// boxing, không chi phí lúc chạy. Kiểm tại nơi NHÂN BẢN generic, nên lỗi báo ở
// chỗ gọi chứ không phải sâu trong thân hàm.
trait Show { fn show(self) -> str }
trait Area { fn area(self) -> int }

struct Pt { x: int, y: int }
impl Show for Pt { fn show(self) -> str { return "Pt" } }

struct Rect { w: int, h: int }
impl Show for Rect { fn show(self) -> str { return "Rect" } }
impl Area for Rect { fn area(self) -> int { return self.w * self.h } }

enum Col { R, G }
impl Show for Col { fn show(self) -> str { return "Col" } }

// impl THƯỜNG (không trait) vẫn hoạt động như trước
impl Pt { fn tong(self) -> int { return self.x + self.y } }

fn nhan<T: Show>(v: T) -> str { return v.show() }
fn dt<T: Area>(v: T) -> int { return v.area() }
fn ca_hai<T: Show + Area>(v: T) -> int { let _ = v.show() return v.area() }
// trait DỰNG SẴN cho kiểu nguyên thuỷ (không cần impl tay)
fn lon_hon<T: Ord>(a: T, b: T) -> T { if a > b { return a } return b }

fn main() -> int {
    println("{} {} {}", nhan(Pt{x:1,y:2}), nhan(Rect{w:2,h:3}), nhan(R))
    println("{} {}", dt(Rect{w:4,h:5}), ca_hai(Rect{w:2,h:6}))
    println("{} {} {}", lon_hon(3, 7), lon_hon(2.5, 1.5), lon_hon('a', 'z'))
    println("{}", Pt{x:3,y:4}.tong())
    return 0
}
