fn main() -> int {
    let x = 5
    asm { "nop" : "=r"(x) }
    return 0
}
