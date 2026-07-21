# Copyright 2026 Query Farm LLC - https://query.farm

"""VGI worker exposing symbolic math (a small CAS) to SQL.

Assembles the scalar functions in ``vgi_sympy`` into a single ``sympy`` catalog
and runs the worker over stdio (DuckDB subprocess) or HTTP. It does computer
algebra -- simplify, expand, factor, differentiate, integrate, solve, evaluate,
to_latex, symbolic_equal -- as DuckDB scalar functions over SymPy.

Untrusted expression strings are parsed through a hardened allow-list parser
(``parse_expr`` with a restricted ``local_dict`` and empty ``global_dict``;
never ``sympify``/``eval``), so a malformed or hostile expression yields a clear
error or NULL, never code execution. See ``vgi_sympy/cas.py`` and the README.

This module is the importable home of the worker (``vgi_sympy.worker``): the
console script ``vgi-sympy-worker`` and the container's ``vgi-serve
vgi_sympy.worker:SympyWorker`` both target it, and the repo-root
``sympy_worker.py`` PEP 723 shim re-exports :class:`SympyWorker` and
:func:`main` so ``uv run sympy_worker.py`` keeps working unchanged.

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
    "# SymPy Symbolic Math (CAS) for DuckDB\n\n"
    "![SymPy logo](https://www.sympy.org/static/images/logo.png)\n\n"
    "**Do computer algebra in SQL** — simplify, expand, factor, differentiate, integrate, and solve "
    "symbolic expressions stored as text columns, powered by the "
    "[SymPy](https://www.sympy.org/) computer algebra system and exposed as DuckDB scalar functions.\n\n"
    "## What it does\n\n"
    "This VGI worker turns DuckDB into a symbolic calculator that works with *symbols*, not just "
    "numbers. Instead of shelling out to Python notebooks or a separate CAS, you can run algebra and "
    "calculus directly inside a query — manipulating formulas held in `VARCHAR` columns. It is built "
    "for data engineers, scientists, educators, and anyone who needs to normalize, transform, or "
    "verify mathematical expressions at scale alongside the rest of their SQL pipeline. Every function "
    "returns canonical, deterministic output that is stable across runs, so results are safe to "
    "materialize, diff, and join.\n\n"
    "## How it works\n\n"
    "The catalog wraps [SymPy](https://www.sympy.org/) — the pure-Python, BSD-licensed computer "
    "algebra library ([documentation](https://docs.sympy.org/latest/index.html), "
    "[source](https://github.com/sympy/sympy)) — behind a set of per-row Arrow scalar functions. "
    "Expression strings are never passed to `eval` or `sympify`: each one runs through a hardened "
    "allow-list parser (a `tokenize`-based screen plus a restricted namespace with empty "
    "`__builtins__`), so a malformed or hostile string is rejected or returns `NULL`, never executed. "
    "SymPy itself produces a canonical string form for results, which is why outputs are reproducible "
    "and worth pinning in tests.\n\n"
    "## When to use it\n\n"
    "Reach for this catalog whenever a value in your data is a *formula* rather than a number and you "
    "need to reason about it: canonicalize free-form formula columns so equivalent inputs collapse to "
    "one representation, grade student or model answers against a key, derive derivatives and "
    "antiderivatives for a scientific pipeline, solve equations row by row, or render expressions for "
    "display. Because every transform is a per-row scalar that yields `NULL` on invalid or unsafe "
    "input (rather than aborting the scan), it drops into an ordinary projection or predicate and "
    "composes over messy, semi-structured text without special-casing.\n\n"
    "```sql\n"
    "SELECT sympy.main.simplify('sin(x)**2 + cos(x)**2');  -- '1'\n"
    "SELECT sympy.main.differentiate('x**3', 'x');         -- '3*x**2'\n"
    "```\n\n"
    "## Notes\n\n"
    "Invalid or unsafe expressions yield `NULL` rather than erroring (except `evaluate`, which raises "
    "on a structurally wrong `vars_json`), so the transforms compose cleanly over messy columns. "
    "Parsing is sandboxed: hostile strings are rejected before any evaluation happens.\n"
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
    # VGI152/407/920: fixed analyst-task suite for `vgi-lint simulate`. Each task's
    # reference_sql is deterministic (SymPy emits canonical strings), so the suite
    # grades by result comparison. Prompts describe the goal in plain language; the
    # analyst discovers the functions by listing/describing the schema.
    "vgi.agent_test_tasks": json.dumps(
        [
            {
                "name": "simplify_trig_identity",
                "prompt": "Algebraically simplify the expression sin(x)**2 + cos(x)**2 to its simplest canonical form.",
                "reference_sql": "SELECT sympy.main.simplify('sin(x)**2 + cos(x)**2')",
                "ignore_column_names": True,
            },
            {
                "name": "expand_binomial",
                "prompt": "Expand the expression (x + 1)**2 by multiplying it out into a flat polynomial.",
                "reference_sql": "SELECT sympy.main.expand('(x + 1)**2')",
                "ignore_column_names": True,
            },
            {
                "name": "factor_difference_of_squares",
                "prompt": "Factor the polynomial x**2 - 1 into a product of irreducible factors.",
                "reference_sql": "SELECT sympy.main.factor('x**2 - 1')",
                "ignore_column_names": True,
            },
            {
                "name": "render_latex",
                "prompt": "Render the expression x**2 as a LaTeX markup string.",
                "reference_sql": "SELECT sympy.main.to_latex('x**2')",
                "ignore_column_names": True,
            },
            {
                "name": "differentiate_cubic",
                "prompt": "Compute the symbolic derivative of x**3 with respect to x.",
                "reference_sql": "SELECT sympy.main.differentiate('x**3', 'x')",
                "ignore_column_names": True,
            },
            {
                "name": "integrate_linear",
                "prompt": "Compute the indefinite integral (antiderivative, with no constant of "
                "integration) of 2*x with respect to x.",
                "reference_sql": "SELECT sympy.main.integrate('2*x', 'x')",
                "ignore_column_names": True,
            },
            {
                "name": "solve_quadratic",
                "prompt": "Solve the equation x**2 - 4 = 0 for x. Return all solutions as a single "
                "VARCHAR[] list value in one row (do not UNNEST them into separate rows).",
                "reference_sql": "SELECT sympy.main.solve('x**2 - 4', 'x')",
                "ignore_column_names": True,
            },
            {
                "name": "evaluate_substitution",
                "prompt": "Substitute x = 3 and y = 1 into the expression x**2 + y and evaluate it "
                "to a numeric (DOUBLE) value.",
                "reference_sql": "SELECT sympy.main.evaluate('x**2 + y', '{\"x\":3,\"y\":1}')",
                "ignore_column_names": True,
            },
            {
                "name": "symbolic_equality",
                "prompt": "Determine whether the expressions 2*(x+1) and 2*x+2 are symbolically "
                "equal, returning a boolean.",
                "reference_sql": "SELECT sympy.main.symbolic_equal('2*(x+1)', '2*x+2')",
                "ignore_column_names": True,
            },
            {
                "name": "backing_version_present",
                "prompt": "Using the worker, check whether its backing SymPy version is available. "
                "Return exactly one boolean value that is TRUE when the worker's reported SymPy "
                "version string is non-empty (its length is greater than zero). Return only that "
                "boolean, not the version string itself.",
                "reference_sql": "SELECT length(sympy.main.sympy_version(1)) > 0",
                "ignore_column_names": True,
            },
        ]
    ),
}

_SCHEMA_DOC_LLM = (
    "## Symbolic-math scalar functions (SymPy)\n\n"
    "The `main` schema groups every computer-algebra scalar in this worker, organized into algebraic "
    "transforms, calculus, equation solving, numeric evaluation, and diagnostics (see the schema's "
    "category registry to browse them).\n\n"
    "Each function takes expression strings (and, where relevant, a variable name or a JSON of "
    "variable values) and returns a SymPy-canonical string, a list of solutions, a number, or a "
    "boolean. The transforming functions return `NULL` for invalid or unsafe input so they can be "
    "applied across columns of free-form formulas without aborting a scan. Reach for this schema "
    "whenever you need algebra or calculus on symbolic expressions inside SQL — for example to "
    "canonicalize formula columns, grade answers against a key, or derive derivatives row by row."
)

_SCHEMA_DOC_MD = (
    "# main — symbolic math\n\n"
    "Computer-algebra scalar functions over [SymPy](https://www.sympy.org/).\n\n"
    "## Organization\n\n"
    "The functions fall into algebraic **transforms** (simplify, expand, factor, to_latex), "
    "**calculus** (differentiate, integrate), **equation** solving (solve, symbolic_equal), numeric "
    "**evaluation** (evaluate), and worker **diagnostics** (sympy_version), grouped by the schema's "
    "`vgi.categories` registry.\n\n"
    "## Usage\n\n"
    "Inputs are expression strings such as `'(x + 1)**2'`. Outputs are SymPy-canonical strings "
    "(stable across runs), a `VARCHAR[]` of solutions, a `DOUBLE`, or a `BOOLEAN`.\n\n"
    "## Notes\n\n"
    "Invalid/unsafe expressions become `NULL` (composes cleanly over messy columns); parsing is "
    "sandboxed and never evaluates hostile input.\n"
)

# VGI515: schema-level illustrative examples as a JSON list of {description, sql}
# so every example carries a human-readable description.
_EXAMPLE_QUERIES = json.dumps(
    [
        {
            "description": "Simplify a Pythagorean trig identity to 1.",
            "sql": "SELECT sympy.main.simplify('sin(x)**2 + cos(x)**2')",
        },
        {
            "description": "Expand a squared binomial into a flat polynomial.",
            "sql": "SELECT sympy.main.expand('(x + 1)**2')",
        },
        {
            "description": "Factor a difference of squares into a product.",
            "sql": "SELECT sympy.main.factor('x**2 - 1')",
        },
        {
            "description": "Differentiate x**3 with respect to x.",
            "sql": "SELECT sympy.main.differentiate('x**3', 'x')",
        },
        {
            "description": "Integrate 2*x with respect to x (no constant of integration).",
            "sql": "SELECT sympy.main.integrate('2*x', 'x')",
        },
        {
            "description": "Solve a quadratic equation for x, returning a VARCHAR[] of roots.",
            "sql": "SELECT sympy.main.solve('x**2 - 4', 'x')",
        },
        {
            "description": "Substitute x=3, y=1 into an expression and evaluate to a DOUBLE.",
            "sql": "SELECT sympy.main.evaluate('x**2 + y', '{\"x\":3,\"y\":1}')",
        },
        {
            "description": "Test that two different-looking expressions are symbolically equal.",
            "sql": "SELECT sympy.main.symbolic_equal('2*(x+1)', '2*x+2')",
        },
    ]
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
    # VGI413/408: ordered category registry for this schema. Each object carries a
    # matching `vgi.category` naming one of these.
    "vgi.categories": json.dumps(
        [
            {
                "name": "transforms",
                "title": "Algebraic transforms",
                "description": "Rewrite an expression into another algebraic form: simplify, expand, "
                "factor, and render to LaTeX.",
            },
            {
                "name": "calculus",
                "title": "Calculus",
                "description": "Differentiate or integrate an expression with respect to a variable.",
            },
            {
                "name": "equations",
                "title": "Equations & equivalence",
                "description": "Solve an equation for a variable, or test whether two expressions are "
                "symbolically equal.",
            },
            {
                "name": "numeric",
                "title": "Numeric evaluation",
                "description": "Substitute numeric values for variables and evaluate an expression to a number.",
            },
            {
                "name": "diagnostics",
                "title": "Diagnostics",
                "description": "Report worker capabilities, such as the backing SymPy version.",
            },
        ]
    ),
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
