# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**G** is a compiled systems programming language. The compiler is written in Python and
**transpiles G source to C**, then invokes `gcc`/`clang` to produce a native executable.
Frontend ideas come from Rust/Zig (`let`/`mut`, `match`, `defer`, `comptime`, `loop`,
`impl`); the backend is C. All source comments, documentation, and **compiler diagnostics
are in Vietnamese** — match that language when editing user-facing strings.

Requires `python3` and `gcc` or `clang`. There are no third-party Python dependencies.

> Note: the git repository root is `/workspaces/minios`, but this project lives in the `G/`
> subdirectory. All commands below assume you are `cd`'d into `G/`.

## Commands

```bash
./gc <file>.g --run         # compile + run
./gc <file>.g -o <name>     # produce executable <name>
./gc <file>.g --emit-c      # print generated C (no compile) — primary debugging tool
./gc <file>.g --check       # type-check only, no codegen
./gc <file>.g --tokens      # dump lexer token stream
./gc <file>.g --ast         # dump parser AST
./gc <file>.g --keep-c      # keep the intermediate .c next to the binary
./gc <file>.g --debug       # show full Python traceback on internal compiler error
./gc <file>.g --cc clang -O3   # pick C compiler / optimization level

# OS / freestanding (v0.6.0) — see "OS development" section below
./gc kernel.g --freestanding -c -o kernel.o   # compile to a libc-free object (kernel/firmware)
./gc kernel.g --freestanding -S               # emit freestanding assembly
# unknown flags pass through to the C compiler: `./gc k.g --freestanding -c -m32 -mno-red-zone`

./tests/run_tests.sh        # run the whole suite
./tests/run_tests.sh --bless   # regenerate expected outputs / fail-test message snapshots
```

There is no single-test filter in `run_tests.sh`. To iterate on one program, invoke `gc`
directly: `./gc tests/cases/<name>.g --run` for a passing case, or
`./gc tests/fail/<name>.g --check` for a should-fail case.

When an internal compiler crash happens, `gc` swallows the traceback by default and prints a
generic message; **always re-run with `--debug`** to see where it actually broke.

## Test harness semantics (`tests/run_tests.sh`)

Two kinds of tests, both keyed by basename:

- **Output tests** — every `examples/*.g` and `tests/cases/*.g`. Compiled, run, and their
  combined **stdout+stderr** compared against `tests/expected/<name>.txt`. Optional stdin
  comes from `tests/input/<name>.txt` (else `/dev/null`, so programs reading input must
  terminate on EOF).
- **Fail tests** — every `tests/fail/<name>.g`. Must *fail* `--check`; the diagnostic must
  **contain** the (ANSI-stripped) message snapshot in `tests/fail/<name>.txt`. These lock in
  diagnostics against regression. The first line is written by `--bless`; any extra lines
  (hand-added, preserved by `--bless`) must also appear in the output — used e.g. to assert
  the multi-error summary `gc: 4 lỗi`.
- **Freestanding tests** — every `tests/freestanding/*.g` and `examples/kernel/*.g`. Compiled
  with `--freestanding -c` to a `.o` and checked for **exit 0** (NOT run — they may contain
  privileged instructions like `hlt`/`cli`/`outb`). Locks in libc-free compilation of the OS
  intrinsics, `@attributes`, `extern let`, and extended asm. The `examples/*.g` glob is
  non-recursive, so `examples/kernel/*.g` is only reached by this section, never run.

Because test output includes stderr, the runtime disables ANSI color when not writing to a
TTY (`g_tcolor` / `isatty` in `runtime/g_runtime.h`) so captured output stays clean.

Adding a feature → add an example/case + `--bless`. Adding a diagnostic → add a
`tests/fail/<name>.g` + `--bless` (which snapshots the message).

## Compilation pipeline

```
source.g ─► Lexer (+ASI) ─► Parser (AST) ─► load_program (merge imports)
         ─► Checker (type inference, mutates AST) ─► Codegen (emit C) ─► gcc/clang
```

