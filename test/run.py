#!/usr/bin/env python3
"""run the whole mach-lsp test suite over the built server and report results.

each scenario module exposes `run()` returning a list of failure strings; this
aggregates them and exits non-zero if any scenario fails. invoke via `make
test` (which builds first) or directly with the server already built.
"""
import sys

import test_diagnostics
import test_features
import test_crossmodule
import test_workspace
import test_multiroot
import test_invalidation

SUITES = [
    ("diagnostics", test_diagnostics.run),
    ("features", test_features.run),
    ("crossmodule", test_crossmodule.run),
    ("workspace", test_workspace.run),
    ("multiroot", test_multiroot.run),
    ("invalidation", test_invalidation.run),
]


def main():
    total = 0
    for name, run in SUITES:
        failures = run()
        total += len(failures)
        if failures:
            print(f"[FAIL] {name}")
            for f in failures:
                print("    -", f)
        else:
            print(f"[ OK ] {name}")
    print()
    if total:
        print(f"FAILED: {total} assertion(s) across the suite")
        return 1
    print("PASSED: all scenarios")
    return 0


if __name__ == "__main__":
    sys.exit(main())
