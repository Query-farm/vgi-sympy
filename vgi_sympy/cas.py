"""Pure symbolic-math (CAS) logic over SymPy -- no Arrow or VGI dependency.

Everything in this module takes plain ``str`` expressions and returns ``str``
(canonical SymPy ``str()`` form), ``list[str]``, ``float``, ``bool`` or ``None``.
``None`` always means "could not be computed safely" (invalid/unsafe input,
free symbols remaining, a SymPy failure, ...). Keeping the logic here -- pure,
importable and side-effect-free -- means it is directly unit-testable and reused
by the thin Arrow-facing adapters in :mod:`vgi_sympy.scalars`.

Safe parsing (READ THIS -- the security model)
==============================================
Turning an untrusted *string* into a SymPy expression is the dangerous step.
``sympy.sympify`` / ``eval`` are **NOT used** here: ``sympify`` falls back to
Python's ``eval`` and can be coerced into executing arbitrary code via attribute
tricks (``__class__``, ``__subclasses__``, lambdas, etc.).

Even :func:`sympy.parsing.sympy_parser.parse_expr` ultimately ``eval``s the
token stream against its namespaces, so on its own it is NOT safe: with the
default ``from sympy import *`` namespace, ``().__class__.__bases__[0].
__subclasses__()`` evaluates and exposes Python internals -- a real sandbox
escape. We therefore use **two independent layers of defense**:

1. **Token screening (primary).** Before parsing, the raw string is tokenized
   with the stdlib :mod:`tokenize`. Any token that enables an escape is
   rejected outright (:func:`_screen_tokens`):
     * ``.`` attribute access (``().__class__``, ``x.y``) -- never needed in a
       math expression (``2.5`` is a NUMBER token, not ``.`` access);
     * dunder names (``__class__``, ``__import__``, ``__builtins__``, ...);
     * ``lambda`` / ``:`` / ``;`` / ``=`` / ``[`` indexing / f-strings / strings
       and other constructs with no place in a scalar math expression.
   This means the dangerous gadgets never even reach ``eval``.
2. **Restricted namespace (defense in depth).** Parsing uses an allow-list
   ``local_dict`` of safe math names and a ``global_dict`` containing only SymPy
   objects with ``__builtins__`` stripped to ``{}`` -- so ``eval``, ``__import__``,
   ``open`` etc. are not in scope even if a token somehow slipped through. Any
   *other* bare name is auto-created as an inert ``Symbol`` by SymPy's
   ``auto_symbol`` transformation (treated as a variable, never executed).

Additionally:

* only the **default**, side-effect-free transformations
  (``standard_transformations``) are used -- no implicit-multiplication or
  lambda transformations;
* the raw input is length-bounded (:data:`MAX_EXPR_LEN`) and the parsed tree is
  complexity-bounded (:data:`MAX_NODES`) to cap blow-ups; and
* every public function wraps the whole parse+compute in ``try/except`` and
  returns ``None`` (or raises a clean :class:`CASError`) on any failure -- a
  malformed or hostile expression yields a clear error, never code execution.

So ``"__import__('os').system('rm')"`` and ``"().__class__.__bases__"`` are both
*rejected at the token screen*, and even an unforeseen gadget would only resolve
to inert SymPy symbols in a builtin-free namespace.
"""

from __future__ import annotations

import io
import json
import math
import tokenize

import sympy
from sympy.parsing.sympy_parser import (
    parse_expr,
    standard_transformations,
)

__all__ = [
    "CASError",
    "MAX_EXPR_LEN",
    "MAX_NODES",
    "differentiate",
    "evaluate",
    "expand",
    "factor",
    "integrate",
    "simplify",
    "solve",
    "symbolic_equal",
    "sympy_version",
    "to_latex",
]


class CASError(ValueError):
    """A user-facing error: invalid, unsafe, or too-complex expression."""


# Hard caps. A user expression longer than this, or one whose parsed tree has
# more than this many nodes, is rejected before any expensive CAS work runs.
MAX_EXPR_LEN = 2000
MAX_NODES = 5000

# ---------------------------------------------------------------------------
# Safe parsing.
# ---------------------------------------------------------------------------