Entry point `gc` → `compiler/driver.py:main`. The driver orchestrates everything and is the
only place that knows about files, modules, and the C compiler subprocess.

| Stage | File | Responsibility |
|-------|------|----------------|
| Lexer | `compiler/lexer.py` | Tokens + **automatic semicolon insertion** (Go-style, in `_auto_semi`, suppressed inside `()`/`[]`). Normalizes `0x`/`0b`/`0o` literals to decimal; rejects C-octal `010`. |
| AST   | `compiler/ast_nodes.py` | `@dataclass` node definitions. `A.Type` is the *syntactic* type; `T.GType` (in `types.py`) is the *resolved* type. |
| Parser | `compiler/parser.py` | Recursive descent + Pratt `parse_binary`. The `no_struct_lit` flag disambiguates `Ident {` as struct-literal vs. block in `if/while/for/match` headers (reset inside `()`/`[]`). |
| Types | `compiler/types.py` | `GType`, primitive table, G→C name map, `printf_spec`, numeric promotion. |
| Checker | `compiler/checker.py` | Semantic analysis + type inference. **Mutates the AST** (see below). |
| Codegen | `compiler/codegen.py` | AST → C. Relies entirely on checker-attached attributes. |
| Driver | `compiler/driver.py` | Module loading, diagnostics rendering, `cc` invocation. |
| Runtime | `runtime/g_runtime.h` | C header auto-included into every program: `g_alloc`/`g_panic`/`g_str_*`/`g_read_*`/test framework/etc. |
| Stdlib | `lib/std.g` | Standard library **written in G itself**, bridging to libc/libm/runtime via `extern fn`. Loaded by `import std`. |

### The checker mutates the AST — codegen depends on it

Codegen is a near-mechanical translation; almost all intelligence lives in the checker, which
**annotates nodes in place**. Codegen reads these and will produce wrong/invalid C if they're
missing. Key annotations:

- `node.gtype` on every expression (the inferred `GType`) — drives print-format selection,
  auto-deref, `==` string lowering, shift-width handling.
- `Ident.c_name` / `Let.c_name` / `For.c_name` — unique C names that implement **shadowing**
  (C forbids redeclaration in a scope; the checker renames via `declare`).
- `Call.is_method` / `.recv` / `.method` / `.struct` / `.recv_is_ptr` — method-call resolution;
  `Call.is_static_method` for `Type.fn(args)` (no `self`). `Function.is_static` is set on
  `impl` methods in `collect_funcs`. `impl` targets may be structs **or enums**.
- `FieldAccess.enum_variant = (Enum, Variant)` for qualified `Color.Red`; `Ident.is_enum_variant`
  for bare variants (both are constants — `_is_addressable` must not take `&` of them).
- `Match.subject_type` / `.has_default` / `.bindings` / `.deref_subject` (for `match self` in
  an enum method, where `self: *Enum`) — match lowering.
- `Binary.widen_i64` — constant integer expression whose folded value exceeds 32 bits; codegen
  casts the left operand so C computes in 64-bit.
- `Param.c_name` — parameters go through `declare()` too, so a parameter named like a libc
  function or a global gets a safe/unique C name.
- `For.var_type`, `ForEach.elem_type` / `.iter_kind`, `FieldAccess.auto_deref`.
- `prog.enum_tables` — the enum value table, shared checker→codegen (avoids a back-dependency).

**Consequence: never run codegen without the checker, and if you add an AST construct that
codegen needs type info for, attach it during `infer`/`check_*`, not in codegen.**

### C identifier hygiene

Every G identifier that reaches C goes through `Checker.safe_c_name` (codegen exposes it as
`cn()`): C keywords and libc names get a `_g` suffix, and `declare()` appends `_sK` when a
local would collide with a global/function. Codegen must apply `cn()` to **every** emitted
name (struct/enum/typedef/field/variant/param/global/method), and use `Ident.c_name` when set.
`main` and `extern` symbols keep their raw name. Pointer/array declarators are built by
`c_decl()` (east-const, `int (*p)[3]`, `int *a[2]`), never by string-concatenating `*`.

