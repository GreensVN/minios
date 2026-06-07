// Kiểm tra defer theo block (Zig): LIFO, chạy cuối mỗi vòng lặp/khối,
// tương tác đúng với return sớm và break.
fn tai_nguyen(id: int) -> int {
    defer println("  [đóng tài nguyên {}]", id)
    println("  mở tài nguyên {}", id)
    if id == 0 {
        return -1            // return sớm vẫn chạy defer
    }
    return id * 10
}

fn main() -> int {
    // 1) defer trong khối trần — thứ tự LIFO
    {
        defer println("dọn 3")
        defer println("dọn 2")
        defer println("dọn 1")
        println("trong khối")
    }

    // 2) defer chạy cuối MỖI vòng lặp
    for i in 1..=3 {
        defer println("  hết vòng {}", i)
        println("vòng {}", i)
    }

    // 3) return sớm trong hàm
    println("kết quả = {}", tai_nguyen(0))
    println("kết quả = {}", tai_nguyen(5))

    // 4) break vẫn xả defer của vòng lặp
    let mut n: int = 0
    loop {
        defer println("  defer-loop {}", n)
        n += 1
        if n >= 2 {
            break
        }
    }
    println("xong");
    return 0
}
