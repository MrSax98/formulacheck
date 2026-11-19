import pytest

from formulacheck.expr import ExprError, evaluate, names_in, parse

FUNCS = {"sqrt": lambda x: x**0.5}


def ev(src: str, **env: float) -> object:
    return evaluate(parse(src), env, FUNCS)


def test_arithmetic_and_functions() -> None:
    assert ev("sqrt(x) + 2*y", x=9.0, y=1.0) == 5.0
    assert ev("-x**2", x=3) == -9


@pytest.mark.parametrize(
    "payload",
    [
        "__import__('os').system('echo pwned')",
        "().__class__",
        "x.real",
        "[i for i in range(3)]",
        "lambda: 1",
        "open('/etc/passwd')",
        "'a string'",
        "x if x else 1",
        "{1: 2}",
        "x[0]",
        "x; y",
        "True",
        "None",
        "sqrt(x, key=1)",
        "x ^ 2",
        "1 < 2 < 3",
        "x // 2",
        "x % 2",
        "unknown_name",
        "unknown_fn(1)",
        "(lambda: 1)()",
        "getattr(x, 'real')",
    ],
)
def test_unsafe_or_unsupported_expressions_are_rejected(payload: str) -> None:
    with pytest.raises(ExprError):
        ev(payload, x=1.0)


@pytest.mark.parametrize("payload", ["9**9**9", "10**100000", "2.0**100000", "x**20000"])
def test_huge_powers_are_rejected(payload: str) -> None:
    with pytest.raises(ExprError):
        ev(payload, x=2)


def test_size_limits() -> None:
    with pytest.raises(ExprError):
        parse("1+" * 600 + "1")
    with pytest.raises(ExprError):
        parse("x" * 2000)
    with pytest.raises(ExprError):
        parse("")


def test_comparison_only_when_allowed() -> None:
    node = parse("x < 2")
    with pytest.raises(ExprError):
        evaluate(node, {"x": 1}, {})
    assert evaluate(node, {"x": 1}, {}, allow_compare=True) is True


def test_names_in_excludes_called_functions() -> None:
    assert names_in(parse("sqrt(x) + y")) == {"x", "y"}
