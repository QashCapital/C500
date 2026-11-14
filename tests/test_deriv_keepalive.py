import asyncio
import json

from app.deriv import DerivCollector

class FakeStore:
    pass

class FakeWebSocket:
    def __init__(self):
        self.sent = []
    async def send(self, payload):
        self.sent.append(json.loads(payload))


def test_keepalive_sends_deriv_application_ping():
    async def scenario():
        collector = DerivCollector(FakeStore())
        ws = FakeWebSocket()
        task = asyncio.create_task(collector._keepalive(ws, interval=0.01))
        await asyncio.sleep(0.035)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert len(ws.sent) >= 2
        assert all(item.get("ping") == 1 for item in ws.sent)
    asyncio.run(scenario())
