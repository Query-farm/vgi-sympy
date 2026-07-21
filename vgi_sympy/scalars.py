"""Per-row scalar symbolic-math functions.

Every function here is a true DuckDB **scalar** -- one value (per row) in, one
value out -- mapping a thin Arrow wrapper over the pure logic in
:mod:`vgi_sympy.cas`. They can be used inline in any projection or predicate::

    SELECT sympy.simplify(expr)                FROM formulas;
    SELECT sympy.differentiate(expr, 'x')      FROM formulas;
    SELECT UNNEST(sympy.solve('x**2 - 4', 'x'));
    SELECT sympy.evaluate('x**2 + y', '{"x":3,"y":1}');

Argument syntax
---------------
VGI / DuckDB *scalar* functions take **positional** arguments and resolve
overloads by *arity* (the ``name := value`` named-argument syntax is a property
of table functions and macros, not scalars). The ``var`` / ``vars_json``
arguments here travel as ordinary string columns/constants.

NULL semantics
--------------
A NULL input row yields NULL output, everywhere. An invalid, unsafe, or
too-complex expression also yields NULL (it is *not* an error) for the
transforming functions, so they compose cleanly over messy columns. The
deliberate exception is the safe-parser: a syntactically hostile string is
*rejected* (returns NULL), never executed. ``sympy_version(n)`` takes an
ignored row-driver argument and always returns the version string.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated

import pyarrow as pa
from vgi.arguments import Param, Returns
from vgi.metadata import FunctionExample
from vgi.scalar_function import ScalarFunction

from . import cas

# ---------------------------------------------------------------------------
# Small mapping helpers: apply a pure function across an array, NULL -> NULL.
# ---------------------------------------------------------------------------


def _map_str(arr: pa.StringArray, fn: Callable[[str], str | None]) -> pa.StringArray:
    out = [None if x is None else fn(x) for x in arr.to_pylist()]
    return pa.array(out, type=pa.string())


def _map_str2(a: pa.StringArray, b: pa.StringArray, fn: Callable[[str, str], str | None]) -> pa.StringArray:
    xs, ys = a.to_pylist(), b.to_pylist()
    out = [None if x is None or y is None else fn(x, y) for x, y in zip(xs, ys, strict=True)]
    return pa.array(out, type=pa.string())


def _map_bool2(a: pa.StringArray, b: pa.StringArray, fn: Callable[[str, str], bool | None]) -> pa.BooleanArray:
    xs, ys = a.to_pylist(), b.to_pylist()
    out = [None if x is None or y is None else fn(x, y) for x, y in zip(xs, ys, strict=True)]
    return pa.array(out, type=pa.bool_())


def _map_double2(a: pa.StringArray, b: pa.StringArray, fn: Callable[[str, str], float | None]) -> pa.DoubleArray:
    xs, ys = a.to_pylist(), b.to_pylist()
    out = [None if x is None or y is None else fn(x, y) for x, y in zip(xs, ys, strict=True)]
    return pa.array(out, type=pa.float64())


def _map_list_str(arr: pa.StringArray, b: pa.StringArray, fn: Callable[[str, str], list[str] | None]) -> pa.ListArray:
    xs, ys = arr.to_pylist(), b.to_pylist()
    out = [None if x is None or y is None else fn(x, y) for x, y in zip(xs, ys, strict=True)]
    return pa.array(out, type=pa.list_(pa.string()))


# ===========================================================================
# Single-expression transforms -> VARCHAR.
# ===========================================================================


class SimplifyFunction(ScalarFunction):
    """``simplify(expr)`` -- simplified canonical form, or NULL if invalid."""

    class Meta:
        """VGI function metadata (name, description, categories, examples)."""

        name = "simplify"
        description = "Algebraically simplified form of an expression, or NULL if invalid/unsafe"
        categories = ["sympy", "cas"]
        tags = {
            "vgi.title": "Simplify Symbolic Expression",
            "vgi.category": "transforms",
            "vgi.keywords": json.dumps(
                ["simplify", "reduce", "canonical form", "normalize", "sympy", "cas", "algebra", "trig identity"]
            ),
            "vgi.doc_llm": (
                "## simplify(expr)\n\n"
                "Apply SymPy's general-purpose algebraic **simplification** to a single expression "
                "string and return a canonical, simplified form as `VARCHAR`.\n\n"
                "Use it to collapse trig identities (`sin(x)**2 + cos(x)**2` -> `1`), cancel common "
                "factors, and normalize equivalent forms to one representation. The result is SymPy's "
                "stable canonical string, so it is safe to compare or store.\n\n"
                "**Input:** one expression string. **Output:** simplified string, or `NULL` when the "
                "input is `NULL`, invalid, unsafe, or too complex — so it composes over messy columns."
            ),
            "vgi.doc_md": (
                "# simplify\n\n"
                "Algebraically simplifies an expression to a canonical form.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT sympy.simplify('sin(x)**2 + cos(x)**2');  -- '1'\n"
                "SELECT sympy.simplify('(x**2 - 1)/(x - 1)');     -- 'x + 1'\n"
                "```\n\n"
                "## Notes\n\n"
                "Returns `NULL` for `NULL`, invalid, or unsafe input. Simplification is heuristic: it "
                "aims for a simpler form, not a guaranteed minimal one."
            ),
            # VGI515: described examples (the native Meta.examples column drops
            # descriptions, so the human-readable text is carried on this tag).
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "Simplify a Pythagorean trig identity to 1.",
                        "sql": "SELECT sympy.main.simplify('sin(x)**2 + cos(x)**2')",
                    },
                    {
                        "description": "Cancel a common factor from a rational expression.",
                        "sql": "SELECT sympy.main.simplify('(x**2 - 1)/(x - 1)')",
                    },
                ]
            ),
        }
        examples = [
            FunctionExample(
                sql="SELECT sympy.main.simplify('sin(x)**2 + cos(x)**2')",
                description="Simplify a trig identity to 1",
            ),
        ]

    @classmethod
    def compute(
        cls, expr: Annotated[pa.StringArray, Param(doc="Expression to simplify.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map the pure CAS function over the Arrow input array(s)."""
        return _map_str(expr, cas.simplify)


