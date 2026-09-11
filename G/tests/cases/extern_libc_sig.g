// 'extern fn' trùng hàm mà runtime tự định nghĩa (memcpy/strlen...) với chữ ký
// G "gần đúng" (*u8 thay vì void*) — không được phát lại nguyên mẫu C (trước đây
// gcc báo 'conflicting types').
extern fn memcpy(d: *u8, s: *u8, n: usize) -> *u8
extern fn strlen(s: str) -> usize
extern fn puts(s: str) -> int

fn main() -> int {
    let a: [4]u8 = [1, 2, 3, 4]
    let mut b: [4]u8 = [0, 0, 0, 0]
    memcpy(&b[0], &a[0], 4)
    println("{} {}", b[3], strlen("abc"))
    puts("hi")
    return 0
}
