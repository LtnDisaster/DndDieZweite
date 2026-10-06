"""Frontend build identity (D78).

One authoritative build token for the WHOLE frontend generation: the sha256
over every application-owned JS/CSS file plus index.html. It is computed once
at process start, so a rebuild/restart that changed any asset yields a new
token, while an unchanged tree keeps its token (cached assets stay valid).

The token is rendered into index.html (`?v=TOKEN` on every asset URL and an
inline `window.__BUILD__`), served by GET /api/build, and logged at startup as
`BUILD <token>`. A browser can therefore never mix script generations from
cache: any changed file changes every URL.

Diagnostic output is deliberately minimal: filenames and content hashes only —
no paths, sizes, environment or secret material.
"""
import hashlib
import os

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
JS_DIR = os.path.join(STATIC_DIR, "js")
_HASH_LEN = 12


def asset_files():
    """(url_basename, absolute_path) of every application-owned asset,
    index.html first, then style.css, then js/*.js in load order."""
    out = []
    index = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index):
        out.append(("index.html", index))
    css = os.path.join(STATIC_DIR, "style.css")
    if os.path.isfile(css):
        out.append(("style.css", css))
    if os.path.isdir(JS_DIR):
        for name in sorted(os.listdir(JS_DIR)):
            if name.endswith(".js"):
                out.append((name, os.path.join(JS_DIR, name)))
    return out


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:_HASH_LEN]


_GENERATION = None


def _compute():
    hashes = {name: _sha(path) for name, path in asset_files()}
    joined = "\n".join(f"{name}:{digest}" for name, digest in sorted(hashes.items()))
    token = hashlib.sha256(joined.encode()).hexdigest()[:_HASH_LEN]
    return token, hashes


def generation():
    """Token and per-file hashes, computed once per process (a new process —
    i.e. any restart or rebuild — recomputes)."""
    global _GENERATION
    if _GENERATION is None:
        _GENERATION = _compute()
    return _GENERATION


def token():
    return generation()[0]


def file_hashes():
    return dict(generation()[1])
