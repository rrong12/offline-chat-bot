from types import SimpleNamespace

import certifi
import pytest

from bot import certs


def fake_paths(cafile=None, capath=None):
    # ssl.get_default_verify_paths() reports None for a CA file or folder that doesn't exist
    return lambda: SimpleNamespace(cafile=cafile, capath=capath)


@pytest.fixture
def clean_env(monkeypatch):
    # setenv first, so monkeypatch remembers and restores the original value after the test
    for name in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    return monkeypatch


def test_uses_certifi_when_python_has_no_ca_bundle(clean_env):
    clean_env.setattr(certs.ssl, "get_default_verify_paths", fake_paths())
    assert certs.ensure_ca_bundle()
    assert certs.os.environ["SSL_CERT_FILE"] == certifi.where()


def test_uses_certifi_when_the_cert_folder_is_empty(clean_env, tmp_path):
    clean_env.setattr(certs.ssl, "get_default_verify_paths", fake_paths(capath=str(tmp_path)))
    assert certs.ensure_ca_bundle()


def test_keeps_a_system_ca_file(clean_env, tmp_path):
    bundle = tmp_path / "cert.pem"
    bundle.write_text("x")
    clean_env.setattr(certs.ssl, "get_default_verify_paths", fake_paths(cafile=str(bundle)))
    assert not certs.ensure_ca_bundle()
    assert "SSL_CERT_FILE" not in certs.os.environ


def test_keeps_a_nonempty_system_cert_folder(clean_env, tmp_path):
    (tmp_path / "abcd1234.0").write_text("x")
    clean_env.setattr(certs.ssl, "get_default_verify_paths", fake_paths(capath=str(tmp_path)))
    assert not certs.ensure_ca_bundle()


def test_respects_explicit_settings(clean_env):
    clean_env.setenv("SSL_CERT_FILE", "/custom.pem")
    assert not certs.ensure_ca_bundle()
    assert certs.os.environ["SSL_CERT_FILE"] == "/custom.pem"
    clean_env.delenv("SSL_CERT_FILE")
    clean_env.setenv("SSL_CERT_DIR", "/custom/certs")
    assert not certs.ensure_ca_bundle()
