"""
Giao diện backend của G.

VÌ SAO
======
Trước đây `driver.py` gọi thẳng `Codegen(prog).generate()`. Muốn thêm backend
phải sửa driver, và không có định nghĩa nào cho "một backend là gì" — nên
backend thứ hai sẽ tất yếu sao chép nhầm các giả định của backend thứ nhất.

File này định nghĩa hợp đồng đó, và một registry để chọn backend theo tên.

HAI HỌ BACKEND
==============
Trong giai đoạn chuyển đổi, G có hai họ backend cùng tồn tại (có chủ ý — xem
ARCHITECTURE.md §3):

  * `AstBackend`  — nhận Typed AST. Backend C hiện tại thuộc nhóm này. Nó đã
    chạy đúng toàn bộ bộ test nên được giữ nguyên làm mặc định.
  * `IRBackend`   — nhận G-IR. Mọi backend TƯƠNG LAI (LLVM/WASM/native, và bản
    C viết lại) thuộc nhóm này.

Driver biết cả hai, nên việc chuyển dần từng backend sang IR không cần đụng vào
phần điều phối.
"""

from abc import ABC, abstractmethod


class BackendError(Exception):
    pass


class Backend(ABC):
    """Lớp cơ sở chung."""

    name = "?"
    #: đuôi file mà backend này xuất ra ('.c', '.ll', '.wat', ...)
    output_ext = ".out"
    #: backend sinh mã nguồn cần biên dịch tiếp bằng cc?
    needs_cc = False

    @abstractmethod
    def emit(self, unit) -> str:
        """Sinh mã đích từ đơn vị biên dịch (AST hoặc IR tuỳ họ backend)."""

    def describe(self) -> str:
        return f"{self.name} (-> {self.output_ext})"


class AstBackend(Backend):
    """Backend nhận Typed AST (`ast_nodes.Program` đã qua checker)."""
    consumes = "ast"


class IRBackend(Backend):
    """Backend nhận G-IR (`ir.Module`)."""
    consumes = "ir"


# ----------------------------------------------------------------------
# registry
# ----------------------------------------------------------------------
_REGISTRY = {}


def register(cls):
    """Đăng ký một lớp backend (dùng làm decorator)."""
    _REGISTRY[cls.name] = cls
    return cls


def get(name):
    if name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY)) or "(chưa có)"
        raise BackendError(
            f"backend không tồn tại: '{name}' — có: {known}")
    return _REGISTRY[name]()


def available():
    return sorted(_REGISTRY)


# ----------------------------------------------------------------------
# backend C hiện tại (đọc từ AST)
# ----------------------------------------------------------------------
@register
class CBackend(AstBackend):
    """Backend C đang dùng làm mặc định.

    Đây là bản sinh mã đã chạy đúng toàn bộ bộ test; nó CỐ Ý vẫn đọc từ AST.
    Bản đọc-từ-IR sẽ được thêm cạnh nó rồi so khớp đầu ra trước khi thay thế
    (ARCHITECTURE.md §3, Giai đoạn B).
    """
    name = "c"
    output_ext = ".c"
    needs_cc = True

    def emit(self, unit) -> str:
        from .codegen import Codegen
        return Codegen(unit).generate()


@register
class IRTextBackend(IRBackend):
    """Backend 'ir' — xuất G-IR dạng văn bản.

    Không sinh mã chạy được; dùng để soi/kiểm IR và làm backend tham chiếu đầu
    tiên chứng minh giao diện IRBackend hoạt động.
    """
    name = "ir"
    output_ext = ".gir"
    needs_cc = False

    def emit(self, unit) -> str:
        return str(unit)
