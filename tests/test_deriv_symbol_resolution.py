import pytest
from types import SimpleNamespace
from app.deriv import DerivCollector

class DummyStore:
    pass

class DummyWS:
    async def send(self, payload):
        self.payload = payload

@pytest.mark.asyncio
async def test_resolves_current_deriv_field_names(monkeypatch):
    from app import deriv
    monkeypatch.setattr(deriv, "settings", SimpleNamespace(symbol_name="Crash 500 Index"))
    c = DerivCollector(DummyStore())
    async def receive(ws, req_id, timeout=20):
        return {"req_id": req_id, "active_symbols": [{
            "underlying_symbol": "CRASH500",
            "underlying_symbol_name": "Crash 500 Index",
            "pip_size": 0.01
        }]}
    c._receive_until = receive
    symbol, display, pip = await c._resolve_symbol(DummyWS())
    assert (symbol, display, pip) == ("CRASH500", "Crash 500 Index", 0.01)

@pytest.mark.asyncio
async def test_resolves_legacy_deriv_field_names(monkeypatch):
    from app import deriv
    monkeypatch.setattr(deriv, "settings", SimpleNamespace(symbol_name="Crash 500 Index"))
    c = DerivCollector(DummyStore())
    async def receive(ws, req_id, timeout=20):
        return {"req_id": req_id, "active_symbols": [{
            "symbol": "CRASH500", "display_name": "Crash 500 Index", "pip": 0.01
        }]}
    c._receive_until = receive
    symbol, display, pip = await c._resolve_symbol(DummyWS())
    assert (symbol, display, pip) == ("CRASH500", "Crash 500 Index", 0.01)
