"""Session-token cookie format: padding-free base64url (Sprint 9 hardening).

A "=" inside an unquoted cookie value makes HTTP cookie parsers drop the cookie
entirely. Payload length decided whether a token contained padding, so logins
failed intermittently (the auth_flows flake). Tokens must never carry "=" and
legacy padded tokens must keep verifying (no forced logout on deploy).
"""
import base64
import json
import time

from app import auth


def test_make_token_has_no_cookie_hostile_chars():
    for _ in range(200):
        tok = auth.make_token(1)
        assert "=" not in tok
        assert " " not in tok
        assert auth.read_token(tok) == 1


def test_legacy_padded_token_still_verifies():
    payload = base64.urlsafe_b64encode(json.dumps(
        {"uid": 42, "exp": time.time() + 1000}).encode()).decode()  # may carry "="
    token = f"{payload}.{auth._sign(payload)}"
    assert auth.read_token(token) == 42


def test_tampered_and_expired_tokens_rejected():
    tok = auth.make_token(7)
    body, sig = tok.rsplit(".", 1)
    assert auth.read_token(f"{body[:-2]}AA.{sig}") is None
    flip = "1" if sig[-1] != "1" else "2"  # never an accidental no-op
    assert auth.read_token(f"{body}.{sig[:-1]}{flip}") is None
    expired = base64.urlsafe_b64encode(json.dumps(
        {"uid": 7, "exp": time.time() - 1}).encode()).decode().rstrip("=")
    assert auth.read_token(f"{expired}.{auth._sign(expired)}") is None


def test_secret_is_stable_across_generation(tmp_path, monkeypatch):
    # Raw 32-byte keys can contain whitespace bytes; the old generate-raw /
    # read-stripped split changed the signing key after first write (~1.6% of
    # installs). Generation and read-back must now return identical bytes.
    key = tmp_path / "secret.key"
    monkeypatch.setattr(auth, "SECRET_FILE", str(key))
    first = auth._secret()
    assert auth._secret() == first
    tok = auth.make_token(9)
    assert auth.read_token(tok) == 9  # sign-with-generation == verify-with-readback
    key.write_bytes(b"\x00\xff" + bytes(range(30)))  # legacy raw key
    assert auth._secret() == b"\x00\xff" + bytes(range(30))


def test_token_survives_http_cookie_parsing():
    from http.cookies import SimpleCookie
    tok = auth.make_token(3)
    c = SimpleCookie()
    c.load(f"{auth.COOKIE}={tok}; Path=/; HttpOnly; SameSite=Lax")
    assert c[auth.COOKIE].value == tok
    assert auth.read_token(c[auth.COOKIE].value) == 3
