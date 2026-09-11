// 'if' và 'match' ở vị trí BIỂU THỨC (cho một giá trị, như Rust).
enum St { Idle, Run, Done }
fn label(s: St) -> str {
    return match s { St.Idle => "idle" St.Run => "run" St.Done => "done" }
}
fn main() -> int {
    let v = if 3 > 2 { 10 } else { 20 }
    println("{}", v)
    println("{}", label(St.Run))
    let n = 7
    println("{}", match n { 1..=5 => 1 x if x > 6 => 2 _ => 3 })
    println("{}", if n < 0 { "neg" } else if n == 0 { "zero" } else { "pos" })
    println("{}", match "go" { "stop" => 0 "go" => 1 _ => -1 })
    // lồng nhau + dùng làm đối số
    println("{}", if true { match n { 7 => 70 _ => 0 } } else { 0 })
    // kiểu chung của các nhánh số
    let f = match n { 7 => 1.5 _ => 2 }
    println("{} {}", f, typeof(f))
    return 0
}
