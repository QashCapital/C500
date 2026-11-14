import asyncio
import json
import logging
import time
from collections import deque

import websockets

from .config import settings

log = logging.getLogger("crash500.deriv")

class DerivCollector:
    def __init__(self, store):
        self.store = store
        self.connected = False
        self.symbol = None
        self.symbol_display = None
        self.last_message_at = None
        self.last_error = None
        self.research = None
        self._req_id = 100
        self._last_quote = None

    async def _send(self, ws, payload):
        await ws.send(json.dumps(payload))

    async def _receive_until(self, ws, req_id, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline-time.monotonic()))
            msg = json.loads(raw)
            if msg.get("error"):
                raise RuntimeError(msg["error"].get("message", str(msg["error"])))
            if msg.get("req_id") == req_id:
                return msg
        raise TimeoutError(f"Deriv request {req_id} timed out")

    async def _resolve_symbol(self, ws):
        self._req_id += 1
        rid = self._req_id
        await self._send(ws, {"active_symbols": "full", "req_id": rid})
        response = await self._receive_until(ws, rid)
        symbols = response.get("active_symbols", [])
        target = settings.symbol_name.strip().lower()
        matches = [
            item for item in symbols
            if str(item.get("display_name", "")).strip().lower() == target
            or str(item.get("symbol", "")).strip().lower() == target.replace(" ", "")
        ]
        if not matches:
            candidates = [
                {"display_name": x.get("display_name"), "symbol": x.get("symbol")}
                for x in symbols
                if "crash 500" in str(x.get("display_name", "")).lower()
            ]
            raise RuntimeError(f"Could not resolve '{settings.symbol_name}'. Crash 500 candidates: {candidates}")
        item = matches[0]
        return item.get("symbol"), item.get("display_name"), item.get("pip")

    async def _seed_history(self, ws, symbol, pip_size):
        self._req_id += 1
        rid = self._req_id
        await self._send(ws, {
            "ticks_history": symbol,
            "count": settings.history_count,
            "end": "latest",
            "style": "ticks",
            "req_id": rid
        })
        response = await self._receive_until(ws, rid, timeout=40)
        history = response.get("history", {})
        times = history.get(" times") or history.get("times") or []
        prices = history.get("prices") or []
        inserted_rows = self.store.insert_history_ticks(symbol, times, prices, pip_size)
        # Update candle tick counts only for history ticks newly added on this run.
        for epoch, quote in sorted(inserted_rows, key=lambda x: int(x[0])):
            for tf in (60, 300, 900, 3600):
                self.store.upsert_candle(symbol, tf, int(epoch), float(quote))
        self.store.set_state("history_seed_inserted", str(len(inserted_rows)))
        log.info("History seed received=%s inserted=%s", len(times), len(inserted_rows))

    async def run_forever(self):
        while True:
            try:
                async with websockets.connect(
                    settings.deriv_ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    max_size=2**20
                ) as ws:
                    self.connected = True
                    self.last_error = None
                    self.last_message_at = int(time.time())
                    self.store.set_state("connection", "connected")
                    symbol, display, pip_size = await self._resolve_symbol(ws)
                    self.symbol, self.symbol_display = symbol, display
                    from .research import TickResearch
                    self.research = TickResearch(
                        settings.rolling_window,
                        settings.spike_multiplier,
                        settings.min_spike_pips
                    )
                    await self._seed_history(ws, symbol, pip_size)

                    self._req_id += 1
                    await self._send(ws, {"ticks": symbol, "subscribe": 1, "req_id": self._req_id})
                    self.store.set_state("resolved_symbol", symbol)
                    self.store.set_state("display_name", display)
                    log.info("Subscribed to %s (%s)", display, symbol)

                    async for raw in ws:
                        msg = json.loads(raw)
                        self.last_message_at = int(time.time())
                        if msg.get("error"):
                            raise RuntimeError(msg["error"].get("message", str(msg["error"])))
                        if msg.get("msg_type") != "tick":
                            continue
                        tick = msg.get("tick", {})
                        epoch = int(tick.get("epoch", time.time()))
                        quote = float(tick["quote"])
                        pip = tick.get("pip_size", pip_size)
                        self.store.insert_tick(symbol, epoch, quote, pip, "live")
                        for tf in (60, 300, 900, 3600):
                            self.store.upsert_candle(symbol, tf, epoch, quote)
                        event = self.research.update(quote, pip)
                        if event:
                            self.store.insert_spike(
                                symbol, epoch, event["previous_quote"], event["quote"],
                                event["delta"], event["threshold"]
                            )
                        self.store.set_state("last_tick_epoch", str(epoch))
                        self.store.set_state("last_tick_quote", str(quote))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.connected = False
                self.last_error = str(exc)
                self.store.set_state("connection", "disconnected")
                self.store.set_state("last_error", self.last_error)
                log.exception("Collector disconnected: %s", exc)
                await asyncio.sleep(settings.reconnect_seconds)
            finally:
                self.connected = False
