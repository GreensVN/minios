# Mô hình bộ nhớ của G

Tài liệu này định nghĩa **chính xác** ngữ nghĩa bộ nhớ của G: cái gì sở hữu cái
gì, cái gì chỉ mượn, và điều gì xảy ra khi bạn làm sai. Nó cũng nói rõ những gì
G **chưa** bảo đảm — im lặng về điểm yếu là cách nhanh nhất khiến người dùng tin
nhầm.

---

## 1. Bốn hạng bộ nhớ

G phân biệt bốn hạng, theo **nơi cấp phát** chứ không theo cú pháp:

| Hạng | Ví dụ | Vòng đời | Ai giải phóng |
|---|---|---|---|
| **Giá trị** (value) | `let x = 5`, `let p = P{..}`, `[4]int` | Hết scope | Tự động (stack) |
| **Tĩnh** (static) | `let g: int = 1` ở cấp cao nhất, literal chuỗi | Toàn chương trình | Không ai |
| **Sở hữu** (owned) | `alloc(T, n)`, `format(...)`, `s.upper()` | Tới khi `free` | **Bạn**, tường minh |
| **Mượn** (borrowed) | `&x`, `slice<T>`, tham số `*T` | ≤ vòng đời nguồn | Không ai |

Nguyên tắc: **mượn không bao giờ giải phóng**. Nếu bạn nhận một `*T` hay
`slice<T>`, bạn không được `free` nó — bạn không sở hữu vùng nhớ đó.

---

## 2. Ai sở hữu cái gì

### Giá trị
Mảng tĩnh `[N]T`, struct, và mọi kiểu vô hướng có **ngữ nghĩa giá trị**:
`let b = a` trên `[4]int` **sao chép** (đây từng là một lỗi thật — xem 0.11.0).
Truyền vào hàm cũng là sao chép; muốn hàm sửa được thì dùng `mut slice<T>` hoặc
`*T`.

### Sở hữu
Mọi thứ *tạo ra bộ nhớ mới* đều trả về quyền sở hữu cho người gọi:

```g
let p = alloc(int, 100)      // sở hữu -> phải free(p)
let s = format("{}", 42)     // sở hữu -> phải free(s)
let u = "abc".upper()        // sở hữu -> phải free(u)
defer free(p)                // cách dùng khuyến nghị
```

G **không** có bộ thu gom rác và **không** tự chèn `free`. Không giải phóng =
rò rỉ. Với chương trình chạy rồi thoát ngay thì vô hại; với vòng lặp dài thì
không.

### Mượn
`&x` tạo một con trỏ **mượn** tới ô nhớ của `x`. `slice<T>` mượn một đoạn của
mảng/slice khác. Cả hai **không mang quyền sở hữu**:

```g
fn tong(xs: slice<int>) -> int { ... }   // mượn, không free
let a: [4]int = [1,2,3,4]
tong(a)                                   // a vẫn thuộc về người gọi
```

---

## 3. Điều G BẢO ĐẢM (kiểm lúc biên dịch)

- **Con trỏ treo do trả về stack**: `return &x` với `x` cục bộ là **lỗi biên
  dịch**, kể cả qua `&a[0]` hay `&s.f`.
- **Ghi qua slice chỉ đọc**: `slice<T>` không ghi được; cần `mut slice<T>`.
- **Mượn quyền ghi từ giá trị bất biến**: truyền mảng `let` cho `mut slice<T>`
  bị từ chối.
- **Slice không tự rã thành con trỏ trần** — làm vậy là vứt bỏ độ dài.
- **Giải tham chiếu `null` tĩnh**: `let p: *int = null` rồi `*p` bị bắt.
- **Kiểu phần tử của slice khớp tuyệt đối** (`slice<i32>` ≠ `slice<i64>`).

## 4. Điều G BẢO ĐẢM (kiểm lúc chạy, tắt được bằng `--no-checks`)

- **Vượt biên mảng tĩnh** và **vượt biên slice** → panic, mã thoát 101.
  Slice mang theo độ dài nên kiểm vẫn đúng **sau khi đi qua nhiều lời gọi hàm**.
- **Chia cho 0** → panic.
- **`s.at(i)` ngoài biên** → panic (không trả `'\0'` âm thầm).

## 5. Điều G **KHÔNG** bảo đảm

Nói thẳng, vì đây là ngôn ngữ hệ thống:

- **use-after-free** — dùng con trỏ sau `free` là **hành vi không xác định**.
  G không theo dõi vòng đời heap.
- **double-free** — cũng là UB.
- **rò rỉ** — không có GC; quên `free` là rò rỉ.
- **con trỏ treo qua heap** — `free(p)` rồi `q` (đã sao chép từ `p`) vẫn trỏ tới
  vùng đã trả.
- **aliasing** — hai `mut slice` chồng lấn nhau không bị phát hiện.
- **an toàn luồng** — G chưa có mô hình đồng thời.

Công cụ để bù: `gcc -fsanitize=address` trên mã C sinh ra
(`bash tests/run_asan.sh`, `LEAKS=1` để bắt rò rỉ).

---

## 6. Allocator (từ 0.20.0)

`alloc`/`free`/`realloc` nhận **allocator tường minh tuỳ chọn**. Không truyền
thì dùng allocator mặc định của chương trình.

```g
let p = alloc(int, 64)                 // allocator mặc định
let q = alloc_in(arena, Node, 10)      // allocator chỉ định
free_in(arena, q)
```

Một allocator là một **struct có bốn hàm** (bảng hàm — vtable):

```g
struct Allocator {
    ctx:     *u8                            // dữ liệu riêng của allocator
    alloc:   fn(*u8, usize, usize) -> *u8   // (ctx, số phần tử, cỡ phần tử)
    free:    fn(*u8, *u8)                   // (ctx, con trỏ)
    realloc: fn(*u8, *u8, usize, usize) -> *u8
}
```

Vì sao là struct-vtable chứ không phải trait: G **chưa có trait** (đó là mục #4
trong lộ trình). Struct-vtable cho đúng khả năng cần thiết ngay bây giờ, hoạt
động ở cả freestanding, và sau này bọc lại bằng trait mà không đổi ABI.

### Allocator dựng sẵn

| Tên | Dùng cho | Freestanding |
|---|---|---|
| `heap_allocator()` | mặc định (libc malloc) | ✗ |
| `arena_allocator(buf)` | cấp phát nhanh, giải phóng **một lượt** | ✓ |
| `fixed_allocator(buf)` | vùng nhớ cố định, không tăng | ✓ |

`arena_allocator` nhận một `mut slice<u8>` do BẠN cung cấp — nên nó chạy được
trong kernel, nơi không có libc:

```g
fn kmain() {
    let mut backing: [4096]u8 = [0; 4096]
    let mut a = arena_allocator(backing)
    let p = alloc_in(a, u32, 16)
    // ... không cần free từng cái; cả arena chết cùng 'backing'
}
```

### Vì sao `alloc` thay cho `g_alloc`

`g_alloc(T, n)` là **macro C** nội tuyến `calloc`, nên: không thay thế được,
không dùng được ở freestanding, và tên rò rỉ tiền tố `g_` của runtime ra mặt
người dùng. `alloc`/`free` là built-in thật của G, hạ qua allocator. `g_alloc`
vẫn hoạt động (tương thích ngược) nhưng là bí danh của `alloc`.
