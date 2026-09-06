# Kiến trúc trình biên dịch G — audit & lộ trình

Tài liệu này ghi lại **hiện trạng kiến trúc**, các **điểm yếu đã xác định**
(xếp hạng theo mức độ), và **chiến lược migration**. Nó được viết để một người
mới vào dự án hiểu được *vì sao* các lớp trừu tượng tồn tại, chứ không chỉ
*chúng là gì*.

---

## 1. Hiện trạng (trước Phase 1)

```text
nguồn .g
   ↓  lexer.py      (320 dòng)   token + ASI
   ↓  parser.py     (883 dòng)   AST, khử đường (if-expr, destructuring, ::)
   ↓  driver.py     (397 dòng)   gộp module (import), điều phối, gọi cc
   ↓  checker.py    (3629 dòng)  phân giải kiểu + kiểm tra + CHÚ THÍCH lên AST
   ↓  codegen.py    (2213 dòng)  AST + chú thích  →  mã C
   ↓  cc (gcc/clang)
```

`types.py` (152 dòng) chứa `GType` — biểu diễn kiểu **đã phân giải**, dùng chung
cho checker và codegen. Đây là phần thiết kế **tốt** và được giữ nguyên.

### Cách checker và codegen thực sự nói chuyện với nhau

Đây là điểm mấu chốt của toàn bộ audit. Checker không trả về một cấu trúc dữ
liệu mới; nó **gắn thuộc tính động lên chính các node AST**:

```python
# checker.py
def infer(self, e) -> T.GType:
    t = self._infer(e)
    e.gtype = t          # ← chú thích ngầm
    return t
```

Codegen đọc lại các chú thích đó bằng `getattr`:

```python
# codegen.py
def gtype_of(self, e): return getattr(e, "gtype", T.UNKNOWN)
```

Đã đếm được **58 vị trí** trong `codegen.py` đọc thuộc tính do checker đặt, qua
**37 tên thuộc tính** khác nhau:

```text
align arr_copy_from attrs auto_deref bindings by_ref by_ref_elem c_name
const_names const_value cur_src_file deref_left deref_right deref_subject
elem_ptr elem_type enum_variant extended gtype is_enum_variant is_extern
is_fn is_method is_static_method is_str_method iter_kind mutable
resolved_type result_type src_file var_type widen_i64 widen_signed ...
```

Không có type nào ràng buộc hợp đồng này. Nó là một **giao diện ngầm, không
được kiểm tra**, trải trên 5800 dòng của hai file lớn nhất dự án.

---

## 2. Điểm yếu đã xác định (xếp hạng)

### CRITICAL — Không có middle-end; hợp đồng checker↔codegen là ngầm

*Triệu chứng thật, không phải giả định:* mọi backend mới (LLVM/WASM/native) sẽ
phải tái hiện **chính xác** 37 thuộc tính ngầm đó, kể cả các quyết định hạ mã
tinh vi như `arr_copy_from` (sao chép tham số mảng `mut`) hay `by_ref_elem`
(`for mut x` hạ thành con trỏ). Một backend thứ hai gần như chắc chắn sẽ đọc
thiếu một thuộc tính và sinh mã sai **âm thầm** — vì `getattr(e, "x", False)`
trả về mặc định thay vì báo lỗi.

*Hệ quả kéo theo:* không có nơi nào để đặt tối ưu hoá, không có gì để verify,
không thể cache IR, không thể phân tích luồng dữ liệu.

**→ Đây là việc phải làm trước tiên, và là nội dung của Phase 1.**

### CRITICAL — Ngữ nghĩa hạ mã nằm rải trong codegen, không có chỗ kiểm chứng

Ví dụ có thật đã gây bug trong các vòng trước:

- mảng phải **sao chép** khi `let b = a` (C thì chia sẻ con trỏ);
- `defer` phải chạy **sau** khi chốt giá trị trả về (Zig/Go);
- `str.at(i)` phải kiểm biên như `a[i]`.

Cả ba đều là *quy tắc ngữ nghĩa của G*, nhưng hiện chỉ tồn tại dưới dạng vài
dòng sinh chuỗi C. Không có biểu diễn nào để một verifier soi được.

### HIGH — Không có lớp trừu tượng backend

