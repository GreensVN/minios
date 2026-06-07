// Test hồi quy: phép '%' và '%=' trên số thực phải dùng fmod() (C cấm '%' cho
// double). '%=' trên ô nhớ lấy-địa-chỉ-được chỉ lượng giá đích một lần.

let mut idx_calls: int = 0

fn idx() -> int {
    idx_calls += 1
    return 1
}

fn main() -> int {
    // '%' nhị phân
    let a: f64 = 10.5
    let b: f64 = 3.0
    println("{f}", a % b)            // 1.5

    // '%=' đơn giản
    let mut x: f64 = 10.5
    x %= 3.0
    println("{f}", x)               // 1.5

    // '%=' trên phần tử mảng: đích (a[idx()]) chỉ lượng giá MỘT lần
    let mut arr: [3]f64 = [10.5, 20.5, 30.5]
    arr[idx()] %= 3.0
    println("{f} idx_calls={}", arr[1], idx_calls)   // 2.5 idx_calls=1

    return 0
}