### Error recovery

`err()` raises `CheckError`; `check_block` and the top-level loop wrap each statement/function
in `_recover()`, which records the error, restores scope depth, and continues. A failing `let`
still declares its name (type `unknown`) to avoid cascades. All errors are raised together as
`CheckErrors` (cap `CheckErrors.MAX = 20`); the driver renders each and prints `gc: N lỗi`.
Inside expressions errors still propagate immediately — do not "recover" mid-expression.

### Checker pass ordering (in `Checker.check`)

Declarations are collected in multiple passes *before* bodies are checked, which is what
enables forward references (call a function/use a struct defined later):
`_all_funcs` (for comptime) → `collect_const_values` → `collect_types` →
`collect_funcs` → `collect_globals` → then per-function/`impl` body checking.

### Comptime constant folding

`_fold_const_int` plus the `_ct_*` methods form a **bounded interpreter** over G's integer
subset (let/assign/if/while/for/return + arithmetic, with a step budget). It folds array
sizes (`[CAP*2+1]int`), enum values, and `sizeof`/`alignof` of types into compile-time
constants. Anything outside the supported subset returns `None` (treated as non-constant).

### Runtime checks

Codegen wraps dynamic indexing of **static arrays** in `g_idx(i, n, "file:line:col")` and
integer `/`, `%`, `/=`, `%=` with a non-constant divisor in `g_chk_div(...)` (both macros in
`runtime/g_runtime.h`; they panic with a location). Constant indices/divisors are checked
statically by the checker instead (`_is_const_expr` in codegen decides). `--no-checks` defines
`G_NO_CHECKS` which turns both macros into identity. Pointers/`[]T` carry no length and are
never checked. In freestanding mode the failure path halts the CPU.

### Static checks that guard the C backend

The checker deliberately rejects things C would accept (or only warn about) because the
generated C would be wrong or produce confusing gcc errors. Notable ones, so you don't
"fix" them as false positives: global initializers may only reference globals declared
*earlier* (`_check_global_init_order` — runtime ctor runs in declaration order); duplicate
`extern`/definition with a differing signature (`_sig_text` compare in `collect_funcs`);
`extern fn` names in `_RUNTIME_DEFINED` (codegen) get **no** prototype because
`g_runtime.h`/libc already defines them; writing through `str` (`const char*`);
`return &local` / `return &local.field` / `return &local_arr[i]` (`_check_return_local_addr`);
`bool` only compares with `bool`; format keys must be in `_FMT_KEYS` and flags must match
`_FMT_FLAGS_RE`; `match` on `bool` must be exhaustive and constant patterns covered by an
earlier range arm are errors; `@naked` bodies must be pure `asm { }` with no return type.
Array literals in expression position (call args, `[1,2][i]`) lower to C99 compound
literals; inside struct literals / `let` / globals they stay as bare `{ ... }` initializers.

### Expression forms lowered in the parser/codegen

`if`/`match` in *expression* position are separate from their statement forms.
`if c { a } else { b }` is desugared by the parser straight into `A.Ternary`
(so it reuses all `?:` checking/codegen); `match` becomes `A.MatchExpr`, checked
by `infer_match_expr` (which sets `is_expr` and reuses `check_match` for
exhaustiveness/dead-arm/binding checks) and emitted by `gen_match_expr` as a GNU
statement-expression. Both require every branch to yield a value: `else` is
mandatory and `match` must be exhaustive. `[v; N]` array literals carry a
`repeat` field that the *checker* expands into N copies of the element before
any inference runs, so everything downstream sees a plain `ArrayLit`.

### `defer` and the return value