# Explicit allow-list of names a user expression may reference. SymPy's
# ``auto_symbol`` transformation turns any *other* bare name into a Symbol, so
# omitting something just means "treated as a variable", never "executes". We do
# NOT expose any Python builtins, ``sympify``, ``lambdify``, file/OS access etc.
_ALLOWED_NAMES: dict[str, object] = {
    # constants
    "pi": sympy.pi,
    "E": sympy.E,
    "I": sympy.I,
    "oo": sympy.oo,
    "infinity": sympy.oo,
    "nan": sympy.nan,
    "GoldenRatio": sympy.GoldenRatio,
    "EulerGamma": sympy.EulerGamma,
    # elementary functions
    "sqrt": sympy.sqrt,
    "exp": sympy.exp,
    "log": sympy.log,
    "ln": sympy.log,
    "Abs": sympy.Abs,
    "abs": sympy.Abs,
    "sign": sympy.sign,
    "factorial": sympy.factorial,
    "gamma": sympy.gamma,
    # trig / hyperbolic
    "sin": sympy.sin,
    "cos": sympy.cos,
    "tan": sympy.tan,
    "cot": sympy.cot,
    "sec": sympy.sec,
    "csc": sympy.csc,
    "asin": sympy.asin,
    "acos": sympy.acos,
    "atan": sympy.atan,
    "atan2": sympy.atan2,
    "sinh": sympy.sinh,
    "cosh": sympy.cosh,
    "tanh": sympy.tanh,
    "asinh": sympy.asinh,
    "acosh": sympy.acosh,
    "atanh": sympy.atanh,
}

# Only the default, side-effect-free transformations. We do NOT add
# implicit-multiplication / function-exponentiation / lambda transformations.
_TRANSFORMATIONS = standard_transformations

# Controlled global namespace for parse_expr's internal eval: every SymPy name
# (so the auto-created Symbol/Integer/etc. constructors that transformations
# emit are resolvable) but with ``__builtins__`` stripped, so eval/__import__/
# open/exec are NOT reachable. Built once at import (expensive) and never
# mutated -- a fresh shallow copy is handed to each parse.
_GLOBAL_DICT: dict[str, object] = {}
exec("from sympy import *", _GLOBAL_DICT)  # noqa: S102 -- our own trusted string
_GLOBAL_DICT["__builtins__"] = {}

# OP tokens that have no place in a scalar math expression and which, if allowed,
# could enable escapes (attribute access, indexing, assignment, statements,
# slicing, lambda bodies). ``.`` is the critical one: ``().__class__`` is an
# escape gadget, while a real decimal like ``2.5`` is a single NUMBER token.
_FORBIDDEN_OPS = frozenset({".", "[", "]", "{", "}", ":", ";", "=", "@", "\\", "->"})


