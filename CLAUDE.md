# CLAUDE.md — vgi-sympy

Contributor/agent notes. User-facing docs live in `README.md`; this is the
"how it's built and where the sharp edges are" companion.

## What this is

A [VGI](https://query.farm) worker that does **symbolic math (a small CAS)** —
simplify, expand, factor, differentiate, integrate, solve, evaluate, to_latex,
symbolic_equal — as DuckDB scalar functions. Backed by
[SymPy](https://www.sympy.org/) (BSD-3-Clause). `sympy_worker.py` assembles every
function into one `sympy` catalog (single `main` schema) over stdio. Sibling
style/tooling to `vgi-conform` and `vgi-calendar`.

## Layout

```
sympy_worker.py        repo-root stdio entry point; PEP 723 inline deps; main()
vgi_sympy/
  cas.py               pure CAS logic + the SAFE PARSER; no Arrow/VGI; unit-testable
  scalars.py           per-row Arrow scalar adapters over cas.py
tests/                 pytest: test_cas (pure, incl. safe-parsing), test_scalars (Client RPC)
test/sql/*.test        haybarn-unittest sqllogictest — authoritative E2E
Makefile               test / test-unit / test-sql / lint
```

To add a function: implement the logic in `cas.py` (pure, total — return `None`
for "invalid / not computable", raise `CASError` only where a clear error beats a
silent NULL), wrap it as a `ScalarFunction` in `scalars.py`, and register it in
both `scalars.SCALAR_FUNCTIONS` and (transitively) `sympy_worker.py`'s
`_FUNCTIONS`.

## SECURITY — the safe parser (read this FIRST, do not regress it)

Parsing an untrusted expression string is the whole risk surface. The rules:

- **NEVER use `sympy.sympify` or `eval`/`exec` on user input.** `sympify` falls
  back to `eval` and is trivially exploitable.
- **`parse_expr` alone is NOT safe.** It `eval`s its token stream against its
  namespaces. With the default `from sympy import *` global namespace,
  `().__class__.__bases__[0].__subclasses__()` *evaluates* and hands back Python
  internals — a real sandbox escape. Verified by hand during development.
- The defense is **two independent layers**, both in `cas.parse()`:
  1. **`_screen_tokens()` (primary).** stdlib `tokenize` over the raw string,
     rejecting anything that enables an escape: the `.` attribute-access op
     (the critical one — `2.5` is a NUMBER token, so decimals still work),
     `[ ] { } : ; = @ \ ->`, dunder names (`__class__`, `__import__`, …),
     `lambda`, and any string/f-string literal. Hostile gadgets never reach
     `eval`.
  2. **Restricted namespace (defense in depth).** allow-list `local_dict`
     (`_ALLOWED_NAMES`: safe constants + elementary/trig functions) and a
     `global_dict` that is `from sympy import *` **with `__builtins__` set to
     `{}`** — so even if a token slipped the screen, `eval`/`open`/`__import__`
     are not in scope. Any other bare name auto-becomes an inert `Symbol`.
- Plus: `MAX_EXPR_LEN` (raw length) and `MAX_NODES` (parsed-tree size) caps, and
  every public op is wrapped in `try/except` → `None` (or `CASError`).

If you touch `cas.parse`, `_screen_tokens`, `_ALLOWED_NAMES`, `_GLOBAL_DICT`, or
`_FORBIDDEN_OPS`, **re-run `tests/test_cas.py::TestSafeParsing` and
`test/sql/security.test`** and add a case for whatever you changed. The known
attack strings to keep failing: `__import__('os').system(...)`,
`().__class__.__bases__[0].__subclasses__()`, `lambda: 1`, `x.y`, `eval('1+1')`.

### Why `=` is allowed in `solve` but rejected elsewhere

The token screen forbids `=`. `solve('lhs = rhs', var)` works because `solve()`
**splits on the first `=` and parses each side independently** — neither side
ever contains `=` when it reaches `parse()`. Don't "fix" this by allowing `=`
through the screen.

## NULL / error conventions

- NULL or empty input → NULL output (adapters map element-wise, NULL passthrough).
- Invalid/unsafe/too-complex expression → **NULL** for the transforming scalars
  (`simplify`, `expand`, `factor`, `differentiate`, `integrate`, `to_latex`,
  `solve`, `symbolic_equal`) — it composes over messy columns, it is not an error.
- `evaluate` raises `CASError` (→ DuckDB error) only for a structurally wrong
  `vars_json` (not a JSON object / non-numeric value), since that's a caller
  mistake; it returns NULL for "free symbols remain" or non-real results.
- `integrate` returns NULL when no closed form is found (result still contains an
  `Integral`); it never returns a `+C`.

## Scalars are positional-only

The VGI SDK makes scalar functions **positional** (no `name := value`). All args
here (`expr`, `var`, `vars_json`) are plain string columns/constants passed
positionally. `solve` returns `LIST(VARCHAR)` and so needs an explicit
`Returns(arrow_type=pa.list_(pa.string()))`. `evaluate` returns `DOUBLE`
(`pa.float64()`), `symbolic_equal` returns `BOOLEAN`. `sympy_version` has no
natural argument, so it takes an ignored int "row driver" column to get a row
count (a scalar needs an input array to know how many rows to emit).

## Determinism (why the tests assert exact strings)

SymPy's `str()` output is canonical and stable, so the E2E `.test` files assert
exact forms (`'3*x**2'`, `'(x - 1)*(x + 1)'`). `solve` results are **sorted by
string** for order-independence; in SQL use `UNNEST(...) ... rowsort`. Where a
form isn't worth pinning, use `symbolic_equal`.

## Dev loop

```bash
uv sync --extra dev
uv run --no-sync pytest -q                 # unit + scalar (subprocess) tests
make test-sql                              # E2E via haybarn-unittest (sets VGI_SYMPY_WORKER)
uv run --no-sync ruff check . && uv run --no-sync ruff format --check .
uv run --no-sync mypy vgi_sympy/
```

`make test-sql` runs the worker as a `uv` stdio subprocess — exactly how DuckDB
drives it after `ATTACH 'sympy' (TYPE vgi, LOCATION '${VGI_SYMPY_WORKER}')`.
SymPy is imported once at module load (expensive import); keep it that way.

## Licensing

This repo: **MIT** (`LICENSE`). SymPy is **BSD-3-Clause** (permissive, no
copyleft concern). `vgi-python` is licensed separately by Query Farm and is a
local path dependency in dev (`[tool.uv.sources]`).