class ExpandFunction(ScalarFunction):
    """``expand(expr)`` -- algebraically expanded form, or NULL if invalid."""

    class Meta:
        """VGI function metadata (name, description, categories, examples)."""

        name = "expand"
        description = "Algebraically expanded form of an expression, or NULL if invalid/unsafe"
        categories = ["sympy", "cas"]
        tags = {
            "vgi.title": "Expand Symbolic Expression",
            "vgi.category": "transforms",
            "vgi.keywords": json.dumps(
                ["expand", "multiply out", "distribute", "binomial", "polynomial", "foil", "sympy", "cas", "algebra"]
            ),
            "vgi.doc_llm": (
                "## expand(expr)\n\n"
                "Algebraically **expand** an expression — multiply out products and powers — and "
                "return the expanded polynomial form as `VARCHAR`.\n\n"
                "It is the inverse direction of `factor`: `(x + 1)**2` becomes `x**2 + 2*x + 1`. Use it "
                "to flatten nested products before pattern matching, term counting, or comparison.\n\n"
                "**Input:** one expression string. **Output:** expanded string, or `NULL` for `NULL`, "
                "invalid, or unsafe input."
            ),
            "vgi.doc_md": (
                "# expand\n\n"
                "Multiplies out products and powers into a flat polynomial form.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT sympy.expand('(x + 1)**2');     -- 'x**2 + 2*x + 1'\n"
                "SELECT sympy.expand('(x + y)*(x - y)'); -- 'x**2 - y**2'\n"
                "```\n\n"
                "## Notes\n\n"
                "The opposite of `factor`. Returns `NULL` for `NULL`/invalid/unsafe input."
            ),
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "Expand a squared binomial into a flat polynomial.",
                        "sql": "SELECT sympy.main.expand('(x + 1)**2')",
                    },
                    {
                        "description": "Expand a product of conjugates to a difference of squares.",
                        "sql": "SELECT sympy.main.expand('(x + y)*(x - y)')",
                    },
                ]
            ),
        }
        examples = [
            FunctionExample(
                sql="SELECT sympy.main.expand('(x + 1)**2')",
                description="Expand a binomial",
            ),
        ]

    @classmethod
    def compute(
        cls, expr: Annotated[pa.StringArray, Param(doc="Expression to expand.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map the pure CAS function over the Arrow input array(s)."""
        return _map_str(expr, cas.expand)


class FactorFunction(ScalarFunction):
    """``factor(expr)`` -- factored form, or NULL if invalid."""

    class Meta:
        """VGI function metadata (name, description, categories, examples)."""

        name = "factor"
        description = "Factored form of an expression, e.g. '(x - 1)*(x + 1)', or NULL if invalid"
        categories = ["sympy", "cas"]
        tags = {
            "vgi.title": "Factor Symbolic Expression",
            "vgi.category": "transforms",
            "vgi.keywords": json.dumps(
                ["factor", "factorize", "factorise", "roots", "divisors", "polynomial", "sympy", "cas", "algebra"]
            ),
            "vgi.doc_llm": (
                "## factor(expr)\n\n"
                "**Factor** an expression into a product of irreducible factors over the rationals and "
                "return that form as `VARCHAR`.\n\n"
                "It is the inverse direction of `expand`: `x**2 - 1` becomes `(x - 1)*(x + 1)`. Use it "
                "to reveal roots, find common factors, or rewrite a polynomial as a product before "
                "cancellation.\n\n"
                "**Input:** one expression string. **Output:** factored string, or `NULL` for `NULL`, "
                "invalid, or unsafe input. Expressions with no nontrivial factorization come back "
                "unchanged."
            ),
            "vgi.doc_md": (
                "# factor\n\n"
                "Factors an expression into a product of irreducible factors.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT sympy.factor('x**2 - 1');         -- '(x - 1)*(x + 1)'\n"
                "SELECT sympy.factor('x**2 + 2*x + 1');   -- '(x + 1)**2'\n"
                "```\n\n"
                "## Notes\n\n"
                "The opposite of `expand`. Already-irreducible inputs return unchanged; "
                "`NULL`/invalid/unsafe input returns `NULL`."
            ),
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "Factor a difference of squares into a product.",
                        "sql": "SELECT sympy.main.factor('x**2 - 1')",
                    },
                    {
                        "description": "Factor a perfect-square trinomial.",
                        "sql": "SELECT sympy.main.factor('x**2 + 2*x + 1')",
                    },
                ]
            ),
        }
        examples = [
            FunctionExample(
                sql="SELECT sympy.main.factor('x**2 - 1')",
                description="Factor a difference of squares",
            ),
        ]

    @classmethod
    def compute(
        cls, expr: Annotated[pa.StringArray, Param(doc="Expression to factor.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map the pure CAS function over the Arrow input array(s)."""
        return _map_str(expr, cas.factor)


class ToLatexFunction(ScalarFunction):
    """``to_latex(expr)`` -- LaTeX rendering, or NULL if invalid."""

    class Meta:
        """VGI function metadata (name, description, categories, examples)."""

        name = "to_latex"
        description = "LaTeX rendering of an expression, or NULL if invalid/unsafe"
        categories = ["sympy", "cas"]
        tags = {
            "vgi.title": "Render Expression To LaTeX",
            "vgi.category": "transforms",
            "vgi.keywords": json.dumps(
                ["latex", "tex", "render", "typeset", "mathjax", "format", "pretty print", "sympy", "cas"]
            ),
            "vgi.doc_llm": (
                "## to_latex(expr)\n\n"
                "Render an expression as a **LaTeX** string (`VARCHAR`) suitable for typesetting in "
                "docs, MathJax/KaTeX, or PDF reports.\n\n"
                "For example `'x**2'` becomes `'x^{2}'` and `'sqrt(x)'` becomes `'\\sqrt{x}'`. The "
                "expression is parsed and simplified to SymPy's internal form first, then pretty-"
                "printed as LaTeX.\n\n"
                "**Input:** one expression string. **Output:** LaTeX markup string, or `NULL` for "
                "`NULL`, invalid, or unsafe input."
            ),
            "vgi.doc_md": (
                "# to_latex\n\n"
                "Renders an expression as LaTeX markup for typesetting.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT sympy.to_latex('x**2');    -- 'x^{2}'\n"
                "SELECT sympy.to_latex('sqrt(x)'); -- '\\\\sqrt{x}'\n"
                "```\n\n"
                "## Notes\n\n"
                "Output is raw LaTeX (no surrounding `$...$`). Returns `NULL` for `NULL`/invalid/"
                "unsafe input."
            ),
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "Render x squared as LaTeX markup.",
                        "sql": "SELECT sympy.main.to_latex('x**2')",
                    },
                    {
                        "description": "Render a square root as LaTeX markup.",
                        "sql": "SELECT sympy.main.to_latex('sqrt(x)')",
                    },
                ]
            ),
        }
        examples = [
            FunctionExample(
                sql="SELECT sympy.main.to_latex('x**2')",
                description="Render x squared as LaTeX",
            ),
        ]

    @classmethod
    def compute(
        cls, expr: Annotated[pa.StringArray, Param(doc="Expression to render.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map the pure CAS function over the Arrow input array(s)."""
        return _map_str(expr, cas.to_latex)


# ===========================================================================
# Calculus: (expr, var) -> VARCHAR.
# ===========================================================================


class DifferentiateFunction(ScalarFunction):
    """``differentiate(expr, var)`` -- derivative w.r.t. ``var``, or NULL."""

    class Meta:
        """VGI function metadata (name, description, categories, examples)."""

        name = "differentiate"
        description = "Derivative of an expression with respect to a variable, or NULL if invalid"
        categories = ["sympy", "cas", "calculus"]
        tags = {
            "vgi.title": "Differentiate Expression By Variable",
            "vgi.category": "calculus",
            "vgi.keywords": json.dumps(
                [
                    "differentiate",
                    "derivative",
                    "calculus",
                    "gradient",
                    "slope",
                    "rate of change",
                    "diff",
                    "sympy",
                    "cas",
                ]
            ),
            "vgi.doc_llm": (
                "## differentiate(expr, var)\n\n"
                "Compute the symbolic **derivative** of an expression with respect to a named "
                "variable and return it as `VARCHAR`.\n\n"
                "For example `differentiate('x**3', 'x')` returns `'3*x**2'`. The second argument names "
                "the variable to differentiate by; other symbols are treated as constants.\n\n"
                "**Inputs:** an expression string and a variable name (both positional). **Output:** "
                "the derivative as a SymPy-canonical string, or `NULL` if either input is `NULL`, "
                "invalid, or unsafe."
            ),
            "vgi.doc_md": (
                "# differentiate\n\n"
                "Symbolic differentiation with respect to a variable.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT sympy.differentiate('x**3', 'x');     -- '3*x**2'\n"
                "SELECT sympy.differentiate('sin(x)', 'x');   -- 'cos(x)'\n"
                "```\n\n"
                "## Notes\n\n"
                "Variables other than `var` are held constant. Returns `NULL` for `NULL`/invalid/"
                "unsafe input."
            ),
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "Differentiate x**3 with respect to x.",
                        "sql": "SELECT sympy.main.differentiate('x**3', 'x')",
                    },
                    {
                        "description": "Differentiate sin(x) with respect to x.",
                        "sql": "SELECT sympy.main.differentiate('sin(x)', 'x')",
                    },
                ]
            ),
        }
        examples = [
            FunctionExample(
                sql="SELECT sympy.main.differentiate('x**3', 'x')",
                description="Differentiate x^3 -> 3*x**2",
            ),
        ]

    @classmethod
    def compute(
        cls,
        expr: Annotated[pa.StringArray, Param(doc="Expression to differentiate.")],
        var: Annotated[pa.StringArray, Param(doc="Variable name to differentiate by.")],
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map the pure CAS function over the Arrow input array(s)."""
        return _map_str2(expr, var, cas.differentiate)


class IntegrateFunction(ScalarFunction):
    """``integrate(expr, var)`` -- indefinite integral (no +C), or NULL."""

    class Meta:
        """VGI function metadata (name, description, categories, examples)."""

        name = "integrate"
        description = (
            "Indefinite integral of an expression w.r.t. a variable (no +C), "
            "or NULL if invalid or no closed form is found"
        )
        categories = ["sympy", "cas", "calculus"]
        tags = {
            "vgi.title": "Integrate Expression By Variable",
            "vgi.category": "calculus",
            "vgi.keywords": json.dumps(
                ["integrate", "integral", "antiderivative", "calculus", "area", "accumulate", "sympy", "cas"]
            ),
            "vgi.doc_llm": (
                "## integrate(expr, var)\n\n"
                "Compute the symbolic **indefinite integral** (antiderivative) of an expression with "
                "respect to a named variable and return it as `VARCHAR`. The constant of integration "
                "`+C` is **not** included.\n\n"
                "For example `integrate('2*x', 'x')` returns `'x**2'`. It is the inverse of "
                "`differentiate`.\n\n"
                "**Inputs:** an expression string and a variable name (both positional). **Output:** "
                "the antiderivative string, or `NULL` if either input is `NULL`/invalid/unsafe, or if "
                "no closed-form antiderivative exists (the result still contains an unresolved "
                "`Integral`)."
            ),
            "vgi.doc_md": (
                "# integrate\n\n"
                "Symbolic indefinite integration (antiderivative, no `+C`).\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT sympy.integrate('2*x', 'x');   -- 'x**2'\n"
                "SELECT sympy.integrate('cos(x)', 'x'); -- 'sin(x)'\n"
                "```\n\n"
                "## Notes\n\n"
                "The inverse of `differentiate`. Returns `NULL` when no closed form is found, or for "
                "`NULL`/invalid/unsafe input. No constant of integration is added."
            ),
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "Integrate 2*x with respect to x (no constant of integration).",
                        "sql": "SELECT sympy.main.integrate('2*x', 'x')",
                    },
                    {
                        "description": "Integrate cos(x) with respect to x.",
                        "sql": "SELECT sympy.main.integrate('cos(x)', 'x')",
                    },
                ]
            ),
        }
        examples = [
            FunctionExample(
                sql="SELECT sympy.main.integrate('2*x', 'x')",
                description="Integrate 2*x -> x**2",
            ),
        ]

    @classmethod
    def compute(
        cls,
        expr: Annotated[pa.StringArray, Param(doc="Expression to integrate.")],
        var: Annotated[pa.StringArray, Param(doc="Variable name to integrate by.")],
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map the pure CAS function over the Arrow input array(s)."""
        return _map_str2(expr, var, cas.integrate)


# ===========================================================================
# solve -> LIST(VARCHAR) (explicit list arrow type required).
# ===========================================================================


class SolveFunction(ScalarFunction):
    """``solve(equation, var)`` -- solutions for ``var`` as a VARCHAR[]."""

    class Meta:
        """VGI function metadata (name, description, categories, examples)."""

        name = "solve"
        description = (
            "Solve an equation for a variable, returning solutions as VARCHAR[]. "
            "Accepts 'lhs = rhs' or a bare expression assumed equal to zero. "
            "NULL if invalid; empty list if no solutions."
        )
        categories = ["sympy", "cas", "solve"]
        tags = {
            "vgi.title": "Solve Equation For Variable",
            "vgi.category": "equations",
            "vgi.keywords": json.dumps(
                ["solve", "equation", "roots", "zeros", "solver", "algebra", "unknown", "sympy", "cas"]
            ),
            "vgi.doc_llm": (
                "## solve(equation, var)\n\n"
                "**Solve** an equation for a variable and return all solutions as a `VARCHAR[]` "
                "(list of expression strings).\n\n"
                "The first argument is either `'lhs = rhs'` (the single `=` is split before parsing) "
                "or a bare expression assumed equal to zero. The second argument names the variable to "
                "solve for. Results are **sorted by string** for order-independence — in SQL use "
                "`UNNEST(...)` to fan them into rows.\n\n"
                "**Output:** a list of solution strings; an **empty list** when there are no "
                "solutions, or `NULL` when either input is `NULL`/invalid/unsafe."
            ),
            "vgi.doc_md": (
                "# solve\n\n"
                "Solves an equation for a variable, returning a `VARCHAR[]` of solutions.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT sympy.solve('x**2 - 4', 'x');      -- ['-2', '2']\n"
                "SELECT UNNEST(sympy.solve('2*x = 10', 'x')); -- 5\n"
                "```\n\n"
                "## Notes\n\n"
                "Accepts `'lhs = rhs'` or a bare expression (assumed `= 0`). Solutions are sorted by "
                "string. Empty list = no solutions; `NULL` = invalid/unsafe input."
            ),
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "Solve a quadratic for x, returning a VARCHAR[] of roots.",
                        "sql": "SELECT sympy.main.solve('x**2 - 4', 'x')",
                    },
                    {
                        "description": "Solve a linear 'lhs = rhs' equation and unnest the solution rows.",
                        "sql": "SELECT UNNEST(sympy.main.solve('2*x = 10', 'x'))",
                    },
                ]
            ),
        }
        examples = [
            FunctionExample(
                sql="SELECT sympy.main.solve('x**2 - 4', 'x')",
                description="Solve x^2 - 4 = 0 -> ['-2', '2']",
            ),
            FunctionExample(
                sql="SELECT UNNEST(sympy.main.solve('2*x = 10', 'x'))",
                description="Unnest the solution rows",
            ),
        ]

    @classmethod
    def compute(
        cls,
        equation: Annotated[pa.StringArray, Param(doc="Equation or expression to solve.")],
        var: Annotated[pa.StringArray, Param(doc="Variable name to solve for.")],
    ) -> Annotated[pa.ListArray, Returns(arrow_type=pa.list_(pa.string()))]:
        """Map the pure CAS function over the Arrow input array(s)."""
        return _map_list_str(equation, var, cas.solve)


