@packed struct Hdr { magic: u16, len: u32, flags: u8 }
fn main() -> int {
    static_assert(sizeof(Hdr) == 8, "Hdr phai dung 8 byte")
    return 0
}
