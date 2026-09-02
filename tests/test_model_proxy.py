import urllib.request

from portal_audit.adapters.network.proxy import resolve_https_proxy


def test_explicit_model_proxy_takes_precedence(monkeypatch):
    monkeypatch.setattr(
        urllib.request,
        "getproxies",
        lambda: {"https": "http://system-proxy.test:8080"},
    )

    assert resolve_https_proxy("http://explicit-proxy.test:9090") == (
        "http://explicit-proxy.test:9090"
    )


def test_model_proxy_discovers_macos_or_environment_https_proxy(monkeypatch):
    monkeypatch.setattr(
        urllib.request,
        "getproxies",
        lambda: {
            "http": "http://127.0.0.1:15236",
            "https": "http://127.0.0.1:15236",
            "socks": "http://127.0.0.1:15235",
        },
    )

    assert resolve_https_proxy() == "http://127.0.0.1:15236"

