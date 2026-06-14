// Kiểm tra match có 'guard' (if) và 'binding' (bắt giá trị vào biến) — gồm cả
// trường hợp binding + guard rớt xuống nhánh kế khi guard sai (vốn từng crash).

fn classify(n: int) -> str {
    match n {
        x if x < 0   => { return "âm" }
        0            => { return "không" }
        x if x > 100 => { return "lớn" }
        x            => { return "thường" }   // binding mặc định, dùng được biến x
    }
}

// Guard tham chiếu biến binding nhiều lần
fn bucket(n: int) -> int {
    match n {
        x if x % 15 == 0 => { return 15 }
        x if x % 3 == 0  => { return 3 }
        x if x % 5 == 0  => { return 5 }
        _                => { return 0 }
    }
}

fn sign_word(s: str) -> str {
    match s {
        "pos" if true => { return "dương" }   // pattern + guard
        "neg"         => { return "âm" }
        _             => { return "khác" }
    }
}

fn main() -> int {
    for v in [-7, 0, 42, 500] {
        println("classify({}) = {s}", v, classify(v))
    }
    for v in [30, 9, 25, 7] {
        println("bucket({}) = {}", v, bucket(v))
    }
    println("{s} {s} {s}", sign_word("pos"), sign_word("neg"), sign_word("zzz"))

    // match dùng làm câu lệnh giữa hàm (không phải nhánh cuối) + binding bắt giá trị
    let mut total: int = 0
    for v in [1, 2, 3, 4, 5, 6] {
        match v {
            x if x % 2 == 0 => { total += x }
            _               => { total -= 1 }
        }
    }
    println("total = {}", total)
    return 0
}
