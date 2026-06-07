// Kiểm tra escape ký tự/chuỗi: \n \t \x \u{...} và escape liền nhau.

fn main() -> int {
    // Escape cơ bản
    print("a\tb\tc\n")

    // Hex escape liền chữ cái (kiểm tra lỗi 'greedy hex' đã sửa)
    println("\x41\x42\x43end")          // ABCend

    // Unicode \u{...}
    println("trái tim: \u{2764}")
    println("emoji: \u{1F680}")

    // ANSI escape (ESC = \x1b) ngay trước '['
    println("\x1b[1mđậm?\x1b[0m (không màu khi pipe)")

    // Ký tự đặc biệt
    let nl: char = '\n'
    let tab: char = '\t'
    print("X{c}Y{c}Z\n", tab, nl)

    return 0
}
