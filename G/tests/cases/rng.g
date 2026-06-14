import std
fn main() -> int {
    rng_seed(42)
    let a = rand_u64()
    let b = rand_u64()
    rng_seed(42)
    let c = rand_u64()
    println("{}", a == c)
    println("{}", b != a)
    println("{}", rand_int(0, 1))
    return 0
}