`gen_stmt`'s `A.Return` branch evaluates the return expression into an
`__auto_type` temp *before* flushing defers, whenever any enclosing scope has a
pending defer. Zig/Go semantics: the returned value is snapshotted, so a defer
that mutates a global cannot change what the caller sees. The temp is skipped
when there are no defers, keeping the generated C clean.

### Reserved C names include all of libm

The driver always links `-lm`, so every `<math.h>` symbol (plus its `f`/`l`
suffixed variants) is in `Checker.C_RESERVED` and gets renamed. Miss one and a
user's `let mut log = 0` becomes `static int log;`, colliding with `log()` and
surfacing a raw C error. Add to this set whenever the runtime pulls in a new
library.

### Target capabilities, not architecture names

`compiler/target.py` maps each OS-dev intrinsic to a *capability*
(`INTRINSIC_CAPS`), and each `Target` declares the set it has. `Checker.
_check_target_cap` rejects anything the target lacks. Adding an architecture is
one entry in `TARGETS` — no checker or codegen changes.

Use capabilities rather than `if arch == "x86"`: `rdtsc` and `outb` are both
x86 instructions, but a cycle counter *has* an equivalent on aarch64
(`cntvct_el0`) while port I/O simply does not exist. Lumping them under "x86"
would wrongly block `rdtsc` on ARM.

The runtime half matters just as much: the non-x86 `#else` block used to define
every x86 intrinsic as a silent no-op, so an `outb`-based driver compiled clean
and did nothing. Now it implements what genuinely has an equivalent and
**omits** what does not — a link error beats a silent no-op. Never add a no-op
stub there to "make it compile".

### Slices are fat pointers, and the checker owns the coercion

`slice<T>` is `GType(kind="slice", elem=T, mutable_slice=bool)`, lowered to a C
struct `{ T* ptr; size_t len; }` (`G_SLICE_DEF` in the runtime), one typedef per
element type since C has no generics.

Two rules that must not be relaxed:
- a slice never decays to `*T` (`assignable` returns False) — decaying throws
  away the length, which is the entire reason slices exist;
- write permission lives in the *type* (`mut slice<T>`), not in the mutability
  of the variable holding it. `_check_lvalue_mutable` special-cases slices:
  `xs[i] = v` mutates the pointee, so it must not demand `mut xs`.

Array→slice coercion is decided in **one place**: `Checker.coerce()`, which tags
the node with `to_slice=(n, mutable)`. `Codegen.gen_expr` and `IRGen.gen_expr`
each honour that tag at a single entry point. Do not scatter the "is the target
a slice?" question across call/assign/return sites — that duplication is exactly
what the IR work was meant to eliminate. `coerce()` also rejects borrowing write
access from an immutable array and calls `_mark_written` (otherwise the
unused-`mut` warning fires falsely).

Printing: a slice's length is only known at runtime, so unlike static arrays it
cannot use a compile-time format string. `_slice_print_fn` emits one printer per
element type. Those printers dereference struct fields, so they are spliced in
**after** struct definitions (`slice_print_at`), while the typedefs go earlier
(`fnptr_at`) because signatures need them.

### The IR is the architectural seam

`compiler/ir.py` + `irgen.py` + `irverify.py` + `backend.py` exist because the
checker↔codegen contract used to be ~37 dynamic attributes stuck onto AST nodes
and read back with `getattr` defaults — a second backend would silently miscompile
by forgetting one. Read `ARCHITECTURE.md` before touching them.

Key point for contributors: **the C backend still lowers straight from the AST.**
The IR runs in parallel and is verified by `tests/run_ir.sh`, but nothing ships
through it yet. That is deliberate (ARCHITECTURE.md §3) — it keeps regression
risk at zero while proving the IR covers the language.

When you add a language feature you must extend `irgen.py` too, or
`tests/run_ir.sh` goes red. That is the point: it stops the IR from rotting.

