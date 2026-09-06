// Định danh G trùng từ khoá C / hàm libc / tên toàn cục: codegen phải đổi tên
// an toàn, không rò lỗi C ("expected identifier", "conflicting types"...).
import std

struct default { switch: int, char: int, register: int }
enum class { typedef, volatile, auto }

let mut total: int = 0
fn bump(exp: int, log: int) -> int { return exp + log }   // tham số trùng hàm libc

fn shadow_test(total: int) -> int {   // tham số che global
    let mut total = total * 2         // che tiếp
    total += 1
    return total
}

fn main() -> int {
    let switch = 3
    let default = default { switch: switch, char: 65, register: 7 }
    let class = class.volatile
    let int_ = 4
    let extern_ = 5
    let unsigned = 6
    let sizeof_ = 7
    let float = 1.5
    let puts = "not libc"
    println("{} {} {}", default.switch, default.char, default.register)
    println("{} {}", class as int, class == volatile)
    println("{} {} {} {}", int_, extern_ + unsigned, sizeof_, float)
    println("{}", puts)
    println("{}", bump(1, 2))
    total = 10
    println("{} {}", shadow_test(total), total)
    let nodes: [3]*int = [null, null, null]
    for i in 0..3 { g_free(nodes[i]) }   // đối số builtin cũng phải đổi tên đúng
    println("{}", len(nodes))
    return 0
}
