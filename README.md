# mach-lsp

Language server for the [Mach](https://github.com/octalide/mach) programming language, implementing the [Language Server Protocol](https://microsoft.github.io/language-server-protocol/).

Written in Mach. Uses the Mach compiler as a dependency for real semantic analysis — no reimplemented parsers, no semantic drift.

## Architecture

`mach-lsp` is a standalone project that imports the Mach compiler (`mach`) as a dependency via Mach's own module system. This means the LSP uses the **exact same** lexer, parser, semantic analyzer, symbol table, and type system as the compiler itself.

```
mach-lsp/
├── mach.toml               # project config; declares mach + mach-std as deps
├── src/
│   ├── main.mach            # entry point — initializes server and enters loop
│   ├── server.mach          # lifecycle management and message dispatch
│   ├── transport.mach       # JSON-RPC framing over stdin/stdout (LSP base protocol)
│   ├── handler.mach         # request/notification handler implementations
│   ├── workspace.mach       # open document tracking, line offset tables
│   └── json.mach            # minimal JSON extraction and construction utilities
└── dep/
    ├── mach/                # vendored compiler (provides mach.compiler.*)
    └── mach-std/            # vendored standard library
```

### Why a separate repo?

The compiler's internals (`mach.compiler.lexer`, `mach.compiler.parser`, `mach.compiler.sema`, etc.) are imported directly as library code — zero duplication. But LSP infrastructure (JSON-RPC transport, long-lived workspace state, incremental document tracking) is fundamentally different from batch compilation, so it lives in its own project. This keeps the compiler binary lean and lets the LSP version independently.

## Current Status

The LSP is functional with the following capabilities:

| Feature | Status |
|---|---|
| `initialize` / `shutdown` / `exit` lifecycle | ✅ |
| `textDocument/didOpen`, `didChange`, `didClose` | ✅ |
| `textDocument/hover` | 🔨 Stub (shows document info) |
| `textDocument/definition` | 🔨 Stub (returns null) |
| `textDocument/completion` | 🔨 Stub (returns empty list) |
| `textDocument/documentSymbol` | 🔨 Stub (returns empty list) |
| Diagnostics (publish on change) | ⬚ Not yet implemented |
| Semantic tokens | ⬚ Not yet implemented |

The transport, protocol handling, workspace management, and JSON utilities are fully implemented. The stubs are where the compiler dependency comes in — each one is a hook point for wiring in `mach.compiler.*` modules.

### Roadmap

1. **Diagnostics** — Run the lexer + parser on document changes, map `ParserError` and `SemaError` to LSP diagnostics, push via `textDocument/publishDiagnostics`.
2. **Document symbols** — Walk the AST from the parser to extract top-level declarations.
3. **Hover** — Look up the symbol under the cursor via sema, display its type.
4. **Go-to-definition** — Query the symbol table for definition locations.
5. **Completion** — Enumerate visible symbols from the current scope.

## Prerequisites

- The Mach compiler (`cmach` bootstrap or self-hosted `mach`), built from the [mach](https://github.com/octalide/mach) repository.
- The [mach-std](https://github.com/octalide/mach-std) standard library.

## Build

```bash
git clone https://github.com/octalide/mach-lsp.git
cd mach-lsp
mach dep pull
mach build .
```

The compiled binary is written to `out/linux/bin/mach-lsp` (or the equivalent path for your target).

## Usage

The language server communicates over stdin/stdout using the LSP base protocol. Point your editor to the `mach-lsp` binary:

### Zed

Install the [mach-zed](https://github.com/octalide/mach-zed) extension. It declares `mach-lsp` as the language server — just make sure the binary is on your `$PATH`.

### Neovim (nvim-lspconfig)

```lua
local lspconfig = require("lspconfig")
local configs = require("lspconfig.configs")

configs.mach_lsp = {
  default_config = {
    cmd = { "mach-lsp" },
    filetypes = { "mach" },
    root_dir = lspconfig.util.root_pattern("mach.toml"),
  },
}

lspconfig.mach_lsp.setup({})
```

### Manual testing

You can pipe JSON-RPC messages directly for debugging:

```bash
echo -ne 'Content-Length: 60\r\n\r\n{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | ./out/linux/bin/mach-lsp
```

## Memory Management

The LSP uses `std.allocator.heap_allocator()` — the brk-based bump allocator from the standard library. All server-owned memory (documents, line tables, response buffers) flows through the `Allocator` interface, keeping allocation strategy decoupled from business logic. Temporary buffers used for JSON construction are allocated and freed per-response.

## Dependencies

Declared in `mach.toml`:

```toml
[deps.mach-std]
type = "remote"
path = "https://github.com/octalide/mach-std"
version = "branch/dev"

[deps.mach]
type = "remote"
path = "https://github.com/octalide/mach"
version = "branch/dev"
```

The compiler dependency is what makes this project unique among language servers — `mach-lsp` doesn't reimplement the frontend. It `use`s it:

```mach
use lexer:  mach.compiler.lexer;
use parser: mach.compiler.parser;
use sema:   mach.compiler.sema;
use ast:    mach.compiler.ast;
use token:  mach.compiler.token;
use ty:     mach.compiler.type;
```

## License

[MIT](../mach/LICENSE)