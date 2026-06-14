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
#include <time.h>

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

/* Đảo ngược chuỗi -> chuỗi mới (heap). */
static inline const char* g_str_rev(const char* s) {
    if (!s) s = "";
    size_t n = strlen(s);
    char* p = (char*)malloc(n + 1);
    if (!p) return NULL;
    for (size_t i = 0; i < n; i++) p[i] = s[n - 1 - i];
    p[n] = '\0';
    return p;
}

/* Chuyển sang CHỮ HOA / chữ thường (ASCII) -> chuỗi mới (heap). */
static inline const char* g_str_upper(const char* s) {
    if (!s) s = "";
    size_t n = strlen(s);
    char* p = (char*)malloc(n + 1);
    if (!p) return NULL;
    for (size_t i = 0; i < n; i++) {
        char c = s[i];
        p[i] = (c >= 'a' && c <= 'z') ? (char)(c - 32) : c;
    }
    p[n] = '\0';
    return p;
}
static inline const char* g_str_lower(const char* s) {
    if (!s) s = "";
    size_t n = strlen(s);
    char* p = (char*)malloc(n + 1);
    if (!p) return NULL;
    for (size_t i = 0; i < n; i++) {
        char c = s[i];
        p[i] = (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c;
    }
    p[n] = '\0';
    return p;
}

/* Lặp chuỗi 's' đúng 'k' lần -> chuỗi mới (heap). k<=0 -> chuỗi rỗng. */
static inline const char* g_str_repeat(const char* s, ptrdiff_t k) {
    if (!s) s = "";
    if (k < 0) k = 0;
    size_t n = strlen(s);
    char* p = (char*)malloc(n * (size_t)k + 1);
    if (!p) return NULL;
    for (ptrdiff_t i = 0; i < k; i++) memcpy(p + (size_t)i * n, s, n);
    p[n * (size_t)k] = '\0';
    return p;
}

/* Đếm số lần ký tự 'c' xuất hiện trong chuỗi. */
static inline ptrdiff_t g_str_count(const char* s, char c) {
    if (!s) return 0;
    ptrdiff_t cnt = 0;
    for (; *s; s++) if (*s == c) cnt++;
    return cnt;
}

/* Cắt khoảng trắng ASCII đầu/cuối -> chuỗi mới (heap). */
static inline const char* g_str_trim(const char* s) {
    if (!s) s = "";
    const char* a = s;
    while (*a == ' ' || *a == '\t' || *a == '\n' || *a == '\r'
           || *a == '\f' || *a == '\v') a++;
    const char* b = a + strlen(a);
    while (b > a && (b[-1] == ' ' || b[-1] == '\t' || b[-1] == '\n'
                     || b[-1] == '\r' || b[-1] == '\f' || b[-1] == '\v')) b--;
    size_t n = (size_t)(b - a);
    char* p = (char*)malloc(n + 1);
    if (!p) return NULL;
    memcpy(p, a, n);
    p[n] = '\0';
    return p;
}

/* Thay mọi ký tự 'from' bằng 'to' -> chuỗi mới (heap). */
static inline const char* g_str_replace_char(const char* s, char from, char to) {
    if (!s) s = "";
    size_t n = strlen(s);
    char* p = (char*)malloc(n + 1);
    if (!p) return NULL;
    for (size_t i = 0; i < n; i++) p[i] = (s[i] == from) ? to : s[i];
    p[n] = '\0';
    return p;
}

/* ---- Đọc đầu vào từ stdin (cấp phát heap -> nhớ g_free với g_read_line) ----
 * Trước đây G không có cách đọc đầu vào nào — các hàm này mở khoá chương trình
 * tương tác (đọc dòng/số). Thiết kế an toàn: EOF -> NULL/0. */
static inline const char* g_read_line(void) {
    size_t cap = 64, len = 0;
    char* buf = (char*)malloc(cap);
    if (!buf) return NULL;
    int c;
    while ((c = getchar()) != EOF && c != '\n') {
        if (len + 1 >= cap) {
            cap *= 2;
            char* nb = (char*)realloc(buf, cap);
            if (!nb) { free(buf); return NULL; }
            buf = nb;
        }
        buf[len++] = (char)c;
    }
    if (c == EOF && len == 0) { free(buf); return NULL; }   /* EOF, không có dữ liệu */
    buf[len] = '\0';
    return buf;
}

/* Đọc một số nguyên (bỏ qua khoảng trắng dẫn đầu). Thất bại/EOF -> 0. */
static inline int64_t g_read_int(void) {
    long long v = 0;
    if (scanf("%lld", &v) != 1) return 0;
    return (int64_t)v;
}

/* Đọc một số thực. Thất bại/EOF -> 0.0. */
static inline double g_read_float(void) {
    double v = 0.0;
    if (scanf("%lf", &v) != 1) return 0.0;
    return v;
}

/* Đã hết đầu vào (EOF) chưa? */
static inline bool g_eof(void) { return feof(stdin) != 0; }

/* ---- Sinh số giả ngẫu nhiên & thời gian (tiện cho ví dụ/thuật toán) ---- */
/* Hạt giống phụ thuộc thời gian (kết hợp time + clock để khác nhau mỗi lần chạy). */
static inline uint64_t g_time_seed(void) {
    uint64_t t = (uint64_t)time(NULL);
    uint64_t c = (uint64_t)clock();
    return (t * 0x9E3779B97F4A7C15ULL) ^ (c << 21) ^ (c >> 7) ^ 0xD1B54A32D192ED03ULL;
}

/* Thời gian CPU đã dùng (giây) — đo hiệu năng. */
static inline double g_clock_secs(void) {
    return (double)clock() / (double)CLOCKS_PER_SEC;
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
