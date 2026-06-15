// Pattern là biến thể của enum KHÁC với subject -> lỗi.
enum A { X, Y }
enum B { P, Q }
fn main() -> int {
    let a = X
    match a {
        X => { }
        Y => { }
        P => { }
    }
    return 0
}
