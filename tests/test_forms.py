"""Unit tests for the typed form-value helpers in app.forms."""

from starlette.datastructures import FormData

from app.forms import (
    get_float,
    get_int,
    get_opt_float,
    get_opt_int,
    get_opt_str,
    get_str,
)


def _form(**kwargs) -> FormData:
    return FormData(list(kwargs.items()))


def test_get_str_returns_value_or_default():
    assert get_str(_form(name="Cash"), "name") == "Cash"
    assert get_str(_form(), "name", "fallback") == "fallback"
    # a present-but-empty field stays "" (not the default)
    assert get_str(_form(name=""), "name", "fallback") == ""


def test_get_opt_str_empty_becomes_none():
    assert get_opt_str(_form(note="hi"), "note") == "hi"
    assert get_opt_str(_form(note=""), "note") is None
    assert get_opt_str(_form(), "note") is None


def test_get_float_parses_and_falls_back():
    assert get_float(_form(value="12.5"), "value") == 12.5
    assert get_float(_form(value=""), "value") == 0.0
    assert get_float(_form(value="oops"), "value", -1.0) == -1.0


def test_get_opt_float_none_when_absent_or_bad():
    assert get_opt_float(_form(x="3"), "x") == 3.0
    assert get_opt_float(_form(), "x") is None
    assert get_opt_float(_form(x="nope"), "x") is None


def test_get_int_truncates_via_float():
    assert get_int(_form(n="5"), "n") == 5
    assert get_int(_form(n="5.9"), "n") == 5  # int(float("5.9"))
    assert get_int(_form(n=""), "n", 9) == 9


def test_get_opt_int_none_when_absent():
    assert get_opt_int(_form(n="7"), "n") == 7
    assert get_opt_int(_form(), "n") is None