Dead-code regions: `IRGen._dead` is set when every path has already exited (all
match arms return, infinite `loop` with no `break`). In a dead region `gen_stmt`
returns immediately — emitting IR for unreachable statements adds no semantics
and creates orphan blocks the verifier then flags.

### Fuzzing

`tests/run_fuzz.py` mutates the real corpus and generates random token soup, then
asserts the compiler either reports a *controlled* error (`LexError`/`ParseError`/
`CheckError`/`IRGenError`) or produces verifiable IR. An `AttributeError`,
`IndexError`, or a hang is a bug. Two of its finds were in `lexer.advance()`
returning `""` at EOF: `"" in "0123..."` is `True` in Python, so the hex-escape
loops spun forever. Watch for that idiom.

### Sanitizer runs are a separate suite

`tests/run_asan.sh` rebuilds every example/case with
`-fsanitize=address,undefined` and runs it — this is what proves the runtime's
bounds clamping is real. Leaks are off by default (`LEAKS=1` enables them)
because heap strings need a manual `g_free` and many examples skip it for
brevity; the memory-ownership rules are documented in README.

### Warnings

`Checker.warnings` collects non-fatal diagnostics; `driver` prints them in
yellow after a clean check, and `-w`/`-W` suppress them / turn them into errors.
Unused-variable detection lives in `Checker.pop()`: `_decl_nodes` maps a scope
entry to its declaring node, `_used_names` records reads (set in `lookup`), and
`_assigned_cnames` records writes. Anything that can write *indirectly* must
call `_mark_written` — `&x`, a self-mutating method receiver, `for mut x in a`,
and `_check_lvalue_mutable` (which marks up front, because its
"write-through-pointer" branches return early). Constant folding also has to
call `_used_names.add`, since a `const` used only as an array size never goes
through `lookup`. The `tests/warn/` category asserts the exact *count* of
warnings, so a false positive fails the suite.

### Destructuring desugars in the parser

`let P{x, y} = v` becomes an `A.Multi` holding a hidden `Let` for `v` (tagged
`destructure_of`) plus one `Let` per binding reading a field off it — so `v` is
evaluated once. `parse_block` flattens `A.Multi` immediately, meaning no later
pass needs to know it exists, and the bindings land in the *enclosing* scope
(an `A.Block` would have created a new one). The hidden temp is exempt from the
unused-variable warning.

### String slices allocate

`s[a..b]` is `A.Slice` -> `g_str_slice`, which clamps both bounds, so
out-of-range indices give a short/empty string instead of reading past the
buffer. It allocates, hence it is rejected under `--freestanding`. Arrays are
deliberately *not* sliceable: G has no length-carrying slice type.

### Arrays are values, and C fights you on it

Two places must copy explicitly or C silently shares memory: `gen_let` emits a
real array plus `memcpy` for `let b = a` (never `__auto_type`), and `gen_fn`
copies `mut` array parameters into a local buffer in the prologue while
`fn_signature` renames the incoming pointer to `<name>__src`.

### `mut` on parameters is real

`Param.mutable` is set by the parser and passed to `declare()` in
`check_function`, so a parameter without `mut` is an immutable binding just like
a `let`. `self` is force-mutable (whether the *receiver* may be mutated is a
separate check in `_require_mutable_receiver`). `_is_param` exists only to pick
the right hint: parameters are fixed with `mut x: T`, not `let mut`.

### Struct literals must be complete

`infer_struct_lit` requires every field of a non-empty struct to be present.
C's designated-initializer syntax zero-fills anything omitted, so without this
check adding a field to a struct silently gives every existing literal a 0 for
it. `struct_order` supplies declaration order for the error message.

### `Program.imports` carries positions

Imports are `(name, line, col)` tuples, not bare strings; `load_program` uses
them so a bad import points at its own line. `driver` still accepts a bare
string for compatibility. Relatedly, `Parser.error(msg, show_token=False)`
suppresses the `(gặp <token>)` suffix — use it whenever the message already
names the fix, since the suffix reports the token *after* the mistake.

