// Kiểm tra match với pattern khoảng (lo..hi, lo..=hi), trộn với literal/|,
// trên số nguyên và ký tự, và match enum vét cạn (không cần '_').

enum Sign { Neg, Zero, Pos }

fn classify(n: int) -> str {
    match n {
        0 => { return "zero" }
        1..=9 => { return "small" }
        10 | 20 | 30 => { return "round" }
        11..100 => { return "medium" }
        _ => { return "large" }
    }
    return "?"
}

fn char_kind(c: char) -> str {
    match c {
        'a'..='z' => { return "lower" }
        'A'..='Z' => { return "upper" }
        '0'..='9' => { return "digit" }
        _ => { return "other" }
    }
    return "?"
}

// match enum phủ hết variant -> không cần return cuối hàm
fn sign_name(s: Sign) -> str {
    match s {
        Neg => { return "âm" }
        Zero => { return "không" }
        Pos => { return "dương" }
    }
}

fn main() -> int {
    for x in [0, 5, 20, 55, 999] {
        println("classify({}) = {s}", x, classify(x))
    }
    println("{s} {s} {s} {s}",
            char_kind('m'), char_kind('Q'), char_kind('4'), char_kind('#'))
    println("{s} {s} {s}", sign_name(Neg), sign_name(Zero), sign_name(Pos))
    return 0
}
