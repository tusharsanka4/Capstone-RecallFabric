from types import SimpleNamespace

import pytest

from recallfabric.db.connection import check_ssl_in_use


@pytest.mark.parametrize("encrypted", [True, False])
def test_tls_uses_client_connection_instead_of_server_view(encrypted):
    class ProxyConnection:
        connection = SimpleNamespace(
            driver_connection=SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=encrypted))
        )

        def execute(self, query):
            raise AssertionError("Server-side TLS does not describe the client-to-proxy link")

    assert check_ssl_in_use(ProxyConnection()) is encrypted


def test_unavailable_tls_information_fails_closed():
    assert check_ssl_in_use(SimpleNamespace()) is False
