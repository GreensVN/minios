// Result<T,E> + 'try' (0.23.0). Result KHÔNG phải kiểu dựng sẵn — nó chỉ là một
// struct generic thường, chứng minh generics/traits đủ mạnh để tự dựng.
// 'try' lan truyền lỗi: nếu giá trị là LỖI thì return ngay khỏi hàm.
struct Result<T, E> { ok: bool, val: T, err: E }

impl<T, E> Result<T, E> {
    fn is_ok(self) -> bool { return self.ok }
    fn unwrap_or(self, d: T) -> T { if self.ok { return self.val } return d }
}

fn ok_i(v: int) -> Result<int, str> {
    return Result<int, str>{ok: true, val: v, err: ""}
}
fn err_i(m: str) -> Result<int, str> {
    return Result<int, str>{ok: false, val: 0, err: m}
}

fn chia(a: int, b: int) -> Result<int, str> {
    if b == 0 { return err_i("chia cho 0") }
    return ok_i(a / b)
}

// 'try' nối nhiều bước có thể lỗi mà không phải if lồng nhau
fn tinh(a: int, b: int, c: int) -> Result<int, str> {
    let x = chia(a, b) try
    let y = chia(x, c) try
    return ok_i(y + 1)
}

// Result với kiểu khác -> bản nhân riêng
fn tim(xs: slice<int>, m: int) -> Result<usize, int> {
    for i in 0..len(xs) {
        if xs[i] == m { return Result<usize, int>{ok: true, val: i, err: 0} }
    }
    return Result<usize, int>{ok: false, val: 0, err: -1}
}

fn main() -> int {
    let r = tinh(100, 2, 5)
    println("{} {} [{}]", r.ok, r.val, r.err)
    let e = tinh(100, 0, 5)
    println("{} {} [{}]", e.ok, e.val, e.err)

    println("{} {}", r.is_ok(), r.unwrap_or(-1))
    println("{} {}", e.is_ok(), e.unwrap_or(-1))

    let a: [4]int = [10, 20, 30, 40]
    let f = tim(a[..], 30)
    let g = tim(a[..], 99)
    println("{} {} | {} {}", f.ok, f.val, g.ok, g.err)
    return 0
}
