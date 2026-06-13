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
- Workspace file watching: `workspace/didChangeWatchedFiles` invalidates the
  affected project root's graph, registered via `client/registerCapability`.
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

The server keeps a **per-root** map of project graphs: each open document is
routed to the project root that governs its path (the nearest ancestor
`mach.toml`), and that root's module graph is loaded from disk on first use
(`mls.project` runs the compiler's own `driver.build_project` over the manifest
and `dep/` tree, snapshotting every loaded module's exports into a dependency
set). The buffer is then re-resolved against its root's dep set, so several
projects open in one session resolve independently. A document that is a
dependency module of another root — one already loaded (e.g. a dep source opened
via go-to-definition), or the project whose manifest declares the document's own
nested root as a dep vendor dir, loaded on demand when the dep file is opened
first — is bound to that root read-only rather than spun up as its own project,
regardless of document open order. A symbol imported through a `use` binds to
its declaration in a dependency module, and:

- hover / definition reach **cross-module and cross-file** symbols, pointing at
  the defining module's source file on disk (a `file://` location);
- references and rename walk a shared use-site index over the document's root
  graph (`build_refs` over `mls.project`'s `module_view`): references reports
  every use-site across that root's modules; rename rewrites the declaring file,
  every importer's body references, and each importer's `use` path leaf (guarded
  by the declared name, so an aliased import's references are left intact).
  Cross-file rename is confined to symbols declared in the user's own project —
  a dependency's declaration is not the editor's to rewrite, whether referenced
  cross-module or opened directly as the buffer — and reflects the on-disk state
  of files other than the active buffer (the project graph is a load-time
  snapshot, not rebuilt on `didChange`). When a module-scope `pub` symbol's
  cross-file identity cannot be recovered from its stale on-disk twin (unsaved
  edits renamed the declaration), rename refuses with an empty edit rather than
  emit a partial, compile-breaking one;
- completion is a flat list of the file's named symbols and the primitives, not
  a lexically scoped view (the resolver's scope chain is not exposed by the
  side tables);
- a document outside any project (no ancestor `mach.toml`) resolves single-file
  with an empty dependency set — references and rename then stay buffer-local.

A root's graph is **invalidated and rebuilt** when its sources change on disk:
the server registers `workspace/didChangeWatchedFiles` watchers (via
`client/registerCapability` when the client supports dynamic registration) for
the manifest, lockfile, and source trees, and a change to any file under a root
drops that root so the next request reloads it. With watching active, editing a
dependency source or pulling updated deps serves the new positions and text
rather than the as-of-first-load snapshot. For clients that do not deliver watch
notifications, a manifest/lockfile mtime check on each access reloads the root —
and retries a previously failed load once the manifest is fixed — but bare
source edits are only picked up through a watch notification (or a manifest /
lockfile touch).

> **Module-id namespacing:** `driver.build_project` numbers modules from 0 and
> writes them into the session's global module registries, so a second build
> over the same session clobbers the first there. The server sidesteps this by
> never reading those session registries — every cross-module lookup reads the
> per-root `driver.Project.modules` array, whose ids are private to that project
> — so several graphs coexist in one shared session (and one source map /
> interner) without collision, and no per-root sessions are needed.

> **Scope note:** each root's graph is the import-reachable module closure of the
> manifest's default target (the compiler's own DFS load), so project files
> outside that closure — secondary `bin` targets, modules nothing imports — are
> still not in the graph: references cannot see their use-sites and rename
> silently leaves them untouched. Loading every declared target per root would
> need path-deduplicated multi-graph merging (to avoid duplicate edits for
> modules shared between targets) and is deferred.

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
and fetched by `mach dep pull`; `mach-std` is pinned to `v0.6.0` and `mach`
tracks `branch/main`.

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
| `project` | per-root project graphs: route a document to its governing root, load each root's module graph, re-resolve a buffer against its root's dependency set, map a symbol to its declaring file's `file://` URI, expose a root's loaded modules for the use-site walk, and invalidate a root on a watched-file change |
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
  edit) — whether referenced cross-module, with the dependency source opened as
  the buffer, or with the dependency source opened cold before any project
  document.
- `test_workspace.py` — against `test/fixture-ws`, a depless two-module project:
  references on a `pub` symbol used across files returns use-sites in both
  modules, and rename rewrites the declaration, the importer's `use` path leaf,
  and every use-site across both files — invoked from either buffer. a
  block-local binding shadowing a pub name renames buffer-local without touching
  importers, and a pub declaration renamed by unsaved edits refuses (empty edit)
  instead of emitting a partial rename.
- `test_multiroot.py` — `test/fixture-ws` and `test/fixture` open in one
  session: each cross-module definition lands in its own project's files, in
  either open order, so the two roots resolve independently.
- `test_invalidation.py` — a scratch copy of `test/fixture-ws`: editing a dep
  source on disk and firing `workspace/didChangeWatchedFiles` (and, separately,
  bumping the manifest mtime for the fallback path) makes the next definition
  serve the shifted declaration line, proving the root's graph reloaded; a
  broken manifest fixed on disk is retried rather than pinned failed.

```sh
make test          # builds, then runs test/run.py
```

## Deferred

- workspace symbol search;
- scope-aware completion (member access after `.`, lexically scoped locals)
  — the resolver's scope chain is internal to the resolve pass and not
  exposed by the side tables.
