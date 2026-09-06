//! accept x86_64-linux
//! reject wasm32 static_assert thất bại lúc biên dịch: bo cuc 64-bit
// Bố cục phụ thuộc BỀ RỘNG CON TRỎ: cùng một struct có cỡ khác nhau trên
// target 64-bit và 32-bit. Trước đây 'usize' hardcode 64-bit nên wasm32 tính sai.
struct P { p: *u32, n: usize }
fn main() -> int {
    static_assert(sizeof(P) == 16, "bo cuc 64-bit")
    return 0
}
