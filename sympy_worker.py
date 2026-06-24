# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http]>=0.8.4",
#     "sympy>=1.13",
# ]
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

_DESCRIPTION_LLM = (
    "Symbolic math (a computer algebra system) over SymPy, exposed as DuckDB scalar functions. "
    "Algebraically simplify, expand, or factor an expression; differentiate or integrate it with "
    "respect to a variable; solve an equation for a variable (returning a VARCHAR[] of solutions); "
    "substitute numeric values and evaluate to a DOUBLE; render to LaTeX; and test whether two "
    "expressions are symbolically equivalent. Expressions are plain strings (e.g. 'x**2 + 2*x + 1', "
    "'sin(x)**2 + cos(x)**2'); untrusted input is parsed through a hardened allow-list parser, never "
    "eval/sympify. Use for symbolic algebra and calculus inside SQL."
)

_DESCRIPTION_MD = (
    "# sympy\n\n"
    "Symbolic math (a small CAS) over [SymPy](https://www.sympy.org/), as DuckDB scalar functions.\n\n"
    "Scalars: `simplify`, `expand`, `factor`, `to_latex`, `differentiate`, `integrate`, `solve`, "
    "`evaluate`, `symbolic_equal`, `sympy_version`.\n\n"
    "```sql\n"
    "SELECT sympy.simplify('sin(x)**2 + cos(x)**2');  -- '1'\n"
    "SELECT sympy.factor('x**2 - 1');                 -- '(x - 1)*(x + 1)'\n"
    "SELECT sympy.solve('x**2 - 4', 'x');             -- ['-2', '2']\n"
    "SELECT sympy.integrate('2*x', 'x');              -- 'x**2'\n"
    "```\n"
)

_CATALOG_TAGS = {
    "vgi.description_llm": _DESCRIPTION_LLM,
    "vgi.description_md": _DESCRIPTION_MD,
    "vgi.author": "Query.Farm",
    "vgi.copyright": "Copyright 2026 Query Farm LLC - https://query.farm",
    "vgi.license": "MIT",
    "vgi.support_contact": "https://github.com/Query-farm/vgi-sympy/issues",
    "vgi.support_policy_url": "https://github.com/Query-farm/vgi-sympy/blob/main/README.md",
}

_SCHEMA_TAGS = {
    "vgi.description_llm": (
        "Computer-algebra scalar functions over SymPy: simplify, expand, factor, differentiate, "
        "integrate, solve, evaluate, to_latex, and symbolic_equal. Inputs are expression strings; "
        "transforms return NULL for invalid/unsafe input so they compose over messy columns."
    ),
    "vgi.description_md": (
        "Symbolic-math (CAS) scalar functions over SymPy: simplify/expand/factor, "
        "differentiate/integrate, solve, evaluate, to_latex, and symbolic_equal."
    ),
}

_SYMPY_CATALOG = Catalog(
    name="sympy",
    default_schema="main",
    comment="Symbolic math (CAS): simplify/solve/differentiate/integrate/factor for SQL via SymPy.",
    tags=_CATALOG_TAGS,
    source_url="https://github.com/Query-farm/vgi-sympy",
    schemas=[
        Schema(
            name="main",
            comment="Symbolic math (CAS): simplify/solve/differentiate/integrate/factor for SQL",
            tags=_SCHEMA_TAGS,
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
