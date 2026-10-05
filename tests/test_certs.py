from types import SimpleNamespace

import certifi

from bot import certs


def fake_paths(cafile=None, capath=None):
    return lambda: SimpleNamespace(cafile=cafile, capath=capath)


def test_uses_certifi_when_python_has_no_ca_bundle(monkeypatch, tmp_path):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(certs.ssl, "get_default_verify_paths", fake_paths(str(tmp_path / "missing.pem")))
    assert certs.ensure_ca_bundle()
    assert certs.os.environ["SSL_CERT_FILE"] == certifi.where()


def test_keeps_the_system_bundle_when_present(monkeypatch, tmp_path):
    bundle = tmp_path / "cert.pem"
    bundle.write_text("x")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(certs.ssl, "get_default_verify_paths", fake_paths(str(bundle)))
    assert not certs.ensure_ca_bundle()
    assert "SSL_CERT_FILE" not in certs.os.environ


def test_respects_an_explicit_setting(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "/custom.pem")
    assert not certs.ensure_ca_bundle()
    assert certs.os.environ["SSL_CERT_FILE"] == "/custom.pem"
