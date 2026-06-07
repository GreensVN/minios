// Kiểm tra shadowing biến (G cho phép, C thì không -> cần đổi tên ngầm),
// shadowing trong block lồng nhau, và shadowing biến lặp.

fn main() -> int {
    // Shadow cùng scope
    let x = 5
    let x = x + 10
    let x = x * 2
    println("x = {}", x)            // 30

    // Shadow trong block lồng
    let y = 1
    {
        let y = 2
        {
            let y = 3
            println("inner y = {}", y)   // 3
        }
        println("mid y = {}", y)         // 2
    }
    println("outer y = {}", y)           // 1

    // Shadow đổi kiểu
    let z = 42
    let z = "now a string"
    println("z = {s}", z)

    // Shadow trong vòng lặp
    let i = 100
    for i in 0..3 {
        print("{} ", i)               // 0 1 2
    }
    println("")
    println("outer i = {}", i)        // 100

    return 0
}
