// list.g - danh sách liên kết đơn (struct tự tham chiếu qua con trỏ)
// Trình diễn: struct đệ quy, cấp phát động, method, duyệt con trỏ.
import std

struct Node {
    val: int,
    next: *Node,
}

struct List {
    head: *Node,
    len: int,
}

impl List {
    // Thêm vào đầu danh sách (O(1))
    fn push_front(self, v: int) {
        let mut n: *Node = g_alloc(Node, 1)
        n.val = v
        n.next = self.head
        self.head = n
        self.len += 1
    }

    // Tổng tất cả phần tử
    fn sum(self) -> i64 {
        let mut s: i64 = 0
        let mut cur: *Node = self.head
        while cur != null {
            s += cur.val as i64
            cur = cur.next
        }
        return s
    }

    // In danh sách theo thứ tự
    fn print_all(self) {
        let mut cur: *Node = self.head
        print("[ ")
        while cur != null {
            print("{} ", cur.val)
            cur = cur.next
        }
        println("]")
    }

    // Giải phóng toàn bộ node
    fn free_all(self) {
        let mut cur: *Node = self.head
        while cur != null {
            let nxt: *Node = cur.next
            g_free(cur)
            cur = nxt
        }
        self.head = null
        self.len = 0
    }
}

fn main() -> int {
    let mut list = List { head: null, len: 0 }

    for i in 1..=8 {
        list.push_front(i * i)
    }

    print("Danh sách ({} phần tử): ", list.len)
    list.print_all()
    println("Tổng = {ld}", list.sum())

    list.free_all()
    println("Sau khi giải phóng: len = {}", list.len)
    return 0
}
