# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python",
#     "sympy>=1.13",
# ]
#
# [tool.uv.sources]
# vgi-python = { path = "../vgi-python" }
# ///
"""VGI worker exposing symbolic math (a small CAS) to SQL.

Assembles the scalar functions in ``vgi_sympy`` into a single ``sympy`` catalog
and runs the worker over stdio (DuckDB subprocess) or HTTP. It does computer
algebra -- simplify, expand, factor, differentiate, integrate, solve, evaluate,
to_latex, symbolic_equal -- as DuckDB scalar functions over SymPy.

Untrusted expression strings are parsed through a hardened allow-list parser
(``parse_expr`` with a restricted ``local_dict`` and empty ``global_dict``;
never ``sympify``/``eval``), so a malformed or hostile expression yields a clear
error or NULL, never code execution. See ``vgi_sympy/cas.py`` and the README.

Usage:
    uv run sympy_worker.py              # serve over stdio (DuckDB subprocess)

    INSTALL vgi FROM community; LOAD vgi;
    ATTACH 'sympy' (TYPE vgi, LOCATION 'uv run sympy_worker.py');

    SELECT sympy.simplify('sin(x)**2 + cos(x)**2');     -- '1'
    SELECT sympy.expand('(x + 1)**2');                  -- 'x**2 + 2*x + 1'
    SELECT sympy.factor('x**2 - 1');                    -- '(x - 1)*(x + 1)'
    SELECT sympy.differentiate('x**3', 'x');            -- '3*x**2'
    SELECT sympy.integrate('2*x', 'x');                 -- 'x**2'
    SELECT sympy.solve('x**2 - 4', 'x');                -- ['-2', '2']
    SELECT UNNEST(sympy.solve('2*x = 10', 'x'));        -- 5
    SELECT sympy.evaluate('x**2 + y', '{"x":3,"y":1}'); -- 10.0
    SELECT sympy.to_latex('x**2');                      -- 'x^{2}'
    SELECT sympy.symbolic_equal('2*(x+1)', '2*x+2');    -- true
    SELECT sympy.sympy_version();
"""

from __future__ import annotations

from vgi import Worker
from vgi.catalog import Catalog, Schema

from vgi_sympy.scalars import SCALAR_FUNCTIONS

_FUNCTIONS: list[type] = [*SCALAR_FUNCTIONS]

_SYMPY_CATALOG = Catalog(
    name="sympy",
    default_schema="main",
    schemas=[
        Schema(
            name="main",
            comment="Symbolic math (CAS): simplify/solve/differentiate/integrate/factor for SQL",
            functions=list(_FUNCTIONS),
        ),
    ],
)


class SympyWorker(Worker):
    """Worker process hosting the ``sympy`` catalog."""

    catalog = _SYMPY_CATALOG


def main() -> None:
    """Run the sympy worker process (stdio or, via flags, HTTP)."""
    SympyWorker.main()


if __name__ == "__main__":
    main()
