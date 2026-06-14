// Kiểm tra phần mở rộng thư viện chuẩn: toán libm, số nguyên, mảng, chuỗi.
import std

fn main() -> int {
    // --- Toán (libm) ---
    println("sqrt(144)={f}, cbrt(27)={f}, pow(3,4)={f}", sqrt(144.0), cbrt(27.0), pow(3.0, 4.0))
    println("floor(2.9)={f}, ceil(2.1)={f}, round(2.5)={f}, trunc(2.9)={f}",
            floor(2.9), ceil(2.1), round(2.5), trunc(2.9))
    println("lerp(10,20,0.5)={f}, clampf(9,0,5)={f}, hypot(3,4)={f}",
            lerp(10.0, 20.0, 0.5), clampf(9.0, 0.0, 5.0), hypot(3.0, 4.0))

    // --- Số nguyên ---
    println("sum_digits(9876)={}, count_digits(100000)={}",
            sum_digits(9876), count_digits(100000))
    println("reverse_int(-405)={}, is_palindrome_int(1221)={}, is_palindrome_int(123)={}",
            reverse_int(-405), is_palindrome_int(1221), is_palindrome_int(123))

    // --- Mảng ---
    let mut v: [8]int = [9, 1, 5, 3, 7, 2, 8, 4]
    insertion_sort(&v[0], 8)
    print("sorted: ")
    for x in v { print("{} ", x) }
    println("")
    println("min={}, max={}, sorted?={}, index_of(7)={}, count_val(5)={}, contains(6)={}",
            array_min(&v[0], 8), array_max(&v[0], 8), is_sorted(&v[0], 8),
            index_of(&v[0], 8, 7), count_val(&v[0], 8, 5), contains(&v[0], 8, 6))
    reverse(&v[0], 8)
    print("reversed: ")
    for x in v { print("{} ", x) }
    println("")
    let mut w: [8]int = [0, 0, 0, 0, 0, 0, 0, 0]
    array_copy(&w[0], &v[0], 8)
    fill(&w[0], 4, 99)
    print("copy+fill: ")
    for x in w { print("{} ", x) }
    println("")

    // --- Chuỗi ---
    let u = to_upper("Ngôn ngữ G")
    let l = to_lower("HELLO World")
    let r = str_rev("abcdef")
    let rep = str_repeat("=", 10)
    println("upper={s}", u)
    println("lower={s}", l)
    println("rev={s}, repeat={s}", r, rep)
    println("count 'l' trong 'parallel' = {}, str_index('parallel','lle') = {}",
            count_char("parallel", 'l'), str_index("parallel", "lle"))
    g_free(u); g_free(l); g_free(r); g_free(rep)
    return 0
}