# ===========================================================================
# evaluate -> DOUBLE.
# ===========================================================================


class EvaluateFunction(ScalarFunction):
    """``evaluate(expr, vars_json)`` -- numeric value of ``expr`` as DOUBLE."""

    class Meta:
        """VGI function metadata (name, description, categories, examples)."""

        name = "evaluate"
        description = (
            'Substitute numeric values from a JSON object like \'{"x":2,"y":3}\' '
            "and evaluate to a DOUBLE. NULL if invalid, non-numeric, or free "
            "symbols remain."
        )
        categories = ["sympy", "cas", "evaluate"]
        tags = {
            "vgi.title": "Evaluate Expression Numerically",
            "vgi.category": "numeric",
            "vgi.keywords": json.dumps(
                ["evaluate", "eval", "substitute", "numeric", "compute", "plug in", "value", "double", "sympy", "cas"]
            ),
            "vgi.doc_llm": (
                "## evaluate(expr, vars_json)\n\n"
                "Substitute numeric values into an expression and **evaluate** it to a `DOUBLE`.\n\n"
                "The second argument is a JSON object mapping variable names to numbers, e.g. "
                '`\'{"x":3,"y":1}\'`. After substitution `evaluate('
                "'x**2 + y', '{\"x\":3,\"y\":1}')` returns `10.0`.\n\n"
                "**Output:** a `DOUBLE`. Returns `NULL` when free symbols remain after substitution or "
                "the result is non-real. Unlike the transforms, it **raises an error** when "
                "`vars_json` is structurally wrong (not a JSON object, or a non-numeric value), since "
                "that is a caller mistake rather than dirty data."
            ),
            "vgi.doc_md": (
                "# evaluate\n\n"
                "Substitutes numeric values from a JSON object and evaluates to a `DOUBLE`.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT sympy.evaluate('x**2 + y', '{\"x\":3,\"y\":1}'); -- 10.0\n"
                "SELECT sympy.evaluate('2*pi', '{}');                  -- 6.283...\n"
                "```\n\n"
                "## Notes\n\n"
                "`NULL` if free symbols remain or the result isn't real. **Errors** (not NULL) when "
                "`vars_json` is not a JSON object of numbers."
            ),
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "Substitute x=3, y=1 into an expression and evaluate to a DOUBLE.",
                        "sql": "SELECT sympy.main.evaluate('x**2 + y', '{\"x\":3,\"y\":1}')",
                    },
                    {
                        "description": "Evaluate a constant expression (2*pi) with no variables.",
                        "sql": "SELECT sympy.main.evaluate('2*pi', '{}')",
                    },
                ]
            ),
        }
        examples = [
            FunctionExample(
                sql="SELECT sympy.main.evaluate('x**2 + y', '{\"x\":3,\"y\":1}')",
                description="Substitute x=3, y=1 -> 10.0",
            ),
        ]

    @classmethod
    def compute(
        cls,
        expr: Annotated[pa.StringArray, Param(doc="Expression to evaluate.")],
        vars_json: Annotated[pa.StringArray, Param(doc='JSON object of variable values, e.g. {"x":2}.')],
    ) -> Annotated[pa.DoubleArray, Returns()]:
        """Map the pure CAS function over the Arrow input array(s)."""
        return _map_double2(expr, vars_json, cas.evaluate)


