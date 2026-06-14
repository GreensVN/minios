// typeof (chuỗi tên kiểu suy luận) + swap (tráo hai ô nhớ)
fn main() -> int {
    let x: i64 = 5
    println("{s}", typeof(x))
    println("{s}", typeof(3.14))
    println("{s}", typeof("hi"))
    println("{s}", typeof(true))
    let mut a = 1
    let mut b = 2
    swap(a, b)
    println("{} {}", a, b)
    let mut arr: [3]int = [7, 8, 9]
    swap(arr[0], arr[2])
    println("{} {} {}", arr[0], arr[1], arr[2])
    return 0
}
