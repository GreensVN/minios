// format() sai số đối số so với placeholder -> phải báo lỗi.
import std

fn main() -> int {
    let s = format("{} và {}", 1)
    g_free(s)
    return 0
}
