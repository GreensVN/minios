// Cận trên/bước của 'for i in a..b' phải được lượng giá ĐÚNG MỘT LẦN (ngữ nghĩa
// Rust), không gọi lại mỗi vòng lặp. Đây là test hồi quy cho lỗi tính lại cận.

let mut end_calls: int = 0
let mut step_calls: int = 0

fn hi() -> int {
    end_calls += 1
    return 4
}

fn st() -> int {
    step_calls += 1
    return 1
}

fn main() -> int {
    // Cận trên là lời gọi hàm: phải gọi đúng 1 lần dù lặp nhiều vòng.
    let mut sum: int = 0
    for i in 0..hi() {
        sum += i
    }
    println("sum={} end_calls={}", sum, end_calls)   // sum=6 end_calls=1

    // Cận trên VÀ bước đều là lời gọi: mỗi cái gọi đúng 1 lần.
    let mut s2: int = 0
    for i in 0..hi() step st() {
        s2 += i
    }
    println("s2={} end_calls={} step_calls={}", s2, end_calls, step_calls)

    // Cận thay đổi trong thân không ảnh hưởng số vòng (đã chốt lúc vào vòng).
    let mut n: int = 3
    let mut iters: int = 0
    for i in 0..n {
        n += 10
        iters += 1
    }
    println("iters={}", iters)   // iters=3

    return 0
}
