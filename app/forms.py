"""Typed helpers for coercing Starlette ``FormData`` values.

``await request.form()`` returns a ``FormData`` whose values are typed
``str | UploadFile``. Handlers routinely coerce those to ``str``/``float``/``int``
with the same little patterns copy-pasted around. These helpers centralise that
coercion and narrow the type via ``isinstance(v, str)`` so the call sites stay
type-clean.
"""

from starlette.datastructures import FormData


def get_str(form: FormData, key: str, default: str = "") -> str:
    """Return the value if it is a ``str``, otherwise ``default``.

    Mirrors ``form.get(key, default)`` for text fields: a present-but-empty
    field returns ``""`` (not the default); a missing field or an uploaded
    file returns ``default``.
    """
    v = form.get(key)
    return v if isinstance(v, str) else default


def get_opt_str(form: FormData, key: str) -> str | None:
    """Return the value if it is a non-empty ``str``, otherwise ``None``.

    Mirrors the ubiquitous ``form.get(key) or None`` idiom. NOTE: this does
    NOT strip whitespace, deliberately preserving the exact (non-stripping)
    semantics of every existing call site — a whitespace-only value is kept
    verbatim, just as ``form.get(key) or None`` would keep it.
    """
    v = form.get(key)
    if isinstance(v, str) and v != "":
        return v
    return None


def get_float(form: FormData, key: str, default: float = 0.0) -> float:
    """Return ``float(value)`` for a parseable, non-empty ``str``; else ``default``.

    Mirrors the ``fval`` helpers: empty/missing/non-str values and unparseable
    strings fall back to ``default``.
    """
    v = form.get(key)
    if isinstance(v, str) and v != "":
        try:
            return float(v)
        except ValueError:
            return default
    return default


def get_opt_float(form: FormData, key: str) -> float | None:
    """Return ``float(value)`` for a parseable, non-empty ``str``; else ``None``.

    Empty/missing/non-str values and unparseable strings return ``None``.
    """
    v = form.get(key)
    if isinstance(v, str) and v != "":
        try:
            return float(v)
        except ValueError:
            return None
    return None


def get_int(form: FormData, key: str, default: int = 0) -> int:
    """Return ``int(float(value))`` for a parseable, non-empty ``str``; else ``default``."""
    v = form.get(key)
    if isinstance(v, str) and v != "":
        try:
            return int(float(v))
        except ValueError:
            return default
    return default


def get_opt_int(form: FormData, key: str) -> int | None:
    """Return ``int(float(value))`` for a parseable, non-empty ``str``; else ``None``."""
    v = form.get(key)
    if isinstance(v, str) and v != "":
        try:
            return int(float(v))
        except ValueError:
            return None
    return None