def _screen_tokens(text: str) -> None:
    """Reject expressions containing escape-enabling tokens before parsing.

    Raises :class:`CASError` on the first dangerous token. See the module
    docstring for the rationale; this is the primary security layer.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise CASError(f"could not tokenize expression: {exc}") from exc

    for tok in tokens:
        if tok.type in (
            tokenize.STRING,
            tokenize.FSTRING_START,
            tokenize.FSTRING_MIDDLE,
            tokenize.FSTRING_END,
        ):
            raise CASError("string literals are not allowed in expressions")
        if tok.type == tokenize.OP and tok.string in _FORBIDDEN_OPS:
            raise CASError(f"operator {tok.string!r} is not allowed in expressions")
        if tok.type == tokenize.NAME:
            name = tok.string
            if name == "lambda":
                raise CASError("'lambda' is not allowed in expressions")
            if name.startswith("__") or name.endswith("__"):
                raise CASError(f"dunder name {name!r} is not allowed in expressions")


def _count_nodes(expr: sympy.Basic) -> int:
    """Number of nodes in the expression tree (cheap structural complexity)."""
    return 1 + sum(_count_nodes(a) for a in expr.args)


def parse(text: str, *, evaluate: bool = True) -> sympy.Basic:
    """Safely parse ``text`` into a SymPy expression.

    Raises :class:`CASError` on empty/oversized/unsafe/too-complex input. Never
    executes arbitrary Python: the input is token-screened, then parsed against
    an allow-list ``local_dict`` and a builtin-free ``global_dict`` (see the
    module docstring).
    """
    if text is None:
        raise CASError("expression is NULL")
    stripped = text.strip()
    if not stripped:
        raise CASError("expression is empty")
    if len(stripped) > MAX_EXPR_LEN:
        raise CASError(f"expression too long (> {MAX_EXPR_LEN} characters)")

    # Layer 1: token screen -- reject escape-enabling syntax up front.
    _screen_tokens(stripped)

    try:
        # Layer 2: parse in a restricted namespace (builtin-free global_dict).
        expr = parse_expr(
            stripped,
            local_dict=dict(_ALLOWED_NAMES),
            global_dict=dict(_GLOBAL_DICT),
            transformations=_TRANSFORMATIONS,
            evaluate=evaluate,
        )
    except CASError:
        raise
    except Exception as exc:  # noqa: BLE001 -- any parse failure is a user error
        raise CASError(f"could not parse expression: {exc}") from exc

    if not isinstance(expr, sympy.Basic):
        raise CASError("expression did not parse to a symbolic object")
    if _count_nodes(expr) > MAX_NODES:
        raise CASError(f"expression too complex (> {MAX_NODES} nodes)")
    return expr


def _symbol(name: str) -> sympy.Symbol:
    """Parse a *variable name* into a single SymPy Symbol (safely)."""
    expr = parse(name)
    if not isinstance(expr, sympy.Symbol):
        raise CASError(f"{name!r} is not a simple variable name")
    return expr


# ---------------------------------------------------------------------------
# Public CAS operations. Each returns ``None`` on failure (adapters map NULL
# in -> NULL out; invalid expression -> NULL), except where a clear error is
# more useful -- those raise CASError, which adapters surface as a DuckDB error.
# ---------------------------------------------------------------------------


def simplify(expr: str) -> str | None:
    """Simplified canonical form of ``expr``, or ``None`` on failure."""
    try:
        return str(sympy.simplify(parse(expr)))
    except Exception:  # noqa: BLE001
        return None


def expand(expr: str) -> str | None:
    """Algebraically expanded form of ``expr``, or ``None`` on failure."""
    try:
        return str(sympy.expand(parse(expr)))
    except Exception:  # noqa: BLE001
        return None


def factor(expr: str) -> str | None:
    """Factored form of ``expr``, or ``None`` on failure."""
    try:
        return str(sympy.factor(parse(expr)))
    except Exception:  # noqa: BLE001
        return None


def differentiate(expr: str, var: str) -> str | None:
    """Derivative of ``expr`` with respect to ``var``, or ``None`` on failure."""
    try:
        return str(sympy.diff(parse(expr), _symbol(var)))
    except Exception:  # noqa: BLE001
        return None


def integrate(expr: str, var: str) -> str | None:
    """Indefinite integral of ``expr`` w.r.t. ``var`` (no ``+C``), or ``None``."""
    try:
        result = sympy.integrate(parse(expr), _symbol(var))
        if result.has(sympy.Integral):
            return None  # could not find a closed form
        return str(result)
    except Exception:  # noqa: BLE001
        return None


def solve(equation: str, var: str) -> list[str] | None:
    """Solve ``equation`` for ``var``.

    Accepts ``'lhs = rhs'`` (split on the first ``=``) or a bare expression that
    is assumed equal to zero. Returns the solutions as canonical strings, sorted
    for determinism, or ``None`` on failure. An empty solution set returns ``[]``.
    """
    try:
        symbol = _symbol(var)
        if "=" in equation:
            lhs_text, rhs_text = equation.split("=", 1)
            expr = parse(lhs_text) - parse(rhs_text)
        else:
            expr = parse(equation)
        solutions = sympy.solve(expr, symbol, dict=False)
        return sorted(str(s) for s in solutions)
    except Exception:  # noqa: BLE001
        return None


def evaluate(expr: str, vars_json: str) -> float | None:
    """Substitute numeric values from a JSON object and evaluate to a float.

    ``vars_json`` is a JSON object like ``{"x": 2, "y": 3}``. Returns ``None`` if
    the input is invalid, if any free symbol remains unsubstituted, or if the
    result is not a finite real number.
    """
    try:
        parsed = parse(expr)
        try:
            mapping = json.loads(vars_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise CASError(f"vars must be a JSON object: {exc}") from exc
        if not isinstance(mapping, dict):
            raise CASError('vars must be a JSON object, e.g. {"x": 2}')

        subs: dict[sympy.Symbol, sympy.Float] = {}
        for name, value in mapping.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise CASError(f"value for {name!r} is not numeric")
            subs[sympy.Symbol(str(name))] = sympy.Float(value)

        substituted = parsed.subs(subs)
        if substituted.free_symbols:
            return None  # unresolved variables remain
        result = complex(substituted.evalf())
        if result.imag != 0:
            return None
        out = result.real
        if not math.isfinite(out):
            return None
        return out
    except CASError:
        raise
    except Exception:  # noqa: BLE001
        return None


def to_latex(expr: str) -> str | None:
    """LaTeX rendering of ``expr``, or ``None`` on failure."""
    try:
        return sympy.latex(parse(expr))
    except Exception:  # noqa: BLE001
        return None


def symbolic_equal(a: str, b: str) -> bool | None:
    """True if ``a`` and ``b`` are symbolically equivalent (``simplify(a-b)==0``).

    Returns ``None`` if either side is invalid or equivalence cannot be decided.
    """
    try:
        diff = sympy.simplify(parse(a) - parse(b))
        if diff == 0:
            return True
        # ``equals`` can prove equivalence in cases ``simplify`` leaves nonzero.
        proven = (parse(a)).equals(parse(b))
        if proven is True:
            return True
        if proven is False:
            return False
        return False
    except Exception:  # noqa: BLE001
        return None


def sympy_version() -> str:
    """The SymPy version string backing this worker."""
    return str(sympy.__version__)
