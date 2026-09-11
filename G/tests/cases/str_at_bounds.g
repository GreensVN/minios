// 's.at(i)' hợp lệ trong [0, len); vượt biên là PANIC (giống 'a[i]' trên mảng
// tĩnh) chứ không trả '\0' âm thầm như trước.
fn main() -> int {
    let s = "hello"
    println("{} {} {}", s.at(0), s.at(4), "".is_empty())
    let mut i = 0
    let mut n = 0
    while i < 5 { if s.at(i) == 'l' { n += 1 } i += 1 }
    println("{}", n)
    return 0
}
