# mach-lsp

A language server for the [Mach](https://github.com/octalide/mach) programming
language, built directly on the compiler-as-library editor surface
(`mach.lang.editor`).

## Status

This server implements the **diagnostics** vertical slice end-to-end:

- LSP lifecycle: `initialize`, `initialized`, `shutdown`, `exit`.
- Document synchronization (full-text): `textDocument/didOpen`,
  `didChange`, `didClose`.
- On open/change, the buffer text is fed to `mach.lang.editor`
  (`open` / `update` / `diagnostics`); every reported `diagnostic.Diagnostic`
  is mapped — its byte span through `source.position` to a 0-based LSP range,
  its severity to the LSP scale — and published via
  `textDocument/publishDiagnostics`.

Language features (`hover`, `definition`, `references`, `rename`,
`completion`, `documentSymbol`) are **not yet implemented** — see
[deferred](#deferred).

## Building

The compiler and standard library are vendored as git submodules under `dep/`.
Build with a Mach compiler binary (v1.0.0 or newer):

```sh
git submodule update --init
mach build
```

The server binary is produced at `out/linux/bin/mach-lsp`.

## How the compiler dependency is wired

`dep/mach` (id `mach`) provides the `mach.lang.*` namespace, including the
`mach.lang.editor` query surface this server binds to; `dep/mach-std` (id
`std`) provides `std.*`. Both are git submodules pinned to the `dev` branch of
their upstream repositories. The `mach.toml` `[deps.*]` entries declare them as
remote dependencies tracking `branch/dev`.

## Architecture

| Module | Responsibility |
|---|---|
| `main` | entry point; page allocator + server loop |
| `server` | lifecycle state, message loop, method dispatch |
| `transport` | LSP base-protocol framing over stdin/stdout |
| `json` | minimal JSON field extraction and response assembly |
| `documents` | URI ⇄ editor `FileId` registry |
| `diagnostics` | run `editor.diagnostics`, map spans, publish |
| `trace` | append-only debug trace log (`/tmp/mach-lsp.log`) |

## Testing

`smoke.py` drives the server over stdio with framed JSON-RPC and asserts the
diagnostics behaviour (broken buffer → diagnostics with ranges; clean buffer →
empty; `didChange`/`didClose` clear):

```sh
mach build && python3 smoke.py
```

## Deferred

The following are tracked as a follow-up (see issue #33). They require an
offset → `ExprId`/`DeclId`/`TypeId` lookup (`ast.offset_to_*`) plus the
`resolve.ResolveResult` side tables, a from-scratch query layer against the
new id-based AST:

- `textDocument/hover`
- `textDocument/definition`
- `textDocument/references`
- `textDocument/rename` / `prepareRename`
- `textDocument/completion`
- `textDocument/documentSymbol`
