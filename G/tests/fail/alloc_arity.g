struct Node { v: int }
fn main() -> int {
    let n = g_alloc(Node)          // thiếu số lượng -> lỗi G (không rò macro C)
    let a: [3]int = [1, 2, 3]
    g_free(a)                      // mảng tĩnh
    let k = 5
    g_free(k)                      // không phải con trỏ
    return 0
}
