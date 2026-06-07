// Kiểm tra số thực: modulo (fmod), số học hỗn hợp, ép kiểu, định dạng.

fn main() -> int {
    // Modulo số thực -> fmod
    let a: f64 = 17.5
    let b: f64 = 5.0
    println("17.5 mod 5.0 = {f}", a % b)        // 2.5

    // Số học float
    let x: f64 = 3.0
    let y: f64 = 2.0
    println("{f} {f} {f}", x + y, x * y, x / y)

    // Hỗn hợp int/float (int thăng cấp lên float)
    let n: int = 7
    let f: f64 = 2.0
    println("7 / 2.0 = {f}", n as f64 / f)

    // Ép float -> int (cắt phần thập phân)
    let pi: f64 = 3.99
    println("3.99 as int = {}", pi as int)

    // f32
    let g: f32 = 1.5
    println("f32: {f}", g as f64)

    // Modulo float với toán hạng âm
    let neg: f64 = -7.5
    println("-7.5 mod 2.0 = {f}", neg % 2.0)

    return 0
}
