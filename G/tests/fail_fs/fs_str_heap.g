// Method 'str' cấp phát heap không dùng được khi không có libc; method chỉ đọc
// (len/at/...) thì vẫn được.
fn kmain() {
    let s = "ab"
    let n = s.len()
    let c = s.at(0)
    let t = s.upper()
}
fn main() -> int { kmain() return 0 }
