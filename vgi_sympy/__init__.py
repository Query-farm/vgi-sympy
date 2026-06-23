"""Symbolic math (CAS) as DuckDB SQL functions, via a VGI worker.

The implementation is split so each concern stays focused:

- ``cas``     -- pure symbolic-math logic over SymPy: simplify / expand / factor
  / differentiate / integrate / solve / evaluate / to_latex / symbolic_equal.
  No Arrow or VGI dependency, directly unit-testable. **All untrusted strings
  are parsed through a hardened allow-list parser (never ``sympify``/``eval``)**
  so a malformed or hostile expression yields a clear error, never code
  execution -- see :mod:`vgi_sympy.cas` for the full security model.
- ``scalars`` -- per-row VGI scalar function adapters (positional-only) that map
  the pure logic over Arrow arrays, NULL in -> NULL out.

``sympy_worker.py`` at the repo root assembles these into the ``sympy`` catalog
and runs the worker over stdio (or HTTP).
"""

from __future__ import annotations

__version__ = "0.1.0"
