// Kiểm tra struct nâng cao: tự tham chiếu, tham chiếu lẫn nhau, thứ tự định nghĩa,
// struct rỗng, struct lồng nhau theo giá trị.

// Tự tham chiếu (cần forward declaration)
struct TreeNode {
    val: int,
    left: *TreeNode,
    right: *TreeNode,
}

// Tham chiếu lẫn nhau (A <-> B)
struct A { b: *B, tag: int }
struct B { a: *A, tag: int }

// Struct dùng trước khi định nghĩa (cần sắp xếp topo theo giá trị)
struct Outer { inner: Inner, n: int }
struct Inner { v: int }

// Struct rỗng
struct Unit {}

fn tree_sum(node: *TreeNode) -> i64 {
    if node == null { return 0 }
    return (node.val as i64) + tree_sum(node.left) + tree_sum(node.right)
}

fn main() -> int {
    // Cây nhị phân nhỏ:    10
    //                     /  \
    //                    5    15
    let mut root: *TreeNode = g_alloc(TreeNode, 1)
    let mut l: *TreeNode = g_alloc(TreeNode, 1)
    let mut r: *TreeNode = g_alloc(TreeNode, 1)
    root.val = 10; root.left = l; root.right = r
    l.val = 5; l.left = null; l.right = null
    r.val = 15; r.left = null; r.right = null
    println("tree_sum = {ld}", tree_sum(root))
    g_free(root); g_free(l); g_free(r)

    // Tham chiếu lẫn nhau
    let mut x = A { b: null, tag: 1 }
    let mut y = B { a: null, tag: 2 }
    x.b = &y
    y.a = &x
    println("x.tag={}, x.b.tag={}, y.a.tag={}", x.tag, x.b.tag, y.a.tag)

    // Struct lồng theo giá trị (thứ tự định nghĩa ngược)
    let o = Outer { inner: Inner { v: 99 }, n: 1 }
    println("o.inner.v = {}", o.inner.v)

    // Struct rỗng
    let u = Unit {}
    println("unit ok")
    return 0
}
