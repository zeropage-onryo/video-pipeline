"""
Shared test setup.

The guard below exists because this has now bitten four times: a test
monkeypatches one generator function, the route is changed to call a
different one, the patch silently misses, and the test makes a real
billed API call while still passing. Nothing failed -- the only signal
was the suite getting slower.

So: no test may reach the network. Anything that wants to talk to
Gemini or YouTube has to patch the function it actually calls, and
gets a loud, immediate failure naming the offender if it doesn't.
"""
import socket

import pytest


class NetworkUseInTest(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch, request):
    def blocked(*args, **kwargs):
        raise NetworkUseInTest(
            f"{request.node.nodeid} tried to open a network connection. "
            "A real API call in a test usually means a monkeypatch is "
            "patching a function the code under test no longer calls."
        )

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