# ===========================================================================
# symbolic_equal -> BOOLEAN.
# ===========================================================================


class SymbolicEqualFunction(ScalarFunction):
    """``symbolic_equal(a, b)`` -- True if symbolically equivalent."""

    class Meta:
        """VGI function metadata (name, description, categories, examples)."""

        name = "symbolic_equal"
        description = (
            "True if two expressions are symbolically equivalent (simplify(a-b)==0), or NULL if either is invalid"
        )
        categories = ["sympy", "cas"]
        tags = {
            "vgi.title": "Test Symbolic Equality",
            "vgi.category": "equations",
            "vgi.keywords": json.dumps(
                ["symbolic equal", "equivalent", "equality", "compare", "identity", "same", "sympy", "cas", "algebra"]
            ),
            "vgi.doc_llm": (
                "## symbolic_equal(a, b)\n\n"
                "Test whether two expressions are **symbolically equivalent** and return a `BOOLEAN`.\n\n"
                "Equivalence is decided by simplifying the difference: `a` and `b` are equal when "
                "`simplify(a - b) == 0`. This catches forms that are textually different but "
                "mathematically the same, e.g. `'2*(x+1)'` and `'2*x+2'` are equal.\n\n"
                "**Inputs:** two expression strings (positional). **Output:** `TRUE`/`FALSE`, or "
                "`NULL` when either input is `NULL`/invalid/unsafe. Use it instead of string equality "
                "to compare expressions whose canonical form you don't want to pin."
            ),
            "vgi.doc_md": (
                "# symbolic_equal\n\n"
                "Returns `TRUE` when two expressions are mathematically equivalent.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT sympy.symbolic_equal('2*(x+1)', '2*x+2'); -- true\n"
                "SELECT sympy.symbolic_equal('sin(x)', 'cos(x)'); -- false\n"
                "```\n\n"
                "## Notes\n\n"
                "Compares via `simplify(a - b) == 0`, so different-looking but equal forms match. "
                "Returns `NULL` if either side is invalid/unsafe."
            ),
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "Prove two different-looking forms are equal (TRUE).",
                        "sql": "SELECT sympy.main.symbolic_equal('2*(x+1)', '2*x+2')",
                    },
                    {
                        "description": "Show two distinct functions are not equal (FALSE).",
                        "sql": "SELECT sympy.main.symbolic_equal('sin(x)', 'cos(x)')",
                    },
                ]
            ),
        }
        examples = [
            FunctionExample(
                sql="SELECT sympy.main.symbolic_equal('2*(x+1)', '2*x+2')",
                description="Prove two forms are equal -> true",
            ),
        ]

    @classmethod
    def compute(
        cls,
        a: Annotated[pa.StringArray, Param(doc="First expression.")],
        b: Annotated[pa.StringArray, Param(doc="Second expression.")],
    ) -> Annotated[pa.BooleanArray, Returns()]:
        """Map the pure CAS function over the Arrow input array(s)."""
        return _map_bool2(a, b, cas.symbolic_equal)


