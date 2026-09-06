"""
Bố cục bộ nhớ & ABI của G.

VÌ SAO CẦN
==========
Trước đây `sizeof`/`alignof` được **giao hết cho C**: codegen phát `sizeof(T)`
rồi để trình biên dịch C tính. Cách đó đúng cho backend C, nhưng:

  * `static_assert(sizeof(S) == 16)` chỉ nổ **lúc biên dịch C**, với thông báo
    của C, trỏ vào file `/tmp` — không phải lỗi G;
  * backend tương lai (LLVM/WASM) **phải tự tính** offset, không có C để nhờ;
  * không có cách nào trả lời "struct này bố cục thế nào trên wasm32?" khi đang
    chạy trên x86_64 — tức không kiểm tra chéo target được.

Module này tính bố cục **độc lập với C**, theo target, dùng quy tắc ABI chuẩn
(System V / LLVM data layout cho các kiểu vô hướng).

PHẠM VI
=======
Cố ý giới hạn ở những gì G thực sự dùng và có thể tính CHẮC CHẮN:
vô hướng, con trỏ, mảng tĩnh, struct (kể cả `@packed`, `@align(N)`), enum, slice.
Không mô hình hoá bitfield/union (G chưa có).

`sizeof` của C vẫn được dùng trong mã sinh ra — module này KHÔNG thay thế nó,
mà là **nguồn chân lý thứ hai** để kiểm chứng. Có một test đối chiếu hai bên
(`tests/test_layout.py`) để bảo đảm chúng không trôi lệch nhau.
"""

from . import types as T


class LayoutError(Exception):
    pass


#: Cỡ & căn lề của kiểu vô hướng bề rộng CỐ ĐỊNH (giống nhau ở mọi target).
_FIXED = {
    "i8": (1, 1), "u8": (1, 1), "char": (1, 1), "bool": (1, 1),
    "i16": (2, 2), "u16": (2, 2),
    "i32": (4, 4), "u32": (4, 4), "int": (4, 4), "f32": (4, 4),
    "i64": (8, 8), "u64": (8, 8), "f64": (8, 8),
}


class Layout:
    """Tính bố cục cho một target cụ thể.

    `structs`: {tên: [(tên_trường, GType)]}, `attrs`: {tên: {"packed", "align"}}.
    """

    def __init__(self, target, structs=None, struct_attrs=None):
        self.target = target
        self.ptr_size = target.ptr_bits // 8
        self.structs = structs or {}
        self.struct_attrs = struct_attrs or {}
        self._cache = {}
        self._in_progress = set()

    # ------------------------------------------------------------------
    def size_of(self, ty: T.GType) -> int:
        return self._size_align(ty)[0]

    def align_of(self, ty: T.GType) -> int:
        return self._size_align(ty)[1]

    def _size_align(self, ty: T.GType):
        if ty is None:
            raise LayoutError("kiểu rỗng không có bố cục")
        k = ty.kind

        if k in ("ptr", "str", "null", "func"):
            # Con trỏ hàm giả định cùng cỡ con trỏ dữ liệu (đúng trên mọi
            # target G hỗ trợ; kiến trúc Harvard sẽ cần tách ra).
            return self.ptr_size, self.ptr_size

        if k == "slice":
            # slice<T> = { T* ptr; usize len } — hai từ máy, căn theo con trỏ.
            return self.ptr_size * 2, self.ptr_size

        if k in ("int", "float", "char", "bool"):
            name = ty.name or k
            if name in ("usize", "isize"):
                return self.ptr_size, self.ptr_size
            sa = _FIXED.get(name)
            if sa is None and ty.bits:
                n = max(1, ty.bits // 8)
                return n, n
            if sa is None:
                raise LayoutError(f"không biết bố cục của kiểu '{ty}'")
            return sa

        if k == "enum":
            # enum của G hạ thành 'enum' C -> cỡ int (ABI System V).
            return _FIXED["i32"]

        if k == "array":
            if not isinstance(ty.n, int):
                # '[]T' là con trỏ trần, không phải mảng có cỡ.
                return self.ptr_size, self.ptr_size
            esz, eal = self._size_align(ty.elem)
            return esz * ty.n, eal

        if k == "struct":
            return self._struct_size_align(ty.name)

        if k == "void":
            return 0, 1

        raise LayoutError(f"không biết bố cục của kiểu '{ty}'")

    # ------------------------------------------------------------------
    def offsets_of(self, sname: str):
        """[(tên_trường, offset, cỡ)] theo đúng thứ tự khai báo."""
        self._struct_size_align(sname)           # bảo đảm đã tính
        return self._cache[sname][2]

    def _struct_size_align(self, sname: str):
        hit = self._cache.get(sname)
        if hit is not None:
            return hit[0], hit[1]
        if sname in self._in_progress:
            raise LayoutError(
                f"struct '{sname}' chứa chính nó theo giá trị (bố cục vô hạn)")
        fields = self.structs.get(sname)
        if fields is None:
            raise LayoutError(f"struct chưa biết: '{sname}'")

        self._in_progress.add(sname)
        try:
            attrs = self.struct_attrs.get(sname, {})
            packed = bool(attrs.get("packed"))
            forced = int(attrs.get("align") or 0)

            off = 0
            max_align = 1
            out = []
            for fname, fty in fields:
                fsz, fal = self._size_align(fty)
                if packed:
                    fal = 1
                if fal > max_align:
                    max_align = fal
                off = _round_up(off, fal)
                out.append((fname, off, fsz))
                off += fsz

            if forced:
                if forced & (forced - 1):
                    raise LayoutError(
                        f"@align({forced}) trên '{sname}' phải là luỹ thừa của 2")
                max_align = max(max_align, forced)
            # Struct RỖNG: C cho sizeof == 0 (mở rộng GNU); G giữ nguyên như vậy
            # để khớp với backend C hiện tại.
            total = _round_up(off, max_align) if out else 0
            self._cache[sname] = (total, max_align, out)
            return total, max_align
        finally:
            self._in_progress.discard(sname)


def _round_up(v, a):
    return v if a <= 1 else ((v + a - 1) // a) * a


def from_checker(checker):
    """Dựng Layout từ trạng thái của một Checker đã chạy xong."""
    attrs = {}
    for name, a in getattr(checker, "struct_attrs", {}).items():
        attrs[name] = a
    return Layout(checker.target, checker.structs_ordered(), attrs)
