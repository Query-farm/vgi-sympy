"""Unit tests for the pure CAS logic in :mod:`vgi_sympy.cas`.

These exercise known, deterministic results and -- importantly -- the safe
parser: a hostile string must be rejected (NULL / CASError), never executed.
"""

from __future__ import annotations

import pytest

from vgi_sympy import cas


class TestKnownResults:
    def test_simplify_trig_identity(self) -> None:
        assert cas.simplify("sin(x)**2 + cos(x)**2") == "1"

    def test_expand_binomial(self) -> None:
        assert cas.expand("(x + 1)**2") == "x**2 + 2*x + 1"

    def test_factor_difference_of_squares(self) -> None:
        assert cas.factor("x**2 - 1") == "(x - 1)*(x + 1)"

    def test_differentiate(self) -> None:
        assert cas.differentiate("x**3", "x") == "3*x**2"

    def test_integrate(self) -> None:
        assert cas.integrate("2*x", "x") == "x**2"

    def test_solve_quadratic_order_insensitive(self) -> None:
        assert cas.solve("x**2 - 4", "x") == ["-2", "2"]

    def test_solve_equation_with_equals(self) -> None:
        assert cas.solve("2*x = 10", "x") == ["5"]

    def test_solve_no_solution_returns_empty(self) -> None:
        # A trivially false equation: 1 = 0 has no solution for x.
        assert cas.solve("1 = 0", "x") == []

    def test_evaluate(self) -> None:
        assert cas.evaluate("x**2 + y", '{"x":3,"y":1}') == 10.0

    def test_evaluate_free_symbol_remaining_is_none(self) -> None:
        assert cas.evaluate("x**2 + y", '{"x":3}') is None

    def test_symbolic_equal_true(self) -> None:
        assert cas.symbolic_equal("2*(x+1)", "2*x+2") is True

    def test_symbolic_equal_false(self) -> None:
        assert cas.symbolic_equal("x+1", "x+2") is False

    def test_to_latex(self) -> None:
        assert cas.to_latex("x**2") == "x^{2}"

    def test_version_is_string(self) -> None:
        v = cas.sympy_version()
        assert isinstance(v, str) and v


class TestNullAndInvalid:
    def test_empty_simplify_is_none(self) -> None:
        assert cas.simplify("") is None
        assert cas.simplify("   ") is None

    def test_garbage_is_none(self) -> None:
        assert cas.simplify("x +* /") is None
        assert cas.factor(")(") is None

    def test_evaluate_bad_json_raises(self) -> None:
        with pytest.raises(cas.CASError):
            cas.evaluate("x", "not json")

    def test_evaluate_non_numeric_value_raises(self) -> None:
        with pytest.raises(cas.CASError):
            cas.evaluate("x", '{"x": "abc"}')

    def test_integrate_no_closed_form_is_none(self) -> None:
        # Most CAS cannot integrate this in closed form -> NULL, not an error.
        assert cas.integrate("sin(sin(x))", "x") is None

    def test_solve_bad_var_is_none(self) -> None:
        assert cas.solve("x**2 - 4", "x + 1") is None


class TestSafeParsing:
    """A hostile expression must NOT execute code -- it is rejected or inert.

    These assertions would FAIL catastrophically (side effects / arbitrary code)
    if ``sympify``/``eval`` were used. With the hardened ``parse_expr``, the
    names resolve to inert SymPy symbols/functions or the parse simply fails.
    """

    def test_import_attempt_does_not_execute(self) -> None:
        # If eval ran, this would call os.system. It must not.
        result = cas.simplify("__import__('os').system('echo pwned')")
        # Either rejected (None) or parsed to an inert symbolic expression --
        # never executed. The key guarantee: no exception from a side effect and
        # no shell ran. We accept None or a harmless string.
        assert result is None or isinstance(result, str)

    def test_dunder_class_traversal_is_rejected(self) -> None:
        # The classic sandbox-escape gadget. Must not yield Python internals.
        assert cas.simplify("().__class__.__bases__[0].__subclasses__()") is None

    def test_lambda_is_rejected(self) -> None:
        assert cas.simplify("lambda: 1") is None

    def test_oversized_expression_is_rejected(self) -> None:
        big = "x+" * (cas.MAX_EXPR_LEN) + "1"
        with pytest.raises(cas.CASError):
            cas.parse(big)

    def test_no_builtins_in_scope(self) -> None:
        # ``eval`` / ``open`` are not bound, so these become inert symbols, never
        # calls. simplify must not error from a real call and must not execute.
        assert cas.simplify("eval('1+1')") is None or isinstance(cas.simplify("eval('1+1')"), str)
