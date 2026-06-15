// In trực tiếp struct với '{}' -> 'Tên { trường: giá trị, ... }' (đệ quy cho
// struct lồng), và enum -> TÊN biến thể. '{d}' tường minh vẫn in số nguyên.
enum Color { Red, Green, Blue }
struct Point { x: int, y: int }
struct Box { lo: Point, hi: Point, color: Color, filled: bool }

fn origin() -> Point { return Point { x: 0, y: 0 } }

fn main() -> int {
    let p = Point { x: 3, y: 4 }
    println("{}", p)                                 // Point { x: 3, y: 4 }
    println("a={}, b={}", p, Point { x: 1, y: 2 })   // hai struct một dòng
    let b = Box { lo: origin(), hi: Point { x: 9, y: 9 }, color: Blue, filled: true }
    println("{}", b)                                 // struct lồng + enum + bool
    println("{} {} {}", Red, Green, Blue)            // Red Green Blue
    println("{d}", Blue)                             // 2 (số nguyên tường minh)
    return 0
}
