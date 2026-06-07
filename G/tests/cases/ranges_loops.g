// Kiểm tra vòng lặp ngược (step âm), step tĩnh/động, và sizeof trên mảng.

fn main() -> int {
    // đếm ngược với step -1
    print("ngược: ")
    for i in 5..0 step -1 { print("{} ", i) }
    println("")

    // bao gồm cận, step -2
    print("ngược chẵn: ")
    for i in 10..=0 step -2 { print("{} ", i) }
    println("")

    // step động (dấu chỉ biết lúc chạy)
    let s = -3
    print("step động: ")
    for i in 9..0 step s { print("{} ", i) }
    println("")

    // step dương vẫn đúng
    print("xuôi: ")
    for i in 0..=8 step 2 { print("{} ", i) }
    println("")

    // sizeof bao gồm chiều mảng
    println("sizeof([10]int)={}, sizeof([3][4]int)={}, sizeof([5]char)={}",
            sizeof([10]int), sizeof([3][4]int), sizeof([5]char))
    return 0
}
