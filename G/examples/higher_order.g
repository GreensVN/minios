// higher_order.g - lập trình HÀM với con trỏ hàm (tính năng mới của G)
// Trình diễn: map/filter/fold/any/all + con trỏ hàm trong struct + format().
import std

fn square(x: int) -> int { return x * x }
fn dbl(x: int) -> int { return x * 2 }
fn is_positive(x: int) -> bool { return x > 0 }   // 'is_even' đã có trong std
fn add(a: int, b: int) -> int { return a + b }
fn mx(a: int, b: int) -> int { return max(a, b) }

// Con trỏ hàm là một trường struct: gói "phép biến đổi có tên"
struct Transform {
    name: str,
    apply: fn(int) -> int,
}

fn print_arr(label: str, a: *int, n: int) {
    print("{s}", label)
    for i in 0..n { print("{} ", a[i]) }
    println("")
}

fn main() -> int {
    let src: [8]int = [-2, 5, 0, 9, -4, 6, 3, 8]
    print_arr("nguồn:   ", &src[0], 8)

    // map: bình phương từng phần tử
    let mut mapped: [8]int = [0, 0, 0, 0, 0, 0, 0, 0]
    map_into(&mapped[0], &src[0], 8, square)
    print_arr("bình phương: ", &mapped[0], 8)

    // filter: chỉ giữ số dương
    let mut kept: [8]int = [0, 0, 0, 0, 0, 0, 0, 0]
    let k = filter_into(&kept[0], &src[0], 8, is_positive)
    print_arr("số dương:  ", &kept[0], k)

    // fold: tổng và lớn nhất bằng cùng một khung
    println("tổng = {}, lớn nhất = {}",
            fold(&src[0], 8, 0, add), fold(&src[0], 8, -1000, mx))

    // any / all / count_if / find_first
    println("có số chẵn? {} | tất cả dương? {} | đếm chẵn: {} | vị trí chẵn đầu: {}",
            any(&src[0], 8, is_even), all(&src[0], 8, is_positive),
            count_if(&src[0], 8, is_even), find_first(&src[0], 8, is_even))

    // Bảng phép biến đổi: mảng struct chứa con trỏ hàm
    let pipeline: [2]Transform = [
        Transform { name: "x2", apply: dbl },
        Transform { name: "x^2", apply: square },
    ]
    for t in pipeline {
        let s = format("{s}(7) = {}", t.name, t.apply(7))
        println("{s}", s)
        g_free(s)
    }
    return 0
}
