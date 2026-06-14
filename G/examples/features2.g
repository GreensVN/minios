// features2.g — trình diễn các tính năng MỚI của G 0.4.0
//   typeof · alignof · so sánh chuỗi theo nội dung · số học con trỏ
//   thống kê · tổ hợp · lý thuyết số · sinh số ngẫu nhiên tất định
import std

fn main() -> int {
    println("== typeof (tên kiểu suy luận) ==")
    let n: i64 = 42
    println("typeof(n)      = {s}", typeof(n))
    println("typeof(3.14)   = {s}", typeof(3.14))
    println("typeof(\"hi\")   = {s}", typeof("hi"))
    println("typeof(true)   = {s}", typeof(true))

    println("\n== sizeof / alignof ==")
    println("sizeof(i64)={}  alignof(i64)={}", sizeof(i64), alignof(i64))
    println("sizeof(*int)={} alignof(*int)={}", sizeof(*int), alignof(*int))

    println("\n== so sánh chuỗi theo NỘI DUNG ==")
    let greeting: str = str_concat("xin ", "chào")   // chuỗi trên heap
    println("\"xin chào\" == nối? {}", greeting == "xin chào")
    g_free(greeting)

    println("\n== swap + số học con trỏ ==")
    let mut a: [6]int = [9, 1, 8, 2, 7, 3]
    swap(a[0], a[5])
    print("sau swap:")
    for i in 0..6 { print(" {}", a[i]) }
    println("")
    quicksort(&a[0], 6)
    print("đã sắp xếp:")
    let mut p: *int = &a[0]
    for _i in 0..6 { print(" {}", *p); p += 1 }
    println("")

    println("\n== thống kê ==")
    println("trung bình = {f:.2}", average(&a[0], 6))
    println("trung vị   = {f:.1}", median_sorted(&a[0], 6))
    println("độ lệch chuẩn = {f:.3}", stddev(&a[0], 6))

    println("\n== tổ hợp & lý thuyết số ==")
    println("C(10,3) = {}   P(10,3) = {}", ncr(10, 3), npr(10, 3))
    println("số ước của 360 = {}", num_divisors(360))
    println("phi(360)       = {}", totient(360))
    println("28 hoàn hảo?   = {}", is_perfect(28))

    println("\n== ngẫu nhiên tất định (cùng hạt -> cùng dãy) ==")
    rng_seed(2026)
    print("gieo 2026:")
    for _i in 0..5 { print(" {}", rand_int(1, 7)) }   // xúc xắc
    println("")
    return 0
}