# ===========================================================================
# sympy_version -> VARCHAR (no argument).
# ===========================================================================


class SympyVersionFunction(ScalarFunction):
    """``sympy_version()`` -- the backing SymPy version string."""

    class Meta:
        """VGI function metadata (name, description, categories, examples)."""

        name = "sympy_version"
        description = "The SymPy version string backing this worker"
        categories = ["sympy"]
        tags = {
            "vgi.title": "Report Backing SymPy Version",
            "vgi.category": "diagnostics",
            "vgi.keywords": json.dumps(
                ["version", "sympy version", "build", "capability", "diagnostics", "about", "sympy", "cas"]
            ),
            "vgi.doc_llm": (
                "## sympy_version(row_driver)\n\n"
                "Report the **SymPy version string** that backs this worker (e.g. `'1.13.3'`), "
                "returned as `VARCHAR`.\n\n"
                "A scalar function needs an input column to know how many rows to emit, so this takes "
                "one ignored `BIGINT` *row driver* argument — pass any integer, such as "
                "`sympy_version(1)`. The value is ignored; the version is the same for every row.\n\n"
                "Use it for diagnostics, capability checks, or pinning expected output in tests."
            ),
            "vgi.doc_md": (
                "# sympy_version\n\n"
                "Reports the backing SymPy version string.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT sympy.sympy_version(1); -- e.g. '1.13.3'\n"
                "```\n\n"
                "## Notes\n\n"
                "Takes one ignored `BIGINT` row-driver argument (a scalar needs an input array to size "
                "its output). The argument value has no effect."
            ),
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "Report the backing SymPy version string.",
                        "sql": "SELECT sympy.main.sympy_version(1)",
                    },
                    {
                        "description": "Check that the backing SymPy version is present (non-empty).",
                        "sql": "SELECT length(sympy.main.sympy_version(1)) > 0",
                    },
                ]
            ),
        }
        examples = [
            FunctionExample(
                sql="SELECT sympy.main.sympy_version(1)",
                description="Report the SymPy version",
            ),
        ]

    @classmethod
    def compute(
        cls, n: Annotated[pa.Int64Array, Param(doc="Row driver (value ignored).")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map the pure CAS function over the Arrow input array(s)."""
        version = cas.sympy_version()
        return pa.array([None if x is None else version for x in n.to_pylist()], type=pa.string())


SCALAR_FUNCTIONS: list[type] = [
    SimplifyFunction,
    ExpandFunction,
    FactorFunction,
    ToLatexFunction,
    DifferentiateFunction,
    IntegrateFunction,
    SolveFunction,
    EvaluateFunction,
    SymbolicEqualFunction,
    SympyVersionFunction,
]
