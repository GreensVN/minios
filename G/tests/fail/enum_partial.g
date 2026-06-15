// match trên enum không có '_' phải phủ HẾT mọi biến thể.
enum Dir { N, E, S, W }
fn main() -> int {
    let d = N
    match d {
        N => { }
        E => { }
    }
    return 0
}
