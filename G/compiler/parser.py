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

    def error(self, msg):
        t = self.cur()
        raise ParseError(f"{msg} (gặp {t.kind} {t.value!r})", t.line, t.col)

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
            if self.is_kw("import"):
                self.advance()
                if self.check("str"):
                    prog.imports.append(self.advance().value)
                else:
                    prog.imports.append(self.expect("id").value)
                self.skip_semis()
            elif self.is_kw("fn") or self.is_kw("comptime") or self.is_kw("extern"):
                prog.items.append(self.parse_fn())
            elif self.is_kw("struct"):
                prog.items.append(self.parse_struct())
            elif self.is_kw("enum"):
                prog.items.append(self.parse_enum())
            elif self.is_kw("impl"):
                prog.items.append(self.parse_impl())
            elif self.is_kw("let") or self.is_kw("const"):
                prog.items.append(self.parse_global())
            else:
                self.error("cần khai báo cấp cao (fn/struct/enum/impl/let/const/import)")
        return prog

    def parse_fn(self, recv=None) -> A.Function:
        t = self.cur()
        is_comptime = bool(self.accept("kw", "comptime"))
        is_extern = bool(self.accept("kw", "extern"))
        self.expect("kw", "fn")
        name = self.expect("id").value
        self.expect("op", "(")
        params = []
        while not self.is_op(")"):
            pname = self.expect("id").value
            # 'self' trong method có thể không cần kiểu
            if pname == "self" and recv and not self.is_op(":"):
                params.append(A.Param("self", A.Type(recv, ptr=1)))
            else:
                self.expect("op", ":")
                params.append(A.Param(pname, self.parse_type()))
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
        return A.Function(name, params, ret, body, is_comptime, is_extern,
                          recv=recv, **self.pos_of(t))

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
        self.expect("kw", "impl")
        struct = self.expect("id").value
        self.expect("op", "{")
        methods = []
        self.skip_semis()
        while not self.is_op("}"):
            methods.append(self.parse_fn(recv=struct))
            self.skip_semis()
        self.expect("op", "}")
        return A.Impl(struct, methods)

    def parse_global(self) -> A.GlobalVar:
        t = self.cur()
        is_const = bool(self.accept("kw", "const"))
        if not is_const:
            self.expect("kw", "let")
        mutable = bool(self.accept("kw", "mut"))
        name = self.expect("id").value
        typ = None
        if self.accept("op", ":"):
            typ = self.parse_type()
        value = None
        if self.accept("op", "="):
            value = self.parse_expr()
        self.skip_semis()
        return A.GlobalVar(name, typ, value, mutable, is_const, **self.pos_of(t))

    # ---------- kiểu ----------
    def parse_type(self) -> A.Type:
        t = self.cur()
        ptr = 0
        while self.accept("op", "*"):
            ptr += 1
        # Mảng (có thể nhiều chiều): [N][M]T | []T | [N]T
        # N là literal nguyên HOẶC tên hằng (vd '[CAP]int') — checker sẽ fold.
        dims = []
        while self.is_op("["):
            self.advance()
            if self.is_op("]"):
                dims.append("dyn")        # []T : con trỏ động
            elif self.check("int"):
                dims.append(int(self.advance().value, 0))
            elif self.check("id"):
                dims.append(self.advance().value)   # tên hằng (string) -> fold sau
            else:
                self.error("cỡ mảng phải là số nguyên hoặc tên hằng")
            self.expect("op", "]")
        name = self.expect("id").value
        ty = A.Type(name, ptr=ptr, **self.pos_of(t))
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
            stmts.append(self.parse_stmt())
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

    def parse_let(self) -> A.Let:
        t = self.cur()
        is_const = bool(self.accept("kw", "const"))
        if not is_const:
            self.expect("kw", "let")
        mutable = bool(self.accept("kw", "mut")) and not is_const
        name = self.expect("id").value
        typ = None
        if self.accept("op", ":"):
            typ = self.parse_type()
        value = None
        if self.accept("op", "="):
            value = self.parse_expr()
        self.skip_semis()
        return A.Let(name, typ, value, mutable, **self.pos_of(t))

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
            end = self.parse_expr()
            step = self.parse_expr() if self.accept("kw", "step") else None
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
                body = [self.parse_stmt()]
            arms.append((pats, guard, body))
            self.accept("op", ",")
            self.skip_semis()
        self.expect("op", "}")
        return A.Match(subject, arms, **self.pos_of(t))

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
        self.expect("kw", "asm")
        volatile = True
        self.expect("op", "{")
        parts = []
        while not self.is_op("}") and not self.check("eof"):
            tk = self.advance()
            if tk.kind == "str":
                parts.append(tk.value)
        self.expect("op", "}")
        return A.Asm("\n".join(parts), volatile)

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
        left = self.parse_unary()
        while self.cur().kind == "op" and self.cur().value in BIN_PREC:
            op = self.cur().value
            prec = BIN_PREC[op]
            if prec < min_prec:
                break
            t = self.advance()
            right = self.parse_binary(prec + 1)
            left = A.Binary(op, left, right, t.line, t.col)
        return left

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
                idx = self.parse_expr()
                self.no_struct_lit = saved
                self.expect("op", "]")
                e = A.Index(e, idx, t.line, t.col)
            elif self.accept("op", "."):
                fld = self.expect("id").value
                e = A.FieldAccess(e, fld, t.line, t.col)
            elif self.is_kw("as"):
                self.advance()
                ty = self.parse_type()
                e = A.Cast(e, ty, t.line, t.col)
            else:
                break
        return e

    def parse_primary(self):
        t = self.cur()
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
        if self.is_kw("sizeof"):
            self.advance()
            self.expect("op", "(")
            # sizeof(*T) / sizeof([N]T): chắc chắn là kiểu
            if self.is_op("*") or self.is_op("["):
                ty = self.parse_type()
                self.expect("op", ")")
                return A.SizeOf(ty, t.line, t.col)
            e = self.parse_expr()
            self.expect("op", ")")
            # tên trần: C cho phép sizeof(name) cho cả kiểu lẫn biến
            if isinstance(e, A.Ident):
                return A.SizeOf(A.Type(e.name, line=e.line, col=e.col), t.line, t.col)
            return A.SizeOfExpr(e, t.line, t.col)
        if self.is_op("["):    # array literal [a, b, c]
            self.advance()
            saved = self.no_struct_lit
            self.no_struct_lit = False
            elems = []
            while not self.is_op("]"):
                elems.append(self.parse_expr())
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
