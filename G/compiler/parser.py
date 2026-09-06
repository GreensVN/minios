"""
G Language - Parser (đệ quy xuống / recursive descent).
Biến chuỗi token thành AST, kèm thông tin vị trí cho chẩn đoán lỗi.
"""

from . import ast_nodes as A
from .lexer import Token


class ParseError(Exception):
    def __init__(self, msg, line, col):
        super().__init__(msg)
        self.msg = msg
        self.line = line
        self.col = col


BIN_PREC = {
    "||": 1, "&&": 2,
    "|": 3, "^": 4, "&": 5,
    "==": 6, "!=": 6,
    "<": 7, ">": 7, "<=": 7, ">=": 7,
    "<<": 8, ">>": 8,
    "+": 9, "-": 9,
    "*": 10, "/": 10, "%": 10,
}

ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}


class Parser:
    def __init__(self, tokens, filename="<input>"):
        self.toks = tokens
        self.pos = 0
        self.filename = filename
        # Khi True, 'Ident {' KHÔNG được coi là struct literal (đang ở header
        # của if/while/for/match — '{' là khối lệnh). Kiểu Rust. Reset trong ( ) [ ].
        self.no_struct_lit = False

    # ---------- tiện ích ----------
    def cur(self) -> Token:
        return self.toks[self.pos]

    def at(self, off=0) -> Token:
        j = self.pos + off
        return self.toks[j] if j < len(self.toks) else self.toks[-1]

    def error(self, msg, show_token=True):
        """Báo lỗi cú pháp tại token hiện tại. 'show_token=False' cho các thông
        báo đã tự đủ nghĩa (kèm gợi ý sửa) — phụ chú '(gặp ...)' khi đó chỉ trỏ
        vào token đứng SAU chỗ sai và gây nhiễu."""
        t = self.cur()
        suffix = f" (gặp {t.kind} {t.value!r})" if show_token else ""
        raise ParseError(f"{msg}{suffix}", t.line, t.col)

    def advance(self) -> Token:
        t = self.toks[self.pos]
        if t.kind != "eof":
            self.pos += 1
        return t

    def check(self, kind, value=None) -> bool:
        t = self.cur()
        if t.kind != kind:
            return False
        if value is not None and t.value != value:
            return False
        return True

    def accept(self, kind, value=None):
        if self.check(kind, value):
            return self.advance()
        return None

    def expect(self, kind, value=None) -> Token:
        if self.check(kind, value):
            return self.advance()
        exp = f"{kind} {value!r}" if value else kind
        self.error(f"cần {exp}")

    def skip_semis(self):
        while self.check("op", ";"):
            self.advance()

    def parse_cond(self):
        """Parse biểu thức điều kiện trong header if/while/for/match: cấm struct
        literal trần để '{' theo sau được hiểu là khối lệnh (giống Rust)."""
        saved = self.no_struct_lit
        self.no_struct_lit = True
        try:
            return self.parse_expr()
        finally:
            self.no_struct_lit = saved

    def is_kw(self, w):
        return self.check("kw", w)

    def is_op(self, o):
        return self.check("op", o)

    def pos_of(self, t):
        return {"line": t.line, "col": t.col}

    # ---------- chương trình ----------
    def parse(self) -> A.Program:
        prog = A.Program()
        while not self.check("eof"):
            self.skip_semis()
            if self.check("eof"):
                break
            # Thuộc tính '@name'/'@name(arg)' đứng trước khai báo (fn/struct/global).
            attrs = self.parse_attrs()
            if self.is_kw("import"):
                if attrs:
                    self.error("'import' không nhận thuộc tính @")
                itok = self.advance()
                # Lưu kèm DÒNG/CỘT: lỗi "không tìm thấy module" trước đây luôn
                # trỏ về dòng 1, tức chỉ vào một import khác khi file có nhiều
                # import.
                if self.check("str"):
                    iname = self.advance().value
                else:
                    iname = self.expect("id").value
                    # 'import mod/a' — đường dẫn có '/' phải đặt trong ngoặc kép;
                    # nếu không, lexer thấy '/' là phép chia và báo "cần khai báo
                    # cấp cao", chẳng gợi ý gì cho người dùng.
                    if self.is_op("/"):
                        parts = [iname]
                        while self.accept("op", "/"):
                            parts.append(self.expect("id").value)
                        guess = "/".join(parts)
                        self.error(
                            f"đường dẫn module có '/' phải đặt trong ngoặc kép: "
                            f'import "{guess}.g"', show_token=False)
                prog.imports.append((iname, itok.line, itok.col))
                self.skip_semis()
            elif self.is_kw("fn") or self.is_kw("comptime"):
                prog.items.append(self._with_attrs(self.parse_fn(), attrs))
            elif self.is_kw("extern"):
                # 'extern fn ...' (hàm libc) | 'extern let/const ...' (ký hiệu
                # linker/assembly — vd 'extern let _kernel_end: u8').
                if self.at(1).kind == "kw" and self.at(1).value in ("let", "const"):
                    prog.items.append(self._with_attrs(self.parse_global(), attrs))
                else:
                    prog.items.append(self._with_attrs(self.parse_fn(), attrs))
            elif self.is_kw("struct"):
                prog.items.append(self._with_attrs(self.parse_struct(), attrs))
            elif self.is_kw("enum"):
                if attrs:
                    self.error("'enum' không nhận thuộc tính @")
                prog.items.append(self.parse_enum())
            elif self.is_kw("impl"):
                if attrs:
                    self.error("'impl' không nhận thuộc tính @ (đặt @ trên method)")
                prog.items.append(self.parse_impl())
            elif self.is_kw("let") or self.is_kw("const"):
                prog.items.append(self._with_attrs(self.parse_global(), attrs))
            else:
                self.error("cần khai báo cấp cao (fn/struct/enum/impl/let/const/import)")
        return prog

    def parse_attrs(self):
        """Đọc danh sách thuộc tính '@name' / '@name(arg, ...)' (kiểu Rust/C) đứng
        trước một khai báo. Cho phép xuống dòng giữa các thuộc tính (ASI chèn ';')."""
        attrs = []
        while self.is_op("@"):
            t = self.advance()
            name = self.expect("id").value
            args = []
            if self.accept("op", "("):
                while not self.is_op(")"):
                    args.append(self.parse_expr())
                    if not self.accept("op", ","):
                        break
                self.expect("op", ")")
            attrs.append(A.Attr(name, args, t.line, t.col))
            self.skip_semis()
        return attrs

    @staticmethod
    def _with_attrs(item, attrs):
        if attrs:
            try:
                item.attrs = attrs
            except Exception:
                pass
        return item

    def parse_fn(self, recv=None) -> A.Function:
        t = self.cur()
        is_comptime = bool(self.accept("kw", "comptime"))
        is_extern = bool(self.accept("kw", "extern"))
        self.expect("kw", "fn")
        name = self.expect("id").value
        # Tham số KIỂU: 'fn max<T>(a: T, b: T) -> T'. Hàm generic được NHÂN BẢN
        # theo từng bộ kiểu cụ thể (monomorphization) trong checker, nên IR và
        # backend không cần biết generic là gì.
        type_params = []
        if self.is_op("<"):
            self.advance()
            while not self.is_op(">"):
                type_params.append(self.expect("id").value)
                if not self.accept("op", ","):
                    break
            if not self.is_op(">"):
                self.error("danh sách tham số kiểu cần đóng bằng '>' "
                           "(vd 'fn f<T>(...)')", show_token=False)
            self.advance()
            if not type_params:
                self.error("'fn " + name + "<>' cần ít nhất một tham số kiểu",
                           show_token=False)
        self.expect("op", "(")
        params = []
        while not self.is_op(")"):
            # 'mut' trước tên tham số (gồm 'mut self') cho phép GHI vào tham số
            # bên trong hàm — nhất quán với 'let'/'let mut'. Không có 'mut' thì
            # tham số là binding bất biến (bản sao của đối số vẫn chỉ đọc).
            pmut = bool(self.accept("kw", "mut"))
            pname = self.expect("id").value
            # 'self' trong method có thể không cần kiểu
            if pname == "self" and recv and not self.is_op(":"):
                params.append(A.Param("self", A.Type(recv, ptr=1), pmut))
            else:
                self.expect("op", ":")
                params.append(A.Param(pname, self.parse_type(), pmut))
            if not self.accept("op", ","):
                break
        self.expect("op", ")")
        ret = A.Type("void")
        if self.accept("op", "->"):
            ret = self.parse_type()
        if is_extern or self.is_op(";"):
            self.skip_semis()
            body = None
        else:
            body = self.parse_block()
        return A.Function(name, params, ret, body, type_params, is_comptime,
                          is_extern, recv=recv, **self.pos_of(t))

    def parse_struct(self) -> A.StructDef:
        t = self.cur()
        self.expect("kw", "struct")
        name = self.expect("id").value
        self.expect("op", "{")
        fields = []
        self.skip_semis()
        while not self.is_op("}"):
            fname = self.expect("id").value
            self.expect("op", ":")
            fields.append(A.Param(fname, self.parse_type()))
            self.accept("op", ",")
            self.skip_semis()
        self.expect("op", "}")
        return A.StructDef(name, fields, **self.pos_of(t))

    def parse_enum(self) -> A.EnumDef:
        t = self.cur()
        self.expect("kw", "enum")
        name = self.expect("id").value
        self.expect("op", "{")
        variants = []
        self.skip_semis()
        while not self.is_op("}"):
            vname = self.expect("id").value
            val = None
            if self.accept("op", "="):
                val = self.parse_expr()
            variants.append((vname, val))
            self.accept("op", ",")
            self.skip_semis()
        self.expect("op", "}")
        return A.EnumDef(name, variants, **self.pos_of(t))

    def parse_impl(self) -> A.Impl:
        t = self.expect("kw", "impl")
        struct = self.expect("id").value
        self.expect("op", "{")
        methods = []
        self.skip_semis()
        while not self.is_op("}"):
            mattrs = self.parse_attrs()
            methods.append(self._with_attrs(self.parse_fn(recv=struct), mattrs))
            self.skip_semis()
        self.expect("op", "}")
        return A.Impl(struct, methods, **self.pos_of(t))

    def parse_global(self) -> A.GlobalVar:
        t = self.cur()
        is_extern = bool(self.accept("kw", "extern"))
        is_const = bool(self.accept("kw", "const"))
        if not is_const:
            self.expect("kw", "let")
        mutable = bool(self.accept("kw", "mut"))
        # Destructuring chỉ dùng được trong THÂN HÀM (nó khử đường thành nhiều
        # câu lệnh, mà cấp cao nhất chỉ nhận khai báo). Báo rõ thay vì để lỗi
        # "cần khai báo cấp cao (gặp op '{')".
        if (self.cur().kind == "id" and self.at(1).value == "{"
                and self._looks_like_destructure()):
            self.error(
                f"'let {self.cur().value}{{...}}' (destructuring) chỉ dùng được "
                f"bên trong hàm — ở cấp cao nhất hãy khai báo từng global một",
                show_token=False)
        name = self.expect("id").value
        typ = None
        if self.accept("op", ":"):
            typ = self.parse_type()
        value = None
        if self.accept("op", "="):
            value = self.parse_expr()
        self.skip_semis()
        if is_extern:
            # Ký hiệu ngoài: chỉ khai báo (kiểu bắt buộc, không giá trị khởi tạo).
            if typ is None:
                self.error("'extern let/const' cần chú thích kiểu "
                           "(vd 'extern let _kernel_end: u8')")
            if value is not None:
                self.error("'extern let/const' không được gán giá trị "
                           "(ký hiệu được định nghĩa ở nơi khác)")
        return A.GlobalVar(name, typ, value, mutable, is_const,
                           is_extern=is_extern, **self.pos_of(t))

    # ---------- kiểu ----------
    def parse_type(self) -> A.Type:
        t = self.cur()
        ptr = 0
        while self.accept("op", "*"):
            ptr += 1
        # Mảng (có thể nhiều chiều): [N][M]T | []T | [N]T | [N+1]T
        # Mỗi chiều: rỗng (=> []T động), hoặc một BIỂU THỨC HẰNG (literal / tên
        # hằng / phép toán giữa các hằng, vd '[CAP*2+1]') — checker sẽ fold.
        dims = []
        while self.is_op("["):
            self.advance()
            if self.is_op("]"):
                dims.append("dyn")        # []T : con trỏ động
            else:
                saved = self.no_struct_lit
                self.no_struct_lit = True
                szexpr = self.parse_expr()
                self.no_struct_lit = saved
                dims.append(int(szexpr.value, 0)
                            if isinstance(szexpr, A.IntLit) else szexpr)
            self.expect("op", "]")
        # Con trỏ trên PHẦN TỬ: '[N]*T' = mảng các con trỏ (khác '*[N]T').
        elem_ptr = 0
        while self.accept("op", "*"):
            elem_ptr += 1
        # Kiểu con trỏ hàm: 'fn(P1, P2, ...) -> R' (R tuỳ chọn; mặc định void).
        if self.is_kw("fn"):
            self.advance()
            self.expect("op", "(")
            fparams = []
            while not self.is_op(")"):
                fparams.append(self.parse_type())
                if not self.accept("op", ","):
                    break
            self.expect("op", ")")
            fret = self.parse_type() if self.accept("op", "->") else None
            ty = A.Type("fn", ptr=ptr, elem_ptr=elem_ptr, is_fn=True,
                        fn_params=fparams, fn_ret=fret, **self.pos_of(t))
        else:
            # 'slice<T>' / 'mut slice<T>' — con trỏ béo (ptr + len). Giữ '[]T'
            # nguyên nghĩa cũ (con trỏ trần) để mã hiện có không đổi hành vi.
            smut = False
            if self.is_kw("mut") and self.at(1).kind == "id" \
                    and self.at(1).value == "slice":
                self.advance()
                smut = True
            if self.check("id", "slice") and self.at(1).value == "<":
                self.advance()                      # 'slice'
                self.expect("op", "<")
                inner = self.parse_type()
                if not self.is_op(">"):
                    self.error("kiểu slice cần đóng bằng '>' (vd 'slice<int>')",
                               show_token=False)
                self.advance()                      # '>'
                ty = A.Type("slice", ptr=ptr, elem_ptr=elem_ptr,
                            slice_elem=inner, slice_mut=smut, **self.pos_of(t))
                if dims:
                    ty.dims = dims
                    ty.array = dims[0]
                return ty
            if smut:
                self.error("'mut' ở vị trí kiểu chỉ dùng với slice "
                           "(vd 'mut slice<int>')", show_token=False)
            name = self.expect("id").value
            targs = None
            if self.is_op("<") and self._looks_like_type_args():
                self.advance()
                targs = []
                while not self.is_op(">"):
                    targs.append(self.parse_type())
                    if not self.accept("op", ","):
                        break
                if not self.is_op(">"):
                    self.error(f"đối số kiểu của '{name}' cần đóng bằng '>'",
                               show_token=False)
                self.advance()
            ty = A.Type(name, type_args=targs, ptr=ptr, elem_ptr=elem_ptr,
                        **self.pos_of(t))
        if dims:
            ty.dims = dims
            ty.array = dims[0]            # chiều ngoài cùng (giữ tương thích)
        return ty

    # ---------- khối & câu lệnh ----------
    def parse_block(self) -> list:
        self.expect("op", "{")
        stmts = []
        self.skip_semis()
        while not self.is_op("}") and not self.check("eof"):
            st = self.parse_stmt()
            # A.Multi (destructuring) làm PHẲNG ngay vào block cha: các pass sau
            # (checker/codegen/phân tích luồng) không cần biết tới nó.
            if isinstance(st, A.Multi):
                stmts.extend(st.stmts)
            else:
                stmts.append(st)
            self.skip_semis()
        self.expect("op", "}")
        return stmts

    def parse_stmt(self):
        t = self.cur()
        if self.is_kw("let") or self.is_kw("const"):
            return self.parse_let()
        if self.is_kw("return"):
            self.advance()
            val = None
            if not self.is_op(";") and not self.is_op("}"):
                val = self.parse_expr()
            self.skip_semis()
            return A.Return(val, **self.pos_of(t))
        if self.is_kw("if"):
            return self.parse_if()
        if self.is_kw("while"):
            self.advance()
            cond = self.parse_cond()
            body = self.parse_block()
            return A.While(cond, body)
        if self.is_kw("loop"):
            self.advance()
            return A.Loop(self.parse_block())
        if self.is_kw("for"):
            return self.parse_for()
        if self.is_kw("match"):
            return self.parse_match()
        if self.is_kw("defer"):
            self.advance()
            return A.Defer(self.parse_stmt())
        if self.is_kw("asm"):
            return self.parse_asm()
        if self.is_kw("break"):
            tk = self.advance(); self.skip_semis()
            return A.Break(**self.pos_of(tk))
        if self.is_kw("continue"):
            tk = self.advance(); self.skip_semis()
            return A.Continue(**self.pos_of(tk))
        if self.is_op("{"):
            # khối lệnh trần { ... } — tạo scope riêng (block-scoped defer)
            return A.Block(self.parse_block(), **self.pos_of(t))
        # biểu thức hoặc gán
        expr = self.parse_expr()
        if self.cur().kind == "op" and self.cur().value in ASSIGN_OPS:
            op = self.advance().value
            value = self.parse_expr()
            self.skip_semis()
            return A.Assign(expr, op, value, **self.pos_of(t))
        self.skip_semis()
        return A.ExprStmt(expr)

    def parse_let(self):
        t = self.cur()
        is_const = bool(self.accept("kw", "const"))
        if not is_const:
            self.expect("kw", "let")
        mutable = bool(self.accept("kw", "mut")) and not is_const
        # ----- destructuring struct: 'let P{x, y} = v' / 'let P{x: a} = v' -----
        if (self.cur().kind == "id" and self.at(1).value == "{"
                and self._looks_like_destructure()):
            return self._parse_destructure(t, mutable, is_const)
        name = self.expect("id").value
        typ = None
        if self.accept("op", ":"):
            typ = self.parse_type()
        value = None
        if self.accept("op", "="):
            value = self.parse_expr()
        self.skip_semis()
        return A.Let(name, typ, value, mutable, is_const=is_const, **self.pos_of(t))

    def _looks_like_destructure(self):
        """Phân biệt 'let P{x, y} = v' (destructuring) với 'let s = P{x: 1}'.
        Ở vị trí NGAY SAU 'let', một 'Tên {' luôn là pattern: dạng khởi tạo phải
        có '=' trước struct literal."""
        i = 2                       # bỏ qua 'Tên' '{'
        if self.at(i).value == "}":
            return True
        return self.at(i).kind == "id" and self.at(i + 1).value in (",", "}", ":")

    def _parse_destructure(self, t, mutable, is_const):
        """'let P{x, y} = v' -> một Let ẩn giữ v, rồi mỗi trường một Let.
        Giá trị được vật hoá đúng MỘT lần (v có thể có tác dụng phụ)."""
        sname = self.expect("id").value
        self.expect("op", "{")
        binds = []                  # (tên_trường, tên_biến)
        self.skip_semis()
        while not self.is_op("}"):
            fname = self.expect("id").value
            vname = fname
            if self.accept("op", ":"):        # 'x: tên_khác'
                vname = self.expect("id").value
            binds.append((fname, vname))
            self.accept("op", ",")
            self.skip_semis()
        self.expect("op", "}")
        if not binds:
            self.error(f"'let {sname}{{}}' không rút trích trường nào — bỏ câu "
                       f"lệnh này, hoặc liệt kê các trường cần lấy",
                       show_token=False)
        if not self.accept("op", "="):
            self.error(f"'let {sname}{{...}}' cần '=' và một giá trị để rút trích")
        value = self.parse_expr()
        self.skip_semis()
        pos = self.pos_of(t)
        tmp = f"__gds{t.line}_{t.col}"
        stmts = [A.Let(tmp, None, value, False, **pos)]
        stmts[0].destructure_of = sname
        for fname, vname in binds:
            fa = A.FieldAccess(A.Ident(tmp, line=t.line, col=t.col), fname,
                               t.line, t.col)
            stmts.append(A.Let(vname, None, fa, mutable, is_const=is_const, **pos))
        return A.Multi(stmts, **pos)

    def parse_if(self) -> A.If:
        self.expect("kw", "if")
        cond = self.parse_cond()
        then = self.parse_block()
        els = None
        if self.accept("kw", "else"):
            if self.is_kw("if"):
                els = [self.parse_if()]
            else:
                els = self.parse_block()
        return A.If(cond, then, els)

    def parse_for(self):
        t = self.cur()
        self.expect("kw", "for")
        mutable = bool(self.accept("kw", "mut"))
        var = self.expect("id").value
        self.expect("kw", "in")
        saved = self.no_struct_lit
        self.no_struct_lit = True
        first = self.parse_expr()
        # for i in a..b | a..=b [step N]   (vòng lặp theo khoảng)
        inclusive = self.accept("op", "..=")
        if inclusive or self.accept("op", ".."):
            if mutable:
                raise ParseError("biến đếm của 'for i in a..b' luôn bất biến (là biến "
                                 "đếm của vòng lặp) — bỏ 'mut'; cần sửa thì 'let mut "
                                 "j = i' trong thân vòng lặp", t.line, t.col)
            end = self.parse_expr()
            step = self.parse_expr() if self.accept("id", "step") else None
            self.no_struct_lit = saved
            body = self.parse_block()
            return A.For(var, first, end, body, bool(inclusive), step,
                         **self.pos_of(t))
        # for [mut] x in <iterable> { }   (duyệt mảng tĩnh hoặc chuỗi)
        self.no_struct_lit = saved
        body = self.parse_block()
        return A.ForEach(var, first, body, mutable, **self.pos_of(t))

    def parse_match(self) -> A.Match:
        t = self.cur()
        self.expect("kw", "match")
        subject = self.parse_cond()
        self.expect("op", "{")
        arms = []
        self.skip_semis()
        while not self.is_op("}"):
            if self.accept("id", "_"):
                pats = None
            else:
                # parse_binary(4): dừng trước '|' (prec 3) để '|' làm dấu phân tách pattern
                pats = [self.parse_match_pattern()]
                while self.accept("op", "|"):
                    pats.append(self.parse_match_pattern())
            # Guard tuỳ chọn (kiểu Rust): 'pattern if <điều kiện> =>'. Cấm struct
            # literal trần trong điều kiện để '{' sau đó là thân nhánh.
            guard = None
            if self.accept("kw", "if"):
                guard = self.parse_cond()
            self.expect("op", "=>")
            if self.is_op("{"):
                body = self.parse_block()
            else:
                one = self.parse_stmt()
                body = one.stmts if isinstance(one, A.Multi) else [one]
            arms.append((pats, guard, body))
            self.accept("op", ",")
            self.skip_semis()
        self.expect("op", "}")
        return A.Match(subject, arms, **self.pos_of(t))

    def _parse_value_block(self, what):
        """Thân của một nhánh if/match Ở VỊ TRÍ BIỂU THỨC: '{ expr }' (đúng MỘT
        biểu thức, không phải câu lệnh). Chuỗi câu lệnh cần 'if' dạng lệnh."""
        self.expect("op", "{")
        self.skip_semis()
        if self.is_op("}"):
            self.error(f"nhánh {what} ở vị trí biểu thức phải cho một GIÁ TRỊ — "
                       f"khối '{{ }}' rỗng không có giá trị")
        saved = self.no_struct_lit
        self.no_struct_lit = False
        e = self.parse_expr()
        self.no_struct_lit = saved
        self.skip_semis()
        if not self.is_op("}"):
            self.error(f"nhánh {what} ở vị trí biểu thức chỉ được chứa MỘT biểu "
                       f"thức (không phải câu lệnh) — dùng '{what}' dạng câu lệnh "
                       f"nếu cần nhiều lệnh")
        self.expect("op", "}")
        return e

    def parse_if_expr(self) -> A.IfExpr:
        """'let v = if c { a } else { b }' — nhánh 'else' BẮT BUỘC (biểu thức
        luôn phải có giá trị); hạ về toán tử ba ngôi C."""
        t = self.cur()
        self.expect("kw", "if")
        cond = self.parse_cond()
        then = self._parse_value_block("if")
        if not self.accept("kw", "else"):
            self.error("'if' ở vị trí biểu thức bắt buộc có 'else' (mọi nhánh "
                       "phải cho một giá trị)")
        if self.is_kw("if"):
            els = self.parse_if_expr()
        else:
            els = self._parse_value_block("else")
        # Hạ thẳng về toán tử ba ngôi: cùng ngữ nghĩa (đánh giá lười một nhánh),
        # và tái dùng toàn bộ kiểm kiểu/sinh mã đã có của '?:'.
        return A.Ternary(cond, then, els, t.line, t.col)

    def parse_match_expr(self) -> A.MatchExpr:
        """'let v = match x { p => val, ... }' — mỗi nhánh cho một GIÁ TRỊ."""
        t = self.cur()
        self.expect("kw", "match")
        subject = self.parse_cond()
        self.expect("op", "{")
        arms = []
        self.skip_semis()
        while not self.is_op("}"):
            if self.accept("id", "_"):
                pats = None
            else:
                pats = [self.parse_match_pattern()]
                while self.accept("op", "|"):
                    pats.append(self.parse_match_pattern())
            guard = None
            if self.accept("kw", "if"):
                guard = self.parse_cond()
            self.expect("op", "=>")
            if self.is_op("{"):
                value = self._parse_value_block("match")
            else:
                saved = self.no_struct_lit
                self.no_struct_lit = False
                value = self.parse_expr()
                self.no_struct_lit = saved
            arms.append((pats, guard, value))
            self.accept("op", ",")
            self.skip_semis()
        self.expect("op", "}")
        if not arms:
            self.error("'match' ở vị trí biểu thức cần ít nhất một nhánh")
        return A.MatchExpr(subject, arms, t.line, t.col)

    def parse_match_pattern(self):
        """Một pattern trong match: biểu thức đơn, hoặc khoảng lo..hi / lo..=hi."""
        lo = self.parse_binary(4)
        t = self.cur()
        inclusive = self.accept("op", "..=")
        if inclusive or self.accept("op", ".."):
            hi = self.parse_binary(4)
            return A.RangePat(lo, hi, bool(inclusive), t.line, t.col)
        return lo

    def parse_asm(self) -> A.Asm:
        """asm cơ bản:    asm { "nop" "nop" }
        asm mở rộng (GCC, có toán hạng — đọc/ghi thanh ghi, MSR, control reg...):
            asm {
                "mov %%cr3, %0"
                : "=r"(out)          // outputs:  "ràng buộc"(ô_nhớ)
                : "r"(in)            // inputs:   "ràng buộc"(biểu_thức)
                : "memory"           // clobbers: danh sách chuỗi
            }
        Bên trong '{ }', ASI chèn ';' sau mỗi chuỗi/')' trên dòng mới — bỏ qua."""
        t = self.cur()
        self.expect("kw", "asm")
        self.expect("op", "{")
        parts = []
        self.skip_semis()
        while self.check("str"):              # template: tới ':' hoặc '}'
            parts.append(self.advance().value)
            self.skip_semis()
        outputs, inputs, clobbers = [], [], []
        extended = False
        section = 0                           # 0=outputs, 1=inputs, 2=clobbers
        while self.is_op(":"):
            self.advance()
            extended = True
            self.skip_semis()
            while self.check("str"):
                s = self.advance().value
                if section < 2:
                    self.expect("op", "(")
                    ex = self.parse_expr()
                    self.expect("op", ")")
                    (outputs if section == 0 else inputs).append((s, ex))
                else:
                    clobbers.append(s)
                self.skip_semis()
                self.accept("op", ",")
                self.skip_semis()
            section += 1
            if section >= 3:
                break
        self.expect("op", "}")
        return A.Asm("\n".join(parts), outputs, inputs, clobbers,
                     volatile=True, extended=extended, **self.pos_of(t))

    # ---------- biểu thức ----------
    def parse_expr(self):
        return self.parse_ternary()

    def parse_ternary(self):
        cond = self.parse_binary(0)
        if self.is_op("?"):
            t = self.advance()
            then = self.parse_expr()
            self.expect("op", ":")
            els = self.parse_ternary()
            return A.Ternary(cond, then, els, t.line, t.col)
        return cond

    def parse_binary(self, min_prec):
        left = self.parse_cast()
        while self.cur().kind == "op" and self.cur().value in BIN_PREC:
            op = self.cur().value
            prec = BIN_PREC[op]
            if prec < min_prec:
                break
            t = self.advance()
            right = self.parse_binary(prec + 1)
            left = A.Binary(op, left, right, t.line, t.col)
        return left

    def parse_cast(self):
        """Phép ép kiểu 'expr as T' — ràng buộc LỎNG hơn tiền tố (-, *, &, !, ~)
        nhưng CHẶT hơn toán tử hai ngôi, đúng như Rust. Nhờ vậy '&x as *T' nghĩa
        là '(&x) as *T' và '-x as int' nghĩa là '(-x) as int' (không còn bắt địa
        chỉ/đảo dấu của chính phép ép). Cho phép chuỗi ép: 'x as int as i64'.
        (Muốn dùng hậu tố sau ép — như '.field' — cần ngoặc: '(x as *T).f'.)"""
        e = self.parse_unary()
        while self.is_kw("as"):
            t = self.advance()
            ty = self.parse_type()
            e = A.Cast(e, ty, t.line, t.col)
        return e

    def parse_unary(self):
        if self.cur().kind == "op" and self.cur().value in ("-", "!", "*", "&", "~"):
            t = self.advance()
            operand = self.parse_unary()
            return A.Unary(t.value, operand, t.line, t.col)
        return self.parse_postfix()

    def parse_postfix(self):
        e = self.parse_primary()
        while True:
            t = self.cur()
            if self.accept("op", "("):
                saved = self.no_struct_lit
                self.no_struct_lit = False    # trong ( ) struct literal lại hợp lệ
                args = []
                while not self.is_op(")"):
                    args.append(self.parse_expr())
                    if not self.accept("op", ","):
                        break
                self.no_struct_lit = saved
                self.expect("op", ")")
                e = A.Call(e, args, t.line, t.col)
            elif self.accept("op", "["):
                saved = self.no_struct_lit
                self.no_struct_lit = False
                # 's[a..b]' / 's[a..=b]' — lát cắt chuỗi (kiểu Rust). Cận có thể
                # khuyết: 's[..n]', 's[n..]', 's[..]'.
                if self.is_op("..") or self.is_op("..="):
                    inc = bool(self.accept("op", "..="))
                    if not inc:
                        self.advance()          # '..'
                    lo = None
                    hi = None if self.is_op("]") else self.parse_expr()
                    self.no_struct_lit = saved
                    self.expect("op", "]")
                    e = A.Slice(e, lo, hi, inc, t.line, t.col)
                    continue
                idx = self.parse_expr()
                if self.is_op("..") or self.is_op("..="):
                    inc = bool(self.accept("op", "..="))
                    if not inc:
                        self.advance()
                    hi = None if self.is_op("]") else self.parse_expr()
                    self.no_struct_lit = saved
                    self.expect("op", "]")
                    e = A.Slice(e, idx, hi, inc, t.line, t.col)
                    continue
                self.no_struct_lit = saved
                self.expect("op", "]")
                e = A.Index(e, idx, t.line, t.col)
            elif self.accept("op", "."):
                fld = self.expect("id").value
                e = A.FieldAccess(e, fld, t.line, t.col)
            elif (self.is_op("<") and isinstance(e, A.Ident)
                  and self._looks_like_call_type_args()):
                # 'f<int>(x)' — đối số kiểu TƯỜNG MINH tại nơi gọi. Chỉ nhận khi
                # sau '>' là '(' , nếu không 'a < b' sẽ bị hiểu nhầm.
                self.advance()
                targs = []
                while not self.is_op(">"):
                    targs.append(self.parse_type())
                    if not self.accept("op", ","):
                        break
                self.expect("op", ">")
                self.expect("op", "(")
                saved = self.no_struct_lit
                self.no_struct_lit = False
                args = []
                while not self.is_op(")"):
                    args.append(self.parse_expr())
                    if not self.accept("op", ","):
                        break
                self.no_struct_lit = saved
                self.expect("op", ")")
                e = A.Call(e, args, t.line, t.col)
                e.type_args = targs
            elif self.is_op("::"):
                # 'Type::item' — đường dẫn kiểu Rust, đồng nghĩa 'Type.item'
                # (biến thể enum hoặc method tĩnh). Trước đây '::' được lexer
                # nhận nhưng không parser nào dùng, nên 'Color::Red' báo "cần
                # biểu thức" rất khó hiểu. Chỉ hợp lệ sau một TÊN trần.
                if not isinstance(e, A.Ident):
                    self.error("'::' chỉ dùng sau tên một kiểu "
                               "(vd 'Color::Red', 'Counter::new()') — "
                               "truy cập trường/method của một giá trị dùng '.'")
                self.advance()
                fld = self.expect("id").value
                e = A.FieldAccess(e, fld, t.line, t.col)
                e.via_path = True
            else:
                break
        return e

    def parse_primary(self):
        t = self.cur()
        if self.is_kw("if"):
            return self.parse_if_expr()
        if self.is_kw("match"):
            return self.parse_match_expr()
        if t.kind == "int":
            self.advance(); return A.IntLit(t.value, t.line, t.col)
        if t.kind == "float":
            self.advance(); return A.FloatLit(t.value, t.line, t.col)
        if t.kind == "str":
            self.advance(); return A.StrLit(t.value, t.line, t.col)
        if t.kind == "char":
            self.advance(); return A.CharLit(t.value, t.line, t.col)
        if self.is_kw("true"):
            self.advance(); return A.BoolLit(True, t.line, t.col)
        if self.is_kw("false"):
            self.advance(); return A.BoolLit(False, t.line, t.col)
        if self.is_kw("null"):
            self.advance(); return A.NullLit(t.line, t.col)
        if self.is_kw("sizeof") or self.is_kw("alignof"):
            is_align = self.cur().value == "alignof"
            self.advance()
            self.expect("op", "(")
            # sizeof/alignof(*T) / ([N]T): chắc chắn là kiểu
            if self.is_op("*") or self.is_op("["):
                ty = self.parse_type()
                self.expect("op", ")")
                return A.SizeOf(ty, t.line, t.col, align=is_align)
            e = self.parse_expr()
            self.expect("op", ")")
            # tên trần: cho cả kiểu lẫn biến (C: sizeof(name) / _Alignof(Type))
            if isinstance(e, A.Ident):
                return A.SizeOf(A.Type(e.name, line=e.line, col=e.col),
                                t.line, t.col, align=is_align)
            # alignof chỉ áp dụng cho KIỂU (C11 _Alignof) — không nhận biểu thức tuỳ ý
            if is_align:
                self.error("alignof cần một tên kiểu (vd 'alignof(i64)', "
                           "'alignof(*Node)', 'alignof([4]int)')")
            return A.SizeOfExpr(e, t.line, t.col)
        if self.is_op("["):    # array literal [a, b, c]
            self.advance()
            saved = self.no_struct_lit
            self.no_struct_lit = False
            elems = []
            while not self.is_op("]"):
                elems.append(self.parse_expr())
                # '[v; N]' — mảng N phần tử cùng giá trị (kiểu Rust). N phải là
                # hằng số nguyên (kích thước mảng biết lúc biên dịch).
                if len(elems) == 1 and self.is_op(";"):
                    self.advance()
                    count = self.parse_expr()
                    self.no_struct_lit = saved
                    self.expect("op", "]")
                    return A.ArrayLit(elems, t.line, t.col, repeat=count)
                if not self.accept("op", ","):
                    break
            self.no_struct_lit = saved
            self.expect("op", "]")
            return A.ArrayLit(elems, t.line, t.col)
        if self.is_op("("):
            self.advance()
            saved = self.no_struct_lit
            self.no_struct_lit = False
            e = self.parse_expr()
            self.no_struct_lit = saved
            self.expect("op", ")")
            return e
        if t.kind == "id":
            self.advance()
            if (not self.no_struct_lit and self.is_op("{")
                    and self._looks_like_struct_lit()):
                return self.parse_struct_lit(t.value, t)
            return A.Ident(t.value, line=t.line, col=t.col)
        self.error("cần biểu thức")

    def _looks_like_call_type_args(self):
        """'f<int>(' — đối số kiểu ở nơi GỌI. Yêu cầu có '(' ngay sau '>' để
        không nuốt nhầm 'a < b' (so sánh) thành đối số kiểu."""
        i = 1
        depth = 0
        while i < 24:
            tk = self.at(i)
            if tk.kind == "eof":
                return False
            v = tk.value
            if v == "<":
                depth += 1
            elif v == ">":
                if depth == 0:
                    return self.at(i + 1).value == "("
                depth -= 1
            elif tk.kind == "id" or v in ("*", ",", "[", "]") or tk.kind == "int":
                pass
            else:
                return False
            i += 1
        return False

    def _looks_like_type_args(self):
        """Phân biệt 'Foo<int>' (đối số kiểu) với 'a < b' (so sánh).

        Chỉ coi là đối số kiểu khi ngay sau '<' là một TÊN/kiểu rồi tới ',' hoặc
        '>'. Ở VỊ TRÍ KIỂU thì '<' không thể là so sánh, nhưng hàm này cũng được
        dùng từ vị trí biểu thức nên phải thận trọng."""
        i = 1                                   # bỏ qua '<'
        depth = 0
        while i < 24:
            t = self.at(i)
            if t.kind == "eof":
                return False
            v = t.value
            if v == "<":
                depth += 1
            elif v == ">":
                if depth == 0:
                    return True
                depth -= 1
            elif t.kind == "id" or v in ("*", ",", "[", "]") or t.kind == "int":
                pass
            else:
                return False
            i += 1
        return False

    def _looks_like_struct_lit(self):
        # 'Name {}' (rỗng) hoặc 'Name { field: ...}' — phân biệt với khối lệnh.
        if self.at(0).value != "{":
            return False
        if self.at(1).value == "}":          # struct literal rỗng
            return True
        return self.at(1).kind == "id" and self.at(2).value == ":"

    def parse_struct_lit(self, name, t):
        self.expect("op", "{")
        fields = []
        self.skip_semis()
        while not self.is_op("}"):
            fname = self.expect("id").value
            self.expect("op", ":")
            val = self.parse_expr()
            fields.append((fname, val))
            self.accept("op", ",")
            self.skip_semis()
        self.expect("op", "}")
        return A.StructLit(name, fields, t.line, t.col)
