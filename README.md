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
- Language features over the buffer's resolved analysis (`project.resolve_doc`
  + `ast.offset_to_*` + the `resolve.ResolveResult` side tables):
  - `textDocument/hover` — the declaration header (or kind + name) of the
    symbol at the cursor, as a fenced `mach` code block, with the decl's doc
    comment as trailing prose.
  - `textDocument/definition` — the resolved symbol's declaration `Location`.
  - `textDocument/references` — the symbol's declaration (which may live in a
    dependency file) plus every use-site **across the loaded project graph**
    (the requesting buffer and every other module that references the symbol).
  - `textDocument/rename` / `prepareRename` — a **cross-file** `WorkspaceEdit`
    renaming the declaration, every importer's references, and each importer's
    `use` path leaf; confined to symbols declared in the user's own project.
    `prepareRename` returns the name range for a renameable symbol, null for a
    dependency-declared one.
  - `textDocument/documentSymbol` — the module's top-level declarations as a
    `DocumentSymbol` list.
  - `textDocument/completion` — the file's named declarations, `use` aliases,
    and the primitive type names.

### Cross-module scope

On first analysis the server loads the project's module graph from disk
(`mls.project` runs the compiler's own `driver.build_project` over the manifest
and `dep/` tree) and snapshots every loaded module's exports into a dependency
set, then re-resolves the open buffer against it. So a symbol imported through
a `use` binds to its declaration in a dependency module, and:

- hover / definition reach **cross-module and cross-file** symbols, pointing at
  the defining module's source file on disk (a `file://` location);
- references and rename walk a shared use-site index over the loaded module
  graph (`build_refs` over `mls.project`'s `module_view`): references reports
  every use-site across all modules; rename rewrites the declaring file, every
  importer's body references, and each importer's `use` path leaf (guarded by
  the declared name, so an aliased import's references are left intact).
  Cross-file rename is confined to symbols declared in the user's own project —
  a dependency's declaration is not the editor's to rewrite — and reflects the
  on-disk state of files other than the active buffer, since the project graph
  is a load-time snapshot not rebuilt on `didChange`;
- completion is a flat list of the file's named symbols and the primitives, not
  a lexically scoped view (the resolver's scope chain is not exposed by the
  side tables);
- a document outside any project (no ancestor `mach.toml`) resolves single-file
  with an empty dependency set — references and rename then stay buffer-local.

> **Known limitation (#45):** the vendored `dep/mach` only parses the old
> `[targets.<name>]` manifest format, so cross-module resolution is currently
> **non-functional for v1.4.0-manifest projects — including this repo itself**
> (its own `mach.toml` uses `[target.X]`/`[bin.X]`). Such projects resolve
> single-file and the server reports the load failure via `window/showMessage`.
> Fixed by bumping `dep/mach` to a version that parses the new format.

## Building

The compiler and standard library are vendored under `dep/` as git dependencies.
Build with a Mach compiler binary (v1.4.0 or newer):

```sh
mach dep pull
mach build .
```

The server binary is produced at `out/linux/debug/bin/mls`.

## How the compiler dependency is wired

`dep/mach` (id `mach`) provides the `mach.lang.*` namespace, including the
`mach.lang.editor` query surface this server binds to; `dep/mach-std` (id
`std`) provides `std.*`. Both are declared as git dependencies in `mach.toml`
and fetched by `mach dep pull`; `mach-std` tracks `branch/dev` and `mach` is pinned to `v1.4.0`.

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
| `project` | load the project module graph; re-resolve a buffer against its dependency set; map a symbol to its declaring file's `file://` URI; expose the loaded modules for the workspace-wide use-site walk |
| `language` | hover / definition / references / rename / documentSymbol / completion request bodies |
| `trace` | append-only debug trace log (`/tmp/mach-lsp.log`) |

## Testing

The stdio test suite under `test/` drives the built server with framed
JSON-RPC. `test/harness.py` owns the protocol framing and the spawn helper;
each scenario module asserts one surface:

- `test_diagnostics.py` — broken buffer → diagnostics with ranges; clean
  buffer → empty; `didChange`/`didClose` clear.
- `test_features.py` — local features over a typed source: hover renders
  signatures / types / doc comments, definition lands on the decl, references
  finds decl + use-sites, rename emits a `WorkspaceEdit` (including a parameter
  binding), documentSymbol lists the top-level decls, completion includes the
  file's functions.
- `test_crossmodule.py` — against `test/fixture` (which depends on the vendored
  `mach-std`): definition / references / hover on a `use`d std symbol reach a
  `file://` location inside `dep/mach-std`, a local symbol still resolves in the
  buffer, and renaming a dependency symbol is refused (prepareRename null, empty
  edit).
- `test_workspace.py` — against `test/fixture-ws`, a depless two-module project:
  references on a `pub` symbol used across files returns use-sites in both
  modules, and rename rewrites the declaration, the importer's `use` path leaf,
  and every use-site across both files — invoked from either buffer.

```sh
make test          # builds, then runs test/run.py
```

## Deferred

- workspace symbol search;
- scope-aware completion (member access after `.`, lexically scoped locals)
  — the resolver's scope chain is internal to the resolve pass and not
  exposed by the side tables.
