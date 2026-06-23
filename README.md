<p align="center">
  <img src="https://raw.githubusercontent.com/Query-farm/vgi/main/docs/vgi-logo.png" alt="Vector Gateway Interface (VGI)" width="320">
</p>

<p align="center"><em>A <a href="https://query.farm">Query.Farm</a> VGI worker for DuckDB.</em></p>

# vgi-sympy

[![CI](https://github.com/Query-farm/vgi-sympy/actions/workflows/ci.yml/badge.svg)](https://github.com/Query-farm/vgi-sympy/actions/workflows/ci.yml)

A [VGI](https://query.farm) worker that brings **symbolic mathematics** — a
small computer-algebra system (CAS) — into DuckDB/SQL. Simplify, expand, factor,
differentiate, integrate, solve, evaluate, render to LaTeX, and test symbolic
equality, all as plain SQL scalar functions, backed by
[SymPy](https://www.sympy.org/) (BSD-3-Clause).

```sql
INSTALL vgi FROM community; LOAD vgi;
ATTACH 'sympy' (TYPE vgi, LOCATION 'uv run sympy_worker.py');

SELECT sympy.simplify('sin(x)**2 + cos(x)**2');      -- '1'
SELECT sympy.expand('(x + 1)**2');                   -- 'x**2 + 2*x + 1'
SELECT sympy.factor('x**2 - 1');                     -- '(x - 1)*(x + 1)'
SELECT sympy.differentiate('x**3', 'x');             -- '3*x**2'
SELECT sympy.integrate('2*x', 'x');                  -- 'x**2'
SELECT sympy.solve('x**2 - 4', 'x');                 -- ['-2', '2']
SELECT UNNEST(sympy.solve('2*x = 10', 'x'));         -- 5
SELECT sympy.evaluate('x**2 + y', '{"x":3,"y":1}');  -- 10.0
SELECT sympy.to_latex('x**2');                       -- 'x^{2}'
SELECT sympy.symbolic_equal('2*(x+1)', '2*x+2');     -- true
SELECT sympy.sympy_version();                        -- e.g. '1.13.3'
```

Everything runs **offline and deterministically** — there is no network access,
and SymPy's canonical string output is stable, so the same input always gives
the same answer. That determinism is what makes the functions testable from SQL
(assert canonical forms, or use `symbolic_equal`).

## Safe parsing — how user expressions are handled (read this)

Turning an **untrusted string** into a symbolic expression is the dangerous part
of any CAS-over-SQL bridge. SymPy's `sympify` (and Python's `eval`) can be
coerced into **executing arbitrary code** via attribute tricks like
`().__class__.__subclasses__()`, lambdas, or `__import__('os').system(...)`.

**This worker never uses `sympify` or `eval`.** Every expression string is
parsed through a hardened `sympy.parsing.sympy_parser.parse_expr` configuration
(see [`vgi_sympy/cas.py`](vgi_sympy/cas.py)):

- **Allow-list `local_dict`.** Only an explicit set of safe math names
  (`sin`, `cos`, `sqrt`, `exp`, `log`, `pi`, `E`, …) is in scope. Any *other*
  bare name becomes an inert SymPy `Symbol` — it is treated as a variable, never
  resolved to a Python callable.
- **Empty `global_dict={}`.** Python builtins (`eval`, `__import__`, `open`,
  `exec`, …) are **not** in scope, so they can never be invoked.
- **Default, side-effect-free transformations only** (`standard_transformations`);
  no implicit-multiplication or lambda/eval transformations are enabled.
- **Size and complexity bounds.** The raw string is capped at `MAX_EXPR_LEN`
  (2000 chars) and the parsed tree at `MAX_NODES` (5000 nodes) to prevent
  blow-ups before any expensive CAS work runs.
- **Total error handling.** Every operation wraps parse + compute in
  `try/except`. A malformed, hostile, or too-complex expression yields **NULL**
  (for the transforming functions) or a **clear error** (for `evaluate` with bad
  JSON) — **never code execution**.

So `simplify('__import__(''os'').system(''rm -rf /'')')` returns NULL (the name
parses to an inert symbol that is never called), and
`().__class__.__bases__[0].__subclasses__()` is rejected outright. This is
covered by unit tests (`tests/test_cas.py::TestSafeParsing`) and an
end-to-end SQL test (`test/sql/security.test`).

## Functions

All expression and variable arguments are `VARCHAR`. Functions are **scalars**:
one row in, one value out, usable inline in any projection or predicate.

| Function | Signature | Returns | NULL / error behavior |
|---|---|---|---|
| `simplify` | `simplify(expr)` | `VARCHAR` | NULL if input NULL, invalid, unsafe, or too complex |
| `expand` | `expand(expr)` | `VARCHAR` | NULL if input NULL/invalid |
| `factor` | `factor(expr)` | `VARCHAR` | NULL if input NULL/invalid |
| `differentiate` | `differentiate(expr, var)` | `VARCHAR` | NULL if either arg NULL, or invalid |
| `integrate` | `integrate(expr, var)` | `VARCHAR` | NULL if invalid **or no closed form** is found (no `+C`) |
| `solve` | `solve(equation, var)` | `VARCHAR[]` | NULL if invalid; **empty list** if no solutions. Parses `'lhs = rhs'` or a bare expr assumed `= 0` |
| `evaluate` | `evaluate(expr, vars_json)` | `DOUBLE` | NULL if free symbols remain or result is non-real; **error** if `vars_json` is not a numeric JSON object |
| `to_latex` | `to_latex(expr)` | `VARCHAR` | NULL if input NULL/invalid |
| `symbolic_equal` | `symbolic_equal(a, b)` | `BOOLEAN` | NULL if either side invalid; else true/false |
| `sympy_version` | `sympy_version(n)` | `VARCHAR` | the backing SymPy version (`n` is a row driver) |

Notes:

- **`solve`** returns `VARCHAR[]` (a `LIST(VARCHAR)`). Solutions are sorted by
  their canonical string form for determinism. Use `UNNEST(...)` to get one row
  per solution.
- **`evaluate`** substitutes a JSON object of numeric values and evaluates to a
  float. Anything left symbolic, or a complex/infinite result, yields NULL.
  A `vars_json` that is not a JSON object, or that contains a non-numeric value,
  is a clear DuckDB error (it usually signals a caller mistake).
- **`integrate`** returns the indefinite integral with no constant of
  integration, and NULL when SymPy cannot find a closed form.

## Scalars take positional arguments

VGI/DuckDB **scalar** functions take positional arguments only (the `name :=
value` syntax is a table-function/macro feature). The `var` and `vars_json`
arguments here are ordinary string columns or constants passed positionally.

## Layout

```
sympy_worker.py          # PEP 723 entry point; assembles the `sympy` catalog
vgi_sympy/
  __init__.py
  cas.py                 # pure CAS logic + the safe parser (no Arrow/VGI deps)
  scalars.py             # per-row Arrow scalar adapters over cas.py
tests/
  test_cas.py            # pure-logic unit tests, incl. safe-parsing tests
  test_scalars.py        # scalars via vgi.client.Client (subprocess worker)
test/sql/
  cas.test               # E2E: simplify/calculus/solve/evaluate/equality
  security.test          # E2E: hostile expressions rejected, not executed
```

`cas.py` is pure and importable — no Arrow, no VGI — so it is directly
unit-testable and reused by the thin Arrow adapters in `scalars.py`. SymPy is
imported once at module load (it is an expensive import).

## Development

```bash
uv sync --extra dev

uv run --no-sync pytest -q                 # unit + scalar (subprocess) tests
make test-sql                              # end-to-end SQL via haybarn-unittest
uv run --no-sync ruff check .              # lint
uv run --no-sync mypy vgi_sympy/           # type check
```

`make test-sql` is self-contained: it points `VGI_SYMPY_WORKER` at the worker
run as a `uv` stdio subprocess (exactly how DuckDB drives it after `ATTACH`) and
runs the `test/sql/*.test` files via
[`haybarn-unittest`](https://github.com/Query-farm-haybarn/haybarn)
(`uv tool install haybarn-unittest`).

## Requirements

- Python ≥ 3.13
- [SymPy](https://www.sympy.org/) (BSD-3-Clause), pyarrow, `vgi-python`
- A DuckDB-compatible engine — [Haybarn](https://github.com/Query-farm-haybarn/haybarn)
  (`uvx haybarn-cli`) or stock DuckDB (`INSTALL vgi FROM community; LOAD vgi;`).

## License

MIT — see [LICENSE](LICENSE). SymPy is BSD-3-Clause; `vgi-python` is licensed
separately by Query Farm.

---

## Authorship & License

Written by [Query.Farm](https://query.farm).

Copyright 2026 Query Farm LLC - https://query.farm

