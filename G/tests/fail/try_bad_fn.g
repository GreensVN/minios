struct R<T,E> { ok: bool, val: T, err: E }
fn g() -> R<int,str> { return R<int,str>{ok:true,val:1,err:""} }
fn f() -> int { let x = g() try
  return x }
fn main() -> int { return f() }
