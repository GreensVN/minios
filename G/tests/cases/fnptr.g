// Kiểm tra con trỏ hàm: biến, tham số, trả về, mảng, trường struct, và hàm bậc cao.
import std

fn add(a: int, b: int) -> int { return a + b }
fn sub(a: int, b: int) -> int { return a - b }
fn mul(a: int, b: int) -> int { return a * b }
fn inc(x: int) -> int { return x + 1 }
fn sqr(x: int) -> int { return x * x }
fn neg(x: int) -> int { return -x }

// Hàm bậc cao: áp f cho từng phần tử (tại chỗ)
fn map_inplace(a: *int, n: int, f: fn(int) -> int) {
    for i in 0..n { a[i] = f(a[i]) }
}

// Reduce với con trỏ hàm + giá trị khởi tạo
fn reduce(a: *int, n: int, init: int, f: fn(int, int) -> int) -> int {
    let mut acc: int = init
    for i in 0..n { acc = f(acc, a[i]) }
    return acc
}

// Trả về con trỏ hàm tuỳ theo lựa chọn
fn op_by_name(name: str) -> fn(int, int) -> int {
    match name {
        "add" => { return add }
        "sub" => { return sub }
        _     => { return mul }
    }
}

struct Calc {
    op: fn(int, int) -> int,
    label: str,
}

fn main() -> int {
    // 1) biến con trỏ hàm + gọi + gán lại
    let mut f: fn(int, int) -> int = add
    println("add(3,4)={}", f(3, 4))
    f = mul
    println("mul(3,4)={}", f(3, 4))

    // 2) so sánh với null
    let mut g: fn(int) -> int = null
    println("g null? {}", g == null)
    g = inc
    println("g(41)={}, g khác null? {}", g(41), g != null)

    // 3) mảng con trỏ hàm + duyệt foreach
    let table: [3]fn(int) -> int = [inc, sqr, neg]
    for h in table { print("{} ", h(5)) }
    println("")

    // 4) hàm bậc cao
    let mut xs: [5]int = [1, 2, 3, 4, 5]
    map_inplace(&xs[0], 5, sqr)
    print("map sqr: ")
    for x in xs { print("{} ", x) }
    println("")
    println("reduce add={}, reduce mul={}",
            reduce(&xs[0], 5, 0, add), reduce(&xs[0], 5, 1, mul))

    // 5) trả về con trỏ hàm
    let chosen = op_by_name("sub")
    println("op_by_name(sub)(10,3)={}", chosen(10, 3))

    // 6) con trỏ hàm trong struct
    let c = Calc { op: add, label: "tổng" }
    println("{s}: {}", c.label, c.op(100, 23))
    return 0
}