### The checker knows about `--freestanding`

`Checker(prog, freestanding=...)` is threaded from `driver.compile_to_c`. When
set, `_HOSTED_ONLY` built-ins (anything needing stdio or the heap) and
`_HEAP_STR_METHODS` are rejected with a G-level diagnostic. Without this the
program type-checked fine and then died inside the C backend with errors like
`'stdout' undeclared`, which is unreadable for a G user. If you add a built-in
that calls libc, add it to `_HOSTED_ONLY` too. `tests/fail_fs/` covers this: each
case must pass `--check` hosted and fail `--freestanding --check`.

### Printing a whole array

`_gtype_print_frag` (codegen) is the single generic "print one value of GType
`gt`" entry point: struct → expand fields, static array → `_gtype_array_frag`
(recursive, capped at `_PRINT_ARRAY_MAX`), enum → variant name, else a printf
spec. `build_format`, `gen_print` and `dbg` all route arrays through it. One
subtlety: arrays must **not** be hoisted into an `__auto_type` temp (that decays
to a pointer and loses the size), so `gen_print` passes the array expression
through unmaterialized — safe because arrays are always stable lvalues here.
The checker only rejects `void` and *dynamic* arrays from format position.

### `::` is an alias for `.` on type paths

`parse_postfix` accepts `Ident :: name` and builds the same `A.FieldAccess` the
`.` form does, tagged `via_path`. The parser rejects a non-`Ident` base; the
checker rejects `via_path` when the base isn't a struct/enum type name. So
`Color::Red` and `Counter::new()` work, `p::x` gets a "use `p.x`" error.

### `for mut x in arr` binds by reference

Unlike the read-only `for x in arr` (which copies each element), `for mut x`
lowers `x` to a **pointer** to the element so writes land in the array. The
checker sets `by_ref` on the `ForEach` node and records the name in
`_by_ref_vars`, which makes `infer_ident` tag every `A.Ident` with
`by_ref_elem`; codegen then emits `(*x)` for those. Exception: when the element
is itself an array (iterating rows of a 2-D array) the row already decays to a
pointer, so `by_ref_deref` is cleared and no extra `*` is added. Arrays are the
only writable iterable — `for mut` over a `str` or an array literal is an error.

### Value-typed arrays can't come out of expressions

Functions may not return arrays by value, and for the same reason `match`/`?:`
in expression position reject array-typed arms: C decays both branches to a
pointer, so G's copy semantics would silently become sharing (and an array
literal arm would dangle). Keep these two checks in sync if you add another
value-producing construct.

### `str` has built-in methods

`s.len()`, `s.upper()`, `s.sub(a, b)` etc. are pure syntax sugar: `_STR_METHODS`
in the checker maps a method name to a runtime C function, the receiver becomes
the first argument, and `gen_call` emits `g_str_*(recv, args...)`. They are NOT
real methods — you cannot define new ones on `str` via `impl`. Wrapper functions
(`g_str_len_i`, `g_substr_i`, ...) exist purely to return the exact G-declared
type without callers casting.

### Generated C must stay warning-free

The generated C compiles clean under `-Wall -Wextra` and the test runner assumes
that. Three deliberate choices keep it that way, so don't "simplify" them:
immutable *arrays* get no C `const` (a `const T[]` decaying into a `T*` parameter
warns even though G already proved immutability statically); `&x` on a `let`
scalar/struct casts away `const` (G permits writing through such pointers);
and the `for i in a..b` upper bound is cast to the loop variable's type rather
than `__auto_type` (otherwise `size_t` counters vs `int` bounds trip
`-Wsign-compare`).

### C backend is GCC/Clang-specific, not portable C

Generated code is compiled with `-std=gnu11` and uses extensions deliberately:
statement-expressions `({ ... })` (for evaluate-once builtins like `min`/`swap`/`dbg`,
left-to-right argument ordering, and `format`), `__auto_type`, `__attribute__((constructor))`
(for non-constant global initializers — C forbids dynamic static initializers), and
`__builtin_unreachable`. Do not assume standard C.

