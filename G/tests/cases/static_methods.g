// Method tĩnh 'Type.fn()', impl trên enum, 'Enum.Variant' đầy đủ, struct '=='.
struct Vec2 { x: int, y: int }
impl Vec2 {
    fn zero() -> Vec2 { return Vec2 { x: 0, y: 0 } }
    fn of(x: int, y: int) -> Vec2 { return Vec2 { x: x, y: y } }
    fn add(self, o: Vec2) -> Vec2 { return Vec2.of(self.x + o.x, self.y + o.y) }
    fn scale(self, k: int) { self.x *= k; self.y *= k }
}
enum Dir { N, E, S, W }
impl Dir {
    fn from_int(v: int) -> Dir { return v as Dir }
    fn turn(self) -> Dir {
        match self { Dir.N => { return Dir.E } Dir.E => { return Dir.S }
                     Dir.S => { return Dir.W } Dir.W => { return Dir.N } }
    }
    fn is_vert(self) -> bool { return *self == Dir.N || *self == Dir.S }
    fn name(self) -> str {
        match *self { N => { return "north" } E => { return "east" } _ => { return "other" } }
    }
}
fn main() -> int {
    let mut v = Vec2.zero().add(Vec2.of(2, 3))
    v.scale(2)
    println("{} {}", v.x, v.y)
    println("{} {}", v == Vec2.of(4, 6), v != Vec2 { x: 4, y: 6 })
    let d = Dir.from_int(1)
    println("{} {} {}", d.turn().is_vert(), Dir.N.is_vert(), d.name())
    let dirs: [4]Dir = [Dir.W, Dir.E, Dir.N, Dir.S]
    for x in dirs { print("{} ", x.turn() as int) }
    println("")
    // Biến thể trần và đầy đủ so sánh được với nhau
    println("{}", Dir.W == W)
    return 0
}
