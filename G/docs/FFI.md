# FFI của G — gọi mã ngoài

Tài liệu này mô tả ba cơ chế FFI của G, khi nào dùng cái nào, và **ranh giới an
toàn** của từng cái. Nó cũng giải thích vì sao bộ sinh binding nằm **ngoài**
trình biên dịch.

---

## 1. Ba cơ chế

| Cơ chế | Ràng buộc lúc | Kiểm kiểu | Dùng khi |
|---|---|---|---|
| `extern fn` + `-l` | liên kết | ✓ (bạn khai) | thư viện luôn có mặt |
| `extern fn` + `@link` | liên kết | ✓ (bạn khai) | module tự mô tả phụ thuộc |
| `dl_open`/`dl_sym` | **chạy** | ✗ | plugin, thư viện tuỳ chọn |

Cả ba dùng **C ABI** — mẫu số chung mà hầu hết ngôn ngữ đều nói được.

---

## 2. FFI tĩnh

### 2.1 Khai báo + cờ dòng lệnh

```g
extern fn twice(x: int) -> int
fn main() -> int { println("{}", twice(21)) return 0 }
```
```sh
gc a.g -L/duong/dan -lmymath -o a
```

### 2.2 `@link` — phụ thuộc nằm cạnh khai báo

```g
@link("m") extern fn sqrt(x: f64) -> f64
@link("/opt/lib:mymath") extern fn twice(x: int) -> int   // "thư_mục:tên"
```

Người dùng module **không phải nhớ** thêm cờ khi build — đó là điểm chính. Cờ
dòng lệnh và `@link` cộng dồn với nhau.

### 2.3 `@symbol` — khi tên khác nhau

```g
@link("mymath") @symbol("gt_internal_v2_twice")
extern fn nhan_doi(x: int) -> int
```

Dùng khi tên trong thư viện xấu, có tiền tố phiên bản, hoặc không hợp lệ làm
định danh G.

---

## 3. FFI động (`dl_open`)

```g
fn main() -> int {
    let h = dl_open("./libplugin.so")
    if h == null { println("lỗi: {}", dl_error()) return 1 }
    let p = dl_sym(h, "process")
    if p == null { println("thiếu ký hiệu 'process'") return 1 }
    let f = p as fn(int) -> int      // ÉP KIỂU: bạn tự chịu trách nhiệm
    println("{}", f(21))
    dl_close(h)
    return 0
}
```

### ⚠️ Đây là ranh giới KHÔNG AN TOÀN

G **không thể** kiểm chữ ký của một ký hiệu nạp lúc chạy — nó chỉ là một địa
chỉ. Ép sai kiểu con trỏ hàm là **hành vi không xác định**, y như C. Cụ thể:

- sai số lượng/kiểu tham số → hỏng ngăn xếp;
- sai kiểu trả về → đọc giá trị rác;
- `dl_sym` trả `null` khi không có ký hiệu — **luôn phải kiểm**.

Nếu thư viện có mặt lúc liên kết thì **hãy dùng `extern fn`**: nó được kiểm kiểu.

Chỉ có ở chế độ **hosted** — `--freestanding` không có bộ nạp động và sẽ báo lỗi
biên dịch rõ ràng.

---

## 4. Sinh binding tự động (`tools/gbind.py`)

```sh
python3 tools/gbind.py /usr/include/zlib.h --link z -o zlib.g
python3 tools/gbind.py my.h --prefix my_ --strip-prefix -o my.g
```

```g
import zlib
```

### Vì sao là công cụ RIÊNG, không phải tính năng của compiler

Đây chính là ranh giới **G-Core / G-Ext**. Nếu nhét bộ sinh binding C vào
compiler thì mai lại phải nhét Python, rồi CUDA, rồi JNI — và core phình ra
mãi. Ở dạng công cụ ngoài, `gbind` chỉ dùng những gì compiler đã công khai
(`extern fn`, `@link`, `@symbol`), nên **bộ sinh cho hệ sinh thái khác có thể
viết mà không đụng một dòng nào của compiler**.

### gbind CỐ Ý bỏ sót

Nó là bộ phân tích C thực dụng, **không phải trình biên dịch C**. Nó bỏ qua —
kèm lý do ghi trong chú thích — những gì không chắc:

- hàm biến-đối-số (`printf`-style): ABI khác nhau tuỳ nền tảng;
- con trỏ hàm trong tham số;
- kiểu chưa ánh xạ được (`struct Foo*`, typedef lạ);
- macro (gbind không chạy bộ tiền xử lý).

**Một binding SAI nguy hiểm hơn nhiều so với một binding thiếu**: sai chữ ký
làm hỏng ABI lúc chạy, ở chỗ rất xa nguyên nhân. Khi nghi ngờ, gbind bỏ qua.

Luôn **đọc lại** file sinh ra trước khi dùng.

---

## 5. Ánh xạ kiểu C ↔ G

| C | G | Ghi chú |
|---|---|---|
| `int` | `int` | |
| `unsigned` | `u32` | |
| `long`/`long long` | `i64` | |
| `size_t` | `usize` | theo bề rộng con trỏ của target |
| `float`/`double` | `f32`/`f64` | |
| `char*` / `const char*` | `str` | |
| `T*` | `*T` | |
| `void*` | `*u8` | G không có con trỏ void |
| `bool`/`_Bool` | `bool` | |

Struct truyền theo giá trị qua ranh giới FFI **chưa được bảo đảm** — hãy dùng
con trỏ. Bố cục struct thì đã khớp C (xem `compiler/layout.py` và
`tests/test_layout.py` đối chiếu với trình biên dịch C thật).

---

## 6. Kiểm thử

`tests/ffi/run_ffi.sh` dựng một thư viện C thật rồi gọi từ G bằng **cả ba cơ
chế, trên cả ba backend** (c, c-ir, llvm), cộng một vòng qua `gbind`. Nó cũng
khẳng định gbind **bỏ qua** hàm biến-đối-số — một binding sai phải là lỗi test,
không phải "tính năng".
