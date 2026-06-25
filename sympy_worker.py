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
    SELECT sympy.sympy_version(1);
"""

from __future__ import annotations

import json

from vgi import Worker
from vgi.catalog import Catalog, Schema

from vgi_sympy.scalars import SCALAR_FUNCTIONS

_FUNCTIONS: list[type] = [*SCALAR_FUNCTIONS]

_DESCRIPTION_LLM = (
    "Symbolic math (a computer algebra system) over [SymPy](https://www.sympy.org/), exposed as "
    "DuckDB scalar functions.\n\n"
    "## What it does\n\n"
    "Algebraically **simplify**, **expand**, or **factor** an expression; **differentiate** or "
    "**integrate** it with respect to a variable; **solve** an equation for a variable (returning a "
    "`VARCHAR[]` of solutions); substitute numeric values and **evaluate** to a `DOUBLE`; render to "
    "**LaTeX**; and test whether two expressions are **symbolically equal**.\n\n"
    "## Inputs & outputs\n\n"
    "Expressions are plain strings, e.g. `'x**2 + 2*x + 1'` or `'sin(x)**2 + cos(x)**2'`. Most "
    "transforms return a canonical SymPy string (or `NULL` for invalid/unsafe input, so they compose "
    "over messy columns). `solve` returns `VARCHAR[]`, `evaluate` returns `DOUBLE`, `symbolic_equal` "
    "returns `BOOLEAN`.\n\n"
    "## Safety\n\n"
    "Untrusted input is parsed through a hardened allow-list parser (token screen plus a restricted "
    "namespace with empty `__builtins__`) — never `eval`/`sympify` — so a hostile string is rejected, "
    "never executed.\n\n"
    "Use this catalog for symbolic algebra and calculus directly inside SQL."
)

_DESCRIPTION_MD = (
    "# sympy\n\n"
    "Symbolic math (a small **computer algebra system**) over [SymPy](https://www.sympy.org/), "
    "surfaced as DuckDB scalar functions you can call inline in any query.\n\n"
    "## Overview\n\n"
    "The catalog turns SQL into a calculator for *symbols*, not just numbers: it can rearrange, "
    "differentiate, integrate, and solve algebraic expressions held as text columns.\n\n"
    "## Functions\n\n"
    "`simplify`, `expand`, `factor`, `to_latex`, `differentiate`, `integrate`, `solve`, "
    "`evaluate`, `symbolic_equal`, `sympy_version`.\n\n"
    "## Usage\n\n"
    "```sql\n"
    "SELECT sympy.simplify('sin(x)**2 + cos(x)**2');  -- '1'\n"
    "SELECT sympy.factor('x**2 - 1');                 -- '(x - 1)*(x + 1)'\n"
    "SELECT sympy.solve('x**2 - 4', 'x');             -- ['-2', '2']\n"
    "SELECT sympy.integrate('2*x', 'x');              -- 'x**2'\n"
    "```\n\n"
    "## Notes\n\n"
    "Invalid or unsafe expressions yield `NULL` rather than erroring (except `evaluate`, which raises "
    "on a structurally wrong `vars_json`). Parsing is sandboxed: hostile strings are rejected before "
    "any evaluation happens.\n"
)

_KEYWORDS = json.dumps(
    [
        "sympy",
        "symbolic math",
        "computer algebra",
        "cas",
        "simplify",
        "expand",
        "factor",
        "differentiate",
        "derivative",
        "integrate",
        "integral",
        "solve",
        "equation",
        "evaluate",
        "latex",
        "symbolic equality",
        "algebra",
        "calculus",
    ]
)

_CATALOG_TAGS = {
    "vgi.title": "SymPy Symbolic Math (CAS)",
    "vgi.keywords": _KEYWORDS,
    "vgi.doc_llm": _DESCRIPTION_LLM,
    "vgi.doc_md": _DESCRIPTION_MD,
    "vgi.author": "Query.Farm",
    "vgi.copyright": "Copyright 2026 Query Farm LLC - https://query.farm",
    "vgi.license": "MIT",
    "vgi.support_contact": "https://github.com/Query-farm/vgi-sympy/issues",
    "vgi.support_policy_url": "https://github.com/Query-farm/vgi-sympy/blob/main/README.md",
}

_SCHEMA_DOC_LLM = (
    "## Symbolic-math scalar functions (SymPy)\n\n"
    "The `main` schema groups every computer-algebra scalar in this worker: `simplify`, `expand`, "
    "`factor`, `differentiate`, `integrate`, `solve`, `evaluate`, `to_latex`, `symbolic_equal`, and "
    "`sympy_version`.\n\n"
    "Each function takes expression strings (and, where relevant, a variable name or a JSON of "
    "variable values) and returns a SymPy-canonical string, a list of solutions, a number, or a "
    "boolean. The transforming functions return `NULL` for invalid or unsafe input so they can be "
    "applied across columns of free-form formulas without aborting a scan. Reach for this schema "
    "whenever you need algebra or calculus on symbolic expressions inside SQL."
)

_SCHEMA_DOC_MD = (
    "# main — symbolic math\n\n"
    "Computer-algebra scalar functions over [SymPy](https://www.sympy.org/).\n\n"
    "## Contents\n\n"
    "- **Transforms:** `simplify`, `expand`, `factor`, `to_latex`\n"
    "- **Calculus:** `differentiate`, `integrate`\n"
    "- **Equations:** `solve`, `symbolic_equal`\n"
    "- **Numeric:** `evaluate`\n"
    "- **Meta:** `sympy_version`\n\n"
    "## Usage\n\n"
    "Inputs are expression strings such as `'(x + 1)**2'`. Outputs are SymPy-canonical strings "
    "(stable across runs), a `VARCHAR[]` of solutions, a `DOUBLE`, or a `BOOLEAN`.\n\n"
    "## Notes\n\n"
    "Invalid/unsafe expressions become `NULL` (composes cleanly over messy columns); parsing is "
    "sandboxed and never evaluates hostile input.\n"
)

_EXAMPLE_QUERIES = (
    "SELECT sympy.main.simplify('sin(x)**2 + cos(x)**2');\n"
    "SELECT sympy.main.expand('(x + 1)**2');\n"
    "SELECT sympy.main.factor('x**2 - 1');\n"
    "SELECT sympy.main.differentiate('x**3', 'x');\n"
    "SELECT sympy.main.integrate('2*x', 'x');\n"
    "SELECT sympy.main.solve('x**2 - 4', 'x');\n"
    "SELECT sympy.main.evaluate('x**2 + y', '{\"x\":3,\"y\":1}');\n"
    "SELECT sympy.main.symbolic_equal('2*(x+1)', '2*x+2');"
)

_SCHEMA_TAGS = {
    "vgi.title": "SymPy CAS — main schema",
    "vgi.keywords": _KEYWORDS,
    # VGI123 classifying tags use BARE keys (not vgi.-namespaced).
    "domain": "mathematics",
    "category": "computer-algebra",
    "topic": "symbolic-algebra-and-calculus",
    "vgi.doc_llm": _SCHEMA_DOC_LLM,
    "vgi.doc_md": _SCHEMA_DOC_MD,
    "vgi.example_queries": _EXAMPLE_QUERIES,
    # VGI509: guaranteed-runnable, verified examples for agents. JSON list of
    # {"description","sql"} with catalog-qualified, self-contained SQL.
    "vgi.executable_examples": json.dumps(
        [
            {
                "description": "Simplify a Pythagorean trig identity to 1.",
                "sql": "SELECT sympy.main.simplify('sin(x)**2 + cos(x)**2')",
            },
            {
                "description": "Factor a difference of squares.",
                "sql": "SELECT sympy.main.factor('x**2 - 1')",
            },
            {
                "description": "Differentiate x^3 with respect to x.",
                "sql": "SELECT sympy.main.differentiate('x**3', 'x')",
            },
            {
                "description": "Substitute x=3, y=1 and evaluate to a DOUBLE.",
                "sql": "SELECT sympy.main.evaluate('x**2 + y', '{\"x\":3,\"y\":1}')",
            },
        ]
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
