// Cảnh báo (không chặn biên dịch): biến khai báo mà không đọc, và 'let mut' mà
// không bao giờ ghi. Tên bắt đầu bằng '_' được miễn (quy ước "cố ý bỏ qua").
struct C { n: int }
impl C { fn inc(self) { self.n += 1 } }
fn take(p: *int) { *p = 9 }
fn main() -> int {
    let khong_dung = 5           // -> cảnh báo
    let _bo_qua = 6              // im lặng (tiền tố '_')
    let mut mut_thua = 7         // -> cảnh báo ('mut' không cần)
    println("{}", mut_thua)

    // Các dạng ghi GIÁN TIẾP dưới đây KHÔNG được coi là 'mut' thừa:
    let mut c = C{n: 0}
    c.inc()                      // method tự-sửa
    let mut v = 5
    take(&v)                     // lấy địa chỉ để ghi
    let mut arr: [2]int = [1, 2]
    for mut x in arr { x += 1 }  // duyệt theo tham chiếu
    let mut p: *int = g_alloc(int, 2)
    p[0] = 1                     // ghi qua con trỏ
    println("{} {} {} {}", c.n, v, arr[0], p[0])
    g_free(p)
    return 0
}
