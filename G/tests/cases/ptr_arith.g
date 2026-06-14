// Số học con trỏ qua '+=' / '-=' (di chuyển n phần tử)
fn main() -> int {
    let mut a: [5]int = [10, 20, 30, 40, 50]
    let mut p: *int = &a[0]
    p += 2
    println("{}", *p)
    p -= 1
    println("{}", *p)
    let mut q: *int = &a[0]
    let mut sum = 0
    let mut i = 0
    while i < 5 {
        sum = sum + *q
        q += 1
        i += 1
    }
    println("{}", sum)
    return 0
}