Other lowering worth knowing: string `==`/`!=` → `g_str_eq` (content compare, null-safe);
`match` → independent `if` + `goto end` chain (so guard arms can *fall through* to the next
arm — a plain `else if` chain cannot); method `recv.method(args)` → `Struct__method(&recv,
args)`; function-pointer types → generated `typedef`s spliced in after struct forward-decls.

## Adding a language feature

A new construct typically threads through the stages in order:
**lexer** (keyword/operator) → **ast_nodes** (node) → **parser** (produce node) → **checker**
(infer/validate, attach annotations) → **codegen** (emit C). Use `--tokens`, `--ast`, and
especially `--emit-c` to inspect each stage in isolation.

## OS development (v0.6.0+)

G targets bare-metal/kernel work. The pieces, and where they live:

- **Freestanding mode** (`driver.py`): `--freestanding` passes `-DG_FREESTANDING
  -ffreestanding -nostdlib -fno-stack-protector -fno-pic`; `-c`/`--compile-obj` emits a `.o`;
  `-S`/`--emit-asm` emits `.s`. Freestanding `-c`/`-S` and any `--freestanding exe` skip the
  `main` requirement (entry is user/linker-defined). `runtime/g_runtime.h` is gated by
  `#ifdef G_FREESTANDING`: the freestanding branch includes only `stdint/stddef/stdbool`,
  self-implements `memcpy/memset/memmove/memcmp` (with `no-tree-loop-distribute-patterns` so
  GCC doesn't turn them into self-calls), and makes `g_panic` a `cli; hlt` loop. Hosted libc
  helpers (g_alloc/g_str_*/print/read/test framework) are NOT available freestanding.

- **OS intrinsics are builtins**, not new syntax — added to `BUILTINS` in `checker.py`,
  type-inferred in `infer_builtin`, and lowered in `codegen.py` via `Codegen._gen_os_call`
  (gated by `Codegen._OS_BUILTINS`). The CPU/port intrinsics map to `g_*` static-inline
  functions in `g_runtime.h` (x86 asm behind `#if defined(__x86_64__)||defined(__i386__)`,
  with safe no-op fallbacks elsewhere). Width-aware bit ops (`clz/ctz/bswap/rotl/rotr`)
  read the argument's `gtype.bits` so `clz(1 as u8) == 7`, not 63.

- **`@attributes`** (`ast_nodes.Attr`): parsed by `parser.parse_attrs` (prefix `@name`/
  `@name(args)`; `@` is already a SINGLE_OP; ASI inserts `;` after each — `skip_semis`
  handles it). Validated by `Checker.validate_attrs` against `_ATTR_TABLE` (target kind +
  arity + arg type). Lowered by `Codegen._gnu_attrs` → `__attribute__((...))` placed on
  struct definition / before fn signature / after `static` for globals.

- **`extern let`** (`GlobalVar.is_extern`): parser routes `extern let/const` to
  `parse_global`; requires a type, forbids a value; codegen emits `extern T NAME;`.

- **Extended inline asm** (`ast_nodes.Asm` now carries `outputs/inputs/clobbers/extended`):
  `parser.parse_asm` parses `"tmpl" : outs : ins : clobbers` with `"constraint"(expr)`
  operands; `Checker.check_stmt`'s `A.Asm` case infers operands (sets c_name, requires output
  operands be mutable lvalues); `Codegen.gen_asm` emits GCC extended asm.

- **Tests**: runnable user-space coverage in `tests/cases/os_intrinsics.g` + `attrs_os.g` +
  `examples/os_features.g`; privileged/freestanding coverage compiled-not-run in
  `tests/freestanding/` + `examples/kernel/` (see test-harness section). The full bootable
  demo (G kernel + multiboot `boot.s` + `linker.ld` + `Makefile`) is `examples/kernel/`.
