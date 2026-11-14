"""Composed example queries that combine several of the worker's functions.

Each example is defined once here as a ``{"description", "sql"}`` dict and
referenced from both the schema-level ``vgi.example_queries`` list
(:mod:`vgi_sympy.worker`) and the example list of the function that drives the
query (:mod:`vgi_sympy.scalars`). Every query is offline and deterministic and is
pinned end-to-end in ``test/sql/cas.test``.
"""

from __future__ import annotations

from typing import Final

# Stationary points: differentiate -> solve (derivative = 0) -> evaluate f there.
CRITICAL_POINTS: Final[dict[str, str]] = {
    "description": "Find the stationary points of x**3 - 3*x by solving its derivative for zero, then "
    "evaluate the function at each one: a local maximum of 2.0 at x = -1 and a local minimum of -2.0 "
    "at x = 1.",
    "sql": (
        "WITH crit AS (\n"
        "  SELECT UNNEST(sympy.main.solve(sympy.main.differentiate('x**3 - 3*x', 'x'), 'x')) AS root\n"
        "), pts AS (\n"
        "  SELECT root, sympy.main.evaluate(root, '{}') AS x_value FROM crit\n"
        ")\n"
        "SELECT root, x_value,\n"
        "       sympy.main.evaluate('x**3 - 3*x', '{\"x\": ' || x_value || '}') AS f_value\n"
        "FROM pts\n"
        "ORDER BY x_value"
    ),
}

# Fundamental theorem check: integrate -> differentiate -> symbolic_equal.
ANTIDERIVATIVE_CHECK: Final[dict[str, str]] = {
    "description": "Integrate each integrand, then verify the antiderivative by differentiating it back "
    "and testing symbolic equality with the original (all four rows are verified TRUE, even where "
    "the round-tripped string looks different).",
    "sql": (
        "SELECT integrand,\n"
        "       sympy.main.integrate(integrand, 'x') AS antiderivative,\n"
        "       sympy.main.symbolic_equal(\n"
        "         sympy.main.differentiate(sympy.main.integrate(integrand, 'x'), 'x'), integrand) AS verified\n"
        "FROM (VALUES ('x*exp(x)'), ('1/(1 + x**2)'), ('sin(x)**2'), ('log(x)')) AS t(integrand)\n"
        "ORDER BY integrand"
    ),
}

# Answer grading: symbolic_equal against a key + to_latex for display.
GRADE_ANSWERS: Final[dict[str, str]] = {
    "description": "Grade free-form answers against the key (x + 1)**2: render each answer as LaTeX for "
    "display and mark it correct when it is symbolically equal to the key (only x**2 + 1 is wrong).",
    "sql": (
        "SELECT answer,\n"
        "       sympy.main.to_latex(answer) AS latex,\n"
        "       sympy.main.symbolic_equal(answer, '(x + 1)**2') AS correct\n"
        "FROM (VALUES ('x**2 + 2*x + 1'), ('(1 + x)*(x + 1)'), ('x**2 + 1'), ('x*(x + 2) + 1')) AS t(answer)\n"
        "ORDER BY answer"
    ),
}

# Factor over the rationals next to the roots from solve.
FACTOR_VS_ROOTS: Final[dict[str, str]] = {
    "description": "Show each polynomial's factorization over the rationals beside its roots: "
    "x**3 - 6*x**2 + 11*x - 6 factors into (x - 3)*(x - 2)*(x - 1) with roots 1, 2, 3, while "
    "x**2 - 2 comes back unfactored because its roots -sqrt(2) and sqrt(2) are irrational.",
    "sql": (
        "SELECT poly,\n"
        "       sympy.main.factor(poly) AS factored,\n"
        "       sympy.main.solve(poly, 'x') AS roots\n"
        "FROM (VALUES ('x**3 - 6*x**2 + 11*x - 6'), ('x**2 - 2')) AS t(poly)\n"
        "ORDER BY poly"
    ),
}

COMPOSED_EXAMPLES: Final[list[dict[str, str]]] = [
    CRITICAL_POINTS,
    ANTIDERIVATIVE_CHECK,
    GRADE_ANSWERS,
    FACTOR_VS_ROOTS,
]
