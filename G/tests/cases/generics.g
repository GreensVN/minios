// Generic (0.21.0): 'fn f<T>(...)'. Hàm generic được NHÂN BẢN theo từng bộ kiểu
// cụ thể (monomorphization) ngay trong checker, nên G-IR và mọi backend không
// cần biết generic là gì — chúng chỉ thấy các hàm thường.
struct Pt { x: int, y: int }

fn id<T>(v: T) -> T { return v }
fn max2<T>(a: T, b: T) -> T { if a > b { return a } return b }
fn first<T>(xs: slice<T>) -> T { return xs[0] }
fn dem<T>(xs: slice<T>) -> int { return len(xs) as int }
fn pick<A, B>(a: A, b: B) -> B { let _ = a return b }
fn tong<T>(xs: slice<T>, zero: T) -> T {
    let mut s = zero
    for i in 0..len(xs) { s += xs[i] }
    return s
}

fn main() -> int {
    // suy kiểu từ đối số
    println("{} {} {}", id(42), id("hi"), id(true))
    println("{} {}", max2(3, 7), max2(2.5, 1.5))
    println("{}", max2('a', 'z'))

    // slice generic
    let a: [3]int = [10, 20, 30]
    println("{} {} {}", first(a[..]), dem(a[..]), tong(a[..], 0))
    let w: [2]str = ["p", "q"]
    println("{} {}", first(w[..]), dem(w[..]))

    // nhiều tham số kiểu
    println("{}", pick(1, "x"))

    // struct qua generic (theo GIÁ TRỊ)
    let p = id(Pt{x: 5, y: 6})
    println("{}", p)

    // đối số kiểu TƯỜNG MINH
    println("{}", id<str>("boo"))

    // cùng một khuôn, nhiều bản nhân -> dùng lại bản đã sinh
    println("{} {}", id(1), id(2))

    // '<' vẫn là so sánh khi không phải đối số kiểu
    let m = 3
    let n = 5
    println("{}", m < n)
    return 0
}
