// Mảng cỡ TĨNH in trực tiếp được: '{}' bung thành '[v0, v1, ...]', đệ quy cho
// mảng nhiều chiều và cho phần tử struct/enum/chuỗi (giống khi mảng là trường
// của struct). Mảng dài hơn 8 phần tử bị cắt bớt.
struct P { x: int }
enum E { A, B }
fn main() -> int {
    let a: [5]int = [1, 2, 3, 4, 5]
    println("{}", a)
    let m: [2][3]int = [[1, 2, 3], [4, 5, 6]]
    println("{}", m)
    println("{}", [P{x:1}, P{x:2}])
    let es: [2]E = [A, B]
    println("{}", es)
    let ss: [2]str = ["hi", "yo"]
    println("{}", ss)
    let big: [12]int = [1,2,3,4,5,6,7,8,9,10,11,12]
    println("{}", big)
    println("{} rồi {}", a, "hết")
    return 0
}
