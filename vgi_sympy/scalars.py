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
*rejected* (returns NULL), never executed. ``sympy_version()`` takes no
argument and always returns the version string.
"""

from __future__ import annotations

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


def _map_bool2(
    a: pa.StringArray, b: pa.StringArray, fn: Callable[[str, str], bool | None]
) -> pa.BooleanArray:
    xs, ys = a.to_pylist(), b.to_pylist()
    out = [None if x is None or y is None else fn(x, y) for x, y in zip(xs, ys, strict=True)]
    return pa.array(out, type=pa.bool_())


def _map_double2(
    a: pa.StringArray, b: pa.StringArray, fn: Callable[[str, str], float | None]
) -> pa.DoubleArray:
    xs, ys = a.to_pylist(), b.to_pylist()
    out = [None if x is None or y is None else fn(x, y) for x, y in zip(xs, ys, strict=True)]
    return pa.array(out, type=pa.float64())


def _map_list_str(
    arr: pa.StringArray, b: pa.StringArray, fn: Callable[[str, str], list[str] | None]
) -> pa.ListArray:
    xs, ys = arr.to_pylist(), b.to_pylist()
    out = [None if x is None or y is None else fn(x, y) for x, y in zip(xs, ys, strict=True)]
    return pa.array(out, type=pa.list_(pa.string()))


# ===========================================================================
# Single-expression transforms -> VARCHAR.
# ===========================================================================


class SimplifyFunction(ScalarFunction):
    """``simplify(expr)`` -- simplified canonical form, or NULL if invalid."""

    class Meta:
        name = "simplify"
        description = "Algebraically simplified form of an expression, or NULL if invalid/unsafe"
        categories = ["sympy", "cas"]
        examples = [
            FunctionExample(
                sql="SELECT sympy.simplify('sin(x)**2 + cos(x)**2')",
                description="Simplify a trig identity to 1",
            ),
        ]

    @classmethod
    def compute(
        cls, expr: Annotated[pa.StringArray, Param(doc="Expression to simplify.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        return _map_str(expr, cas.simplify)


class ExpandFunction(ScalarFunction):
    """``expand(expr)`` -- algebraically expanded form, or NULL if invalid."""

    class Meta:
        name = "expand"
        description = "Algebraically expanded form of an expression, or NULL if invalid/unsafe"
        categories = ["sympy", "cas"]
        examples = [
            FunctionExample(
                sql="SELECT sympy.expand('(x + 1)**2')",
                description="Expand a binomial",
            ),
        ]

    @classmethod
    def compute(
        cls, expr: Annotated[pa.StringArray, Param(doc="Expression to expand.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        return _map_str(expr, cas.expand)


class FactorFunction(ScalarFunction):
    """``factor(expr)`` -- factored form, or NULL if invalid."""

    class Meta:
        name = "factor"
        description = "Factored form of an expression, e.g. '(x - 1)*(x + 1)', or NULL if invalid"
        categories = ["sympy", "cas"]
        examples = [
            FunctionExample(
                sql="SELECT sympy.factor('x**2 - 1')",
                description="Factor a difference of squares",
            ),
        ]

    @classmethod
    def compute(
        cls, expr: Annotated[pa.StringArray, Param(doc="Expression to factor.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        return _map_str(expr, cas.factor)


class ToLatexFunction(ScalarFunction):
    """``to_latex(expr)`` -- LaTeX rendering, or NULL if invalid."""

    class Meta:
        name = "to_latex"
        description = "LaTeX rendering of an expression, or NULL if invalid/unsafe"
        categories = ["sympy", "cas"]
        examples = [
            FunctionExample(
                sql="SELECT sympy.to_latex('x**2')",
                description="Render x squared as LaTeX",
            ),
        ]

    @classmethod
    def compute(
        cls, expr: Annotated[pa.StringArray, Param(doc="Expression to render.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        return _map_str(expr, cas.to_latex)


# ===========================================================================
# Calculus: (expr, var) -> VARCHAR.
# ===========================================================================


class DifferentiateFunction(ScalarFunction):
    """``differentiate(expr, var)`` -- derivative w.r.t. ``var``, or NULL."""

    class Meta:
        name = "differentiate"
        description = "Derivative of an expression with respect to a variable, or NULL if invalid"
        categories = ["sympy", "cas", "calculus"]
        examples = [
            FunctionExample(
                sql="SELECT sympy.differentiate('x**3', 'x')",
                description="Differentiate x^3 -> 3*x**2",
            ),
        ]

    @classmethod
    def compute(
        cls,
        expr: Annotated[pa.StringArray, Param(doc="Expression to differentiate.")],
        var: Annotated[pa.StringArray, Param(doc="Variable name to differentiate by.")],
    ) -> Annotated[pa.StringArray, Returns()]:
        return _map_str2(expr, var, cas.differentiate)


class IntegrateFunction(ScalarFunction):
    """``integrate(expr, var)`` -- indefinite integral (no +C), or NULL."""

    class Meta:
        name = "integrate"
        description = (
            "Indefinite integral of an expression w.r.t. a variable (no +C), "
            "or NULL if invalid or no closed form is found"
        )
        categories = ["sympy", "cas", "calculus"]
        examples = [
            FunctionExample(
                sql="SELECT sympy.integrate('2*x', 'x')",
                description="Integrate 2*x -> x**2",
            ),
        ]

    @classmethod
    def compute(
        cls,
        expr: Annotated[pa.StringArray, Param(doc="Expression to integrate.")],
        var: Annotated[pa.StringArray, Param(doc="Variable name to integrate by.")],
    ) -> Annotated[pa.StringArray, Returns()]:
        return _map_str2(expr, var, cas.integrate)


# ===========================================================================
# solve -> LIST(VARCHAR) (explicit list arrow type required).
# ===========================================================================


class SolveFunction(ScalarFunction):
    """``solve(equation, var)`` -- solutions for ``var`` as a VARCHAR[]."""

    class Meta:
        name = "solve"
        description = (
            "Solve an equation for a variable, returning solutions as VARCHAR[]. "
            "Accepts 'lhs = rhs' or a bare expression assumed equal to zero. "
            "NULL if invalid; empty list if no solutions."
        )
        categories = ["sympy", "cas", "solve"]
        examples = [
            FunctionExample(
                sql="SELECT sympy.solve('x**2 - 4', 'x')",
                description="Solve x^2 - 4 = 0 -> ['-2', '2']",
            ),
            FunctionExample(
                sql="SELECT UNNEST(sympy.solve('2*x = 10', 'x'))",
                description="Unnest the solution rows",
            ),
        ]

    @classmethod
    def compute(
        cls,
        equation: Annotated[pa.StringArray, Param(doc="Equation or expression to solve.")],
        var: Annotated[pa.StringArray, Param(doc="Variable name to solve for.")],
    ) -> Annotated[pa.ListArray, Returns(arrow_type=pa.list_(pa.string()))]:
        return _map_list_str(equation, var, cas.solve)


# ===========================================================================
# evaluate -> DOUBLE.
# ===========================================================================


class EvaluateFunction(ScalarFunction):
    """``evaluate(expr, vars_json)`` -- numeric value of ``expr`` as DOUBLE."""

    class Meta:
        name = "evaluate"
        description = (
            'Substitute numeric values from a JSON object like \'{"x":2,"y":3}\' '
            "and evaluate to a DOUBLE. NULL if invalid, non-numeric, or free "
            "symbols remain."
        )
        categories = ["sympy", "cas", "evaluate"]
        examples = [
            FunctionExample(
                sql="SELECT sympy.evaluate('x**2 + y', '{\"x\":3,\"y\":1}')",
                description="Substitute x=3, y=1 -> 10.0",
            ),
        ]

    @classmethod
    def compute(
        cls,
        expr: Annotated[pa.StringArray, Param(doc="Expression to evaluate.")],
        vars_json: Annotated[pa.StringArray, Param(doc='JSON object of variable values, e.g. {"x":2}.')],
    ) -> Annotated[pa.DoubleArray, Returns()]:
        return _map_double2(expr, vars_json, cas.evaluate)


# ===========================================================================
# symbolic_equal -> BOOLEAN.
# ===========================================================================


class SymbolicEqualFunction(ScalarFunction):
    """``symbolic_equal(a, b)`` -- True if symbolically equivalent."""

    class Meta:
        name = "symbolic_equal"
        description = (
            "True if two expressions are symbolically equivalent (simplify(a-b)==0), "
            "or NULL if either is invalid"
        )
        categories = ["sympy", "cas"]
        examples = [
            FunctionExample(
                sql="SELECT sympy.symbolic_equal('2*(x+1)', '2*x+2')",
                description="Prove two forms are equal -> true",
            ),
        ]

    @classmethod
    def compute(
        cls,
        a: Annotated[pa.StringArray, Param(doc="First expression.")],
        b: Annotated[pa.StringArray, Param(doc="Second expression.")],
    ) -> Annotated[pa.BooleanArray, Returns()]:
        return _map_bool2(a, b, cas.symbolic_equal)


# ===========================================================================
# sympy_version -> VARCHAR (no argument).
# ===========================================================================


class SympyVersionFunction(ScalarFunction):
    """``sympy_version()`` -- the backing SymPy version string."""

    class Meta:
        name = "sympy_version"
        description = "The SymPy version string backing this worker"
        categories = ["sympy"]
        examples = [
            FunctionExample(
                sql="SELECT sympy.sympy_version()",
                description="Report the SymPy version",
            ),
        ]

    @classmethod
    def compute(
        cls, n: Annotated[pa.Int64Array, Param(doc="Row driver (value ignored).")]
    ) -> Annotated[pa.StringArray, Returns()]:
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