`driver.py` gọi thẳng `Codegen(prog).generate()`. Muốn thêm backend phải sửa
driver, và không có hợp đồng nào định nghĩa "một backend là gì".

### HIGH — Không có target/HAL layer

`inb/outb/cli/sti/rdtsc/read_crN` được xử lý như built-in toàn cục trong
checker, giả định x86-64. Trên aarch64/riscv chúng vô nghĩa nhưng vẫn qua được
checker.

### MEDIUM — Memory model chưa được hình thức hoá

Có `*T`, `g_alloc/g_free`, và phân tích con trỏ treo (khá tốt). Nhưng chưa có
khái niệm rõ ràng cho owned/borrowed, nên không thể thêm ownership analysis mà
không đụng vào toàn bộ checker.

### MEDIUM — Chưa có generics / traits / Result

Chưa có `Slice<T>` thật (mới chỉ có lát cắt **chuỗi**). `[]T` mang theo độ dài
là tiền đề cho hầu hết các thứ còn lại.

### MEDIUM — Diagnostics chưa có cấu trúc

`GError` mang `(file, line, col, msg, phase)` dạng chuỗi. Không có mã lỗi, span
phụ, hay fix-it → không đủ cho LSP.

### LOW — Chưa có incremental compilation / package manager

Đúng, nhưng **chưa phải nút thắt**: không có IR thì không có gì để cache.
Những việc này phụ thuộc Phase 1.

---

## 3. Chiến lược migration (vì sao làm theo thứ tự này)

Nguyên tắc: **không đập đi làm lại**. C backend hiện tại đang chạy đúng 210 ca
test — nó là tài sản, không phải nợ.

```text
Giai đoạn A  (ĐÃ XONG — xem §4)
  Thêm G-IR SONG SONG với đường hiện tại.
  AST → Typed AST → G-IR → verifier.
  Đường sinh mã C giữ NGUYÊN, không đụng tới.
  → rủi ro hồi quy bằng 0; chứng minh IR biểu diễn được toàn bộ ngôn ngữ.

Giai đoạn B  (tiếp theo)
  Viết backend C thứ hai đọc TỪ IR (`--backend=c-ir`).
  Chạy song song, so khớp đầu ra với backend hiện tại trên cả bộ test.
  Khi khớp 100% → đổi mặc định, backend cũ thành fallback.

Giai đoạn C
  Xoá backend cũ. Lúc này LLVM/WASM chỉ là "một backend nữa đọc IR".
```

Giai đoạn A là điều kiện tiên quyết cho *mọi thứ* trong roadmap: tối ưu hoá,
cache, backend mới, phân tích. Vì vậy nó được làm trước generics/traits/package
manager — dù những thứ kia "nhìn thấy được" hơn với người dùng.

---

## 4. Đã triển khai trong Phase 1

| Thành phần | File | Vai trò |
|---|---|---|
| Mô hình G-IR | `compiler/ir.py` | Kiểu dữ liệu IR: Module/Func/Block/Instr/Value |
| Hạ mã AST→IR | `compiler/irgen.py` | Typed AST → G-IR (CFG có basic block) |
| Trình kiểm IR | `compiler/irverify.py` | Kiểm bất biến cấu trúc & kiểu |
| Giao diện backend | `compiler/backend.py` | `Backend` ABC + registry |
| CLI | `--emit-ir`, `--verify-ir` | Xem & kiểm IR |

**G-IR là three-address code trên CFG có basic block.** Các cấu trúc điều khiển
cấp cao được **hạ hẳn**, không giữ dạng cây:

- `if/while/loop/for` → `Jump` / `Branch` giữa các block;
- `match` → `Switch` (hoặc chuỗi `Branch` khi pattern không phải hằng);
- `defer` → nhân bản lời gọi tại **mọi** điểm thoát, theo thứ tự LIFO —
  đây chính là chỗ ngữ nghĩa "defer chạy sau khi chốt giá trị trả về" trở nên
  **nhìn thấy được** trong IR thay vì ẩn trong chuỗi C;
- biến cục bộ → `Alloca` + `Load`/`Store` (dạng địa chỉ, chưa SSA);
- truy cập trường/phần tử → `FieldAddr` / `ElemAddr` rồi `Load`/`Store`.

