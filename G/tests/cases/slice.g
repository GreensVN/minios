// slice<T> — con trỏ BÉO (ptr + len). Khác '[]T' (con trỏ trần, mất độ dài) và
// '[N]T' (mảng tĩnh). Độ dài đi CÙNG con trỏ nên kiểm biên vẫn hoạt động sau
// khi slice đã đi qua nhiều lời gọi hàm.
fn total(xs: slice<int>) -> int {
    let mut s = 0
    for i in 0..len(xs) { s += xs[i] }
    return s
}
fn fill(xs: mut slice<int>, v: int) {
    for i in 0..len(xs) { xs[i] = v }
}
fn first_or(xs: slice<int>, d: int) -> int {
    if len(xs) == 0 { return d }
    return xs[0]
}
struct Buf { data: [4]int }

fn main() -> int {
    let a: [5]int = [1, 2, 3, 4, 5]
    // mảng tĩnh tự chuyển thành slice (mang theo độ dài)
    println("{} {}", total(a), len(a))
    // cắt lát: nửa mở, và dạng khuyết cận
    println("{} {} {}", total(a[0..2]), total(a[3..]), total(a[..2]))
    println("{}", total(a[1..=3]))
    // slice rỗng và kẹp biên
    println("{} {} {}", len(a[2..2]), len(a[9..20]), first_or(a[2..2], -1))
    // cắt lát của cắt lát
    let mid = a[1..4]
    println("{} {}", len(mid), total(mid[1..3]))

    // ghi qua 'mut slice' sửa mảng gốc
    let mut b: [5]int = [0, 0, 0, 0, 0]
    fill(b, 7)
    println("{} {}", total(b), b[4])
    fill(b[1..3], 9)
    println("{} {} {} {}", b[0], b[1], b[2], b[3])

    // slice trên trường mảng của struct
    let mut s = Buf{data: [1, 2, 3, 4]}
    fill(s.data, 5)
    println("{}", total(s.data))

    // slice của kiểu khác
    let words: [3]str = ["a", "bb", "ccc"]
    let w = words[1..3]
    println("{} {}", len(w), w[1])
    // in trực tiếp một slice (độ dài biết lúc chạy -> hàm in riêng)
    println("{}", a[1..4])
    println("{}", a[2..2])
    println("{}", w)
    return 0
}
