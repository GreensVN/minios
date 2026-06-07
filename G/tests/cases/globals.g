// Kiểm tra global khởi tạo KHÔNG hằng (tham chiếu global khác, lời gọi hàm,
// g_alloc) — sinh constructor chạy trước main. Cùng global có-hằng inline.

fn compute() -> int { return 7 * 6 }

// hằng số -> initializer tĩnh
let g_const: int = 100
let g_arr_const: [3]int = [1, 2, 3]

// không-hằng -> khởi tạo lúc chạy, theo thứ tự khai báo
let g_from_const = g_const + 1
let g_from_call = compute()
let g_arr_dyn: [3]int = [g_const, g_const * 2, g_from_call]
let mut g_mut = g_const

fn main() -> int {
    println("g_const = {}", g_const)
    println("g_from_const = {}", g_from_const)
    println("g_from_call = {}", g_from_call)
    println("g_arr_const = {} {} {}", g_arr_const[0], g_arr_const[1], g_arr_const[2])
    println("g_arr_dyn = {} {} {}", g_arr_dyn[0], g_arr_dyn[1], g_arr_dyn[2])

    g_mut += 5
    println("g_mut = {}", g_mut)
    return 0
}
