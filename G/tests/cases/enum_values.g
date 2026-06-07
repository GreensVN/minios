// Test hồi quy: biến thể enum mang giá trị âm tường minh phải được ghi nhận đúng,
// và biến thể KHÔNG gán giá trị sau đó tự tăng từ giá trị (âm) liền trước.

enum Sign { Neg = -1, Zero, Pos }          // -1, 0, 1
enum Code { Err = -10, Warn, Info, Ok = 0 } // -10, -9, -8, 0

fn main() -> int {
    println("{} {} {}", Neg as int, Zero as int, Pos as int)        // -1 0 1
    println("{} {} {} {}", Err as int, Warn as int, Info as int, Ok as int)

    // match enum phủ hết variant (vét cạn, không cần '_')
    let s: Sign = Zero
    match s {
        Neg => { println("neg") }
        Zero => { println("zero") }
        Pos => { println("pos") }
    }
    return 0
}
