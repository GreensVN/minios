// Vượt biên một SLICE CON: độ dài đi theo slice nên vẫn bắt được, dù mảng gốc
// còn phần tử ở vị trí đó. Con trỏ trần '[]T' sẽ đọc bậy âm thầm.
fn get(xs: slice<int>, i: int) -> int { return xs[i] }
fn main() -> int {
    let a: [4]int = [10, 20, 30, 40]
    println("{}", get(a[0..2], 1))
    println("{}", get(a[0..2], 2))
    return 0
}