Cách này giữ IR **đủ thấp để LLVM/WASM tiêu thụ trực tiếp**, nhưng vẫn mang đủ
thông tin kiểu (`GType` dùng lại nguyên vẹn) để backend C tái tạo mã đọc được.

### Điều gì được kiểm chứng

`tests/run_ir.sh` hạ **toàn bộ** ví dụ + ca test sang IR rồi chạy verifier. Đây
là bằng chứng cho tuyên bố "IR biểu diễn được cả ngôn ngữ" — không phải lời hứa.

---

## 5. Đã triển khai trong Phase 2 (một phần): Slice

`slice<T>` / `mut slice<T>` — con trỏ béo `(ptr, len)`; xem README 0.13.0.

Vì sao slice được làm **trước** generics/traits, dù roadmap gốc xếp sau: nó
không cần thay đổi hệ kiểu (chỉ thêm một `kind`), nhưng loại bỏ được thành ngữ
"con trỏ trần + độ dài rời" ở mọi nơi — thứ mà generics/traits sẽ phải xây
chồng lên. Làm ngược lại thì phải viết lại container hai lần.

Ba bất biến của thiết kế, được khoá bằng test:
1. slice **không bao giờ** tự rã thành `*T` (rã = vứt độ dài);
2. quyền ghi ở **kiểu** (`mut slice<T>`), không ở biến giữ nó;
3. chuyển ngầm mảng→slice quyết định ở **một chỗ duy nhất** (`Checker.coerce`),
   codegen và irgen chỉ đọc dấu — không lặp lại suy luận đích.

## 6. Đã triển khai trong Phase 5 (một phần): Target/HAL

`compiler/target.py` — mô hình **năng lực**; xem README 0.14.0. Việc này được
kéo lên trước generics vì nó không phải "tính năng thiếu" mà là một **lỗi đúng
nghĩa**: mã dùng `outb` biên dịch sạch trên aarch64 rồi chạy no-op.

Còn lại của Phase 5: chọn toolchain chéo tự động, layout/ABI theo target
(hiện `ptr_bits` đã có trong `Target` nhưng `types.py` vẫn giả định 64-bit).

## 7. Giai đoạn B đang chạy: backend C đọc từ IR

`--backend=c-ir` khớp **101/101, 0 khác, 0 chưa hỗ trợ** — gồm cả freestanding
và panic (`tests/run_backend_diff.sh`). **Tiêu chí thoát của Giai đoạn B đã
đạt.**

Nguyên tắc đã theo suốt: mọi thứ còn thiếu đều hạ trong `irgen.py`, **không
phải** trong backend. Bằng chứng: *mọi* khác biệt mà bộ so khớp tìm ra đều là
lỗi của tầng hạ mã IR — tức là lỗi mà LLVM/WASM cũng sẽ dính.

Bài học về PHẠM VI kiểm chứng: bộ so khớp ban đầu chỉ chạy `examples/` +
`tests/cases/` và báo "93/93 khớp" khi `asm` mở rộng, `s.at()` và chế độ
freestanding vẫn còn hỏng. Chỉ khi mở rộng sang `tests/freestanding/` và
`tests/panic/` mới lộ ra. Một bộ so khớp chỉ mạnh bằng phạm vi đầu vào của nó.

### Giai đoạn C (tiếp theo)

Đổi mặc định sang backend đọc-từ-IR, rồi xoá đường AST→C. Chưa làm trong bản
này: nên để hai backend chạy song song thêm một thời gian, vì bộ so khớp là
mạng an toàn rẻ nhất đang có.

## 8. CHƯA làm (nói rõ để không gây hiểu nhầm)

Các mục sau **chưa được triển khai**, mới chỉ có chỗ đứng trong kiến trúc:

- backend LLVM / WASM / native;
- generics, traits, `Result<T,E>`;
- ownership/borrow CHECKING tự động (mô hình đã hình thức hoá trong
  docs/MEMORY.md và allocator đã thay thế được, nhưng compiler CHƯA theo dõi
  vòng đời heap: use-after-free/double-free vẫn là UB);
- incremental compilation, IR cache, package manager, LSP.

Roadmap chi tiết cho từng mục: xem §2 (xếp hạng) và §3 (thứ tự).
