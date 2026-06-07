# mach-lsp

A language server for the [Mach](https://github.com/octalide/mach) programming
language, built directly on the compiler-as-library editor surface
(`mach.lang.editor`).

## Status

This server implements the **diagnostics** vertical slice plus the
**language features** end-to-end, all on the `mach.lang.editor` surface:

- LSP lifecycle: `initialize`, `initialized`, `shutdown`, `exit`.
- Document synchronization (full-text): `textDocument/didOpen`,
  `didChange`, `didClose`.
- Diagnostics: on open/change the buffer text is fed to `mach.lang.editor`
  (`open` / `update` / `diagnostics`); every reported `diagnostic.Diagnostic`
  is mapped — its byte span through `source.position` to a 0-based LSP range,
  its severity to the LSP scale — and published via
  `textDocument/publishDiagnostics`.
- Language features over the buffer's resolved analysis (`editor.resolve` +
  `ast.offset_to_*` + the `resolve.ResolveResult` side tables):
  - `textDocument/hover` — the declaration header (or kind + name) of the
    symbol at the cursor, as a fenced `mach` code block.
  - `textDocument/definition` — the resolved symbol's declaration `Location`.
  - `textDocument/references` — every in-file position resolving to the same
    symbol (declaration plus use-sites).
  - `textDocument/rename` / `prepareRename` — a `WorkspaceEdit` renaming every
    in-file reference; `prepareRename` returns the name range.
  - `textDocument/documentSymbol` — the module's top-level declarations as a
    `DocumentSymbol` list.
  - `textDocument/completion` — the file's named declarations, `use` aliases,
    and the primitive type names.

### Single-file scope

The editor resolves one buffer in isolation with an empty dependency set, so
resolution is **single-file**. A reference to a locally declared symbol binds
fully (its declaration is in the same buffer); a symbol imported through a
`use` resolves against dependency modules this server never loaded, so:

- hover/definition/references/rename are complete for **local** symbols;
- a cross-module `use`d symbol does not resolve, so those features return
  `null`/empty for it rather than a wrong answer — never a faked result;
- completion is a flat list of the file's named symbols and the primitives,
  not a lexically scoped view (the resolver's scope chain is not exposed by
  the side tables).

Full-project resolution (cross-module go-to-def, workspace symbols,
scope-aware completion) needs the driver's dependency loading wired into the
editor surface, tracked upstream.

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
| `positions` | byte offset ⇄ LSP `(line, character)` and span text |
| `features` | offset → id → symbol query core over the resolve side tables |
| `language` | hover / definition / references / rename / documentSymbol / completion request bodies |
| `trace` | append-only debug trace log (`/tmp/mach-lsp.log`) |

## Testing

Two stdio smoke tests drive the server with framed JSON-RPC:

- `smoke.py` asserts diagnostics (broken buffer → diagnostics with ranges;
  clean buffer → empty; `didChange`/`didClose` clear).
- `smoke_features.py` asserts the language features against a small typed
  source: hover renders signatures/types, definition lands on the decl,
  references finds decl + use-sites, rename emits a `WorkspaceEdit`,
  documentSymbol lists the top-level decls, completion includes the file's
  functions and the primitives.

```sh
mach build && python3 smoke.py && python3 smoke_features.py
```

## Deferred

These need full-project resolution (the driver's dependency loading wired into
the editor surface), which is out of scope for the single-file query layer:

- cross-module go-to-definition / hover / references (symbols imported via
  `use` resolve against dependency modules the editor does not load);
- workspace symbol search;
- scope-aware completion (member access after `.`, lexically scoped locals)
  — the resolver's scope chain is internal to the resolve pass and not
  exposed by the side tables.
