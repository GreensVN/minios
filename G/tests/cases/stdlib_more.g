import std
fn main() -> int {
    println("{}", ncr(6, 2))
    println("{}", npr(6, 2))
    println("{}", sum_to(10))
    println("{}", num_divisors(12))
    println("{}", is_perfect(6))
    println("{}", totient(10))
    println("{}", hex_val('a'))
    println("{}", gcd3(12, 18, 24))
    println("{}", mod_floor(-1, 3))
    println("{}", is_power_of_two(64))
    println("{}", next_power_of_two(100))
    let mut v: [5]int = [3, 1, 4, 1, 5]
    clamp_array(&v[0], 5, 2, 4)
    print("clamped:")
    for i in 0..5 { print(" {}", v[i]) }
    println("")
    return 0
}
