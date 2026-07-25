"""Escaping helpers for the HTML fragments that routers build by hand.

Most of the UI is rendered through Jinja2, which autoescapes. But the HTMX
partials in a few routers are assembled as f-strings, where nothing escapes
anything for you. Everything those fragments interpolate out of the database is
user-authored — asset names, tickers, currency codes, snapshot dates all arrive
from a form or a CSV import — so each value has to be escaped at the point of
use.

New fragments are better off as Jinja partials under ``templates/``, which get
autoescaping for free.
"""

import html
import json
from typing import Any


def e(value: Any) -> str:
    """HTML-escape a value for element text or a quoted attribute."""
    return html.escape(str(value if value is not None else ""), quote=True)


def json_for_script(value: Any) -> str:
    """Serialise ``value`` to JSON that is safe to embed inside a <script> block.

    ``json.dumps`` on its own is not sufficient: it leaves ``<`` untouched, so a
    string containing ``</script>`` closes the block early and everything after
    it is parsed as HTML. Escaping the three HTML-significant characters as
    ``\\uXXXX`` leaves the JSON semantically identical but inert — the same
    treatment Jinja's ``|tojson`` filter applies. (Non-ASCII, including U+2028
    and U+2029, is already escaped by ``ensure_ascii``.)
    """
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
