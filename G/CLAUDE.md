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
