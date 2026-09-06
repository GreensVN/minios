struct R<T,E> { ok: bool, val: T, err: E }
fn g() -> R<int,str> { return R<int,str>{ok:true,val:1,err:""} }
fn f() -> R<int,int> { let x = g() try
  return R<int,int>{ok:true,val:x,err:0} }
fn main() -> int { return 0 }
