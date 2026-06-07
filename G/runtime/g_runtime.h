/* === G Language Runtime ===
 * Header nền tảng tự động include vào mọi chương trình G.
 * Cầu nối tới thư viện chuẩn C + các tiện ích lấy cảm hứng từ Rust/Zig.
 */
#ifndef G_RUNTIME_H
#define G_RUNTIME_H

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stddef.h>
#include <math.h>

/* ---- Cấp phát bộ nhớ (Zig/Rust style) ---- */
#define g_alloc(T, n)        ((T*)calloc((size_t)(n), sizeof(T)))
#define g_realloc(p, T, n)   ((T*)realloc((p), sizeof(T) * (size_t)(n)))
#define g_free(p)            free((void*)(p))

/* ---- panic: dừng chương trình (giống Rust) ---- */
_Noreturn static inline void g_panic(const char* msg) {
    fprintf(stderr, "\033[1;31mG panic:\033[0m %s\n", msg);
    exit(101);
}

/* ---- unreachable/todo (Rust/Zig): đánh dấu nhánh không thể tới / chưa làm ---- */
_Noreturn static inline void g_unreachable(const char* where) {
    fprintf(stderr, "\033[1;31mG unreachable:\033[0m %s\n", where);
    exit(101);
}
_Noreturn static inline void g_todo(const char* where) {
    fprintf(stderr, "\033[1;33mG todo:\033[0m chưa cài đặt: %s\n", where);
    exit(101);
}

/* ---- min/max/abs/clamp: statement-expression, đánh giá đối số đúng MỘT lần.
 *      (Trình sinh mã G nội tuyến phiên bản riêng; các macro này tiện cho asm/C.) */
#define g_min(a, b)      ({ __auto_type _ga = (a); __auto_type _gb = (b); _ga < _gb ? _ga : _gb; })
#define g_max(a, b)      ({ __auto_type _ga = (a); __auto_type _gb = (b); _ga > _gb ? _ga : _gb; })
#define g_abs(x)         ({ __auto_type _gx = (x); _gx < 0 ? -_gx : _gx; })
#define g_clamp(x, lo, hi) ({ __auto_type _gc = (x); __auto_type _gl = (lo); __auto_type _gh = (hi); \
                              _gc < _gl ? _gl : (_gc > _gh ? _gh : _gc); })
#define g_swap(T, a, b)  do { T _gt = (a); (a) = (b); (b) = _gt; } while (0)

/* ---- Tiện ích chuỗi (cấp phát trên heap; nhớ g_free khi xong) ----
 * G coi 'str' là 'const char*'. Các hàm dưới đây trả về chuỗi mới trên heap
 * (trừ hàm chỉ đọc). Thiết kế an toàn null: chuỗi NULL coi như rỗng. */
static inline const char* g_str_dup(const char* s) {
    if (!s) s = "";
    size_t n = strlen(s);
    char* p = (char*)malloc(n + 1);
    if (p) memcpy(p, s, n + 1);
    return p;
}

static inline const char* g_str_concat(const char* a, const char* b) {
    if (!a) a = "";
    if (!b) b = "";
    size_t na = strlen(a), nb = strlen(b);
    char* p = (char*)malloc(na + nb + 1);
    if (!p) return NULL;
    memcpy(p, a, na);
    memcpy(p + na, b, nb + 1);
    return p;
}

/* Cắt chuỗi con [start, start+len) — chỉ số/độ dài được kẹp vào biên hợp lệ. */
static inline const char* g_substr(const char* s, ptrdiff_t start, ptrdiff_t len) {
    if (!s) s = "";
    ptrdiff_t n = (ptrdiff_t)strlen(s);
    if (start < 0) start = 0;
    if (start > n) start = n;
    if (len < 0) len = 0;
    if (start + len > n) len = n - start;
    char* p = (char*)malloc((size_t)len + 1);
    if (!p) return NULL;
    memcpy(p, s + start, (size_t)len);
    p[len] = '\0';
    return p;
}

static inline bool g_str_eq(const char* a, const char* b) {
    if (a == b) return true;
    if (!a || !b) return false;
    return strcmp(a, b) == 0;
}

/* Vị trí xuất hiện đầu tiên của 'needle' trong 'hay', hoặc -1. */
static inline ptrdiff_t g_str_index(const char* hay, const char* needle) {
    if (!hay || !needle) return -1;
    const char* p = strstr(hay, needle);
    return p ? (ptrdiff_t)(p - hay) : -1;
}

static inline bool g_str_contains(const char* hay, const char* needle) {
    return g_str_index(hay, needle) >= 0;
}

static inline bool g_str_starts_with(const char* s, const char* pre) {
    if (!s || !pre) return false;
    size_t np = strlen(pre);
    return strncmp(s, pre, np) == 0;
}

static inline bool g_str_ends_with(const char* s, const char* suf) {
    if (!s || !suf) return false;
    size_t ns = strlen(s), nf = strlen(suf);
    return nf <= ns && memcmp(s + ns - nf, suf, nf) == 0;
}

static inline int64_t g_parse_int(const char* s) {
    if (!s) return 0;
    return (int64_t)strtoll(s, NULL, 10);
}

static inline double g_parse_float(const char* s) {
    if (!s) return 0.0;
    return strtod(s, NULL);
}

/* Chuyển số nguyên thành chuỗi mới trên heap (cơ số 10). */
static inline const char* g_int_to_str(int64_t v) {
    char buf[32];
    snprintf(buf, sizeof(buf), "%lld", (long long)v);
    return g_str_dup(buf);
}

/* ---- giá trị nhỏ nhất/lớn nhất theo kiểu (tiện cho comptime) ---- */
#define G_I8_MAX   127
#define G_I8_MIN   (-128)
#define G_I16_MAX  32767
#define G_I16_MIN  (-32768)
#define G_I32_MAX  2147483647
#define G_I32_MIN  (-2147483647 - 1)
#define G_I64_MAX  9223372036854775807LL
#define G_I64_MIN  (-9223372036854775807LL - 1)
#define G_U8_MAX   255u
#define G_U16_MAX  65535u
#define G_U32_MAX  4294967295u
#define G_U64_MAX  18446744073709551615ULL

#endif /* G_RUNTIME_H */
