// 'return' trong 'defer' là vô nghĩa (và làm codegen đệ quy vô hạn) -> cấm.
fn f() -> int {
    defer return 9
    return 1
}
fn main() -> int {
    return f()
}
