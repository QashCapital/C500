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

    @staticmethod
    def _normalise_symbol_text(value):
        return "".join(ch for ch in str(value or "").lower() if ch.isalnum())

    async def _resolve_symbol(self, ws):
        self._req_id += 1
        rid = self._req_id
        await self._send(ws, {"active_symbols": "full", "req_id": rid})
        response = await self._receive_until(ws, rid)
        symbols = response.get("active_symbols", [])
        if not isinstance(symbols, list):
            raise RuntimeError(
                "Deriv active_symbols response did not contain a list; "
                f"response keys={list(response.keys())}"
            )

        target = self._normalise_symbol_text(settings.symbol_name)
        matches = []
        for item in symbols:
            # The current Deriv API renamed legacy fields:
            # symbol -> underlying_symbol, display_name -> underlying_symbol_name,
            # pip -> pip_size. Keep legacy aliases for backward compatibility.
            display = (item.get("underlying_symbol_name") or item.get("display_name")
                       or item.get("name") or "")
            code = item.get("underlying_symbol") or item.get("symbol") or ""
            display_norm = self._normalise_symbol_text(display)
            code_norm = self._normalise_symbol_text(code)
            if display_norm == target or code_norm == target:
                matches.append(item)

        if not matches:
            candidates = []
            for item in symbols:
                display = (item.get("underlying_symbol_name") or item.get("display_name")
                           or item.get("name"))
                code = item.get("underlying_symbol") or item.get("symbol")
                if "crash500" in self._normalise_symbol_text(display) or "crash500" in self._normalise_symbol_text(code):
                    candidates.append({"display_name": display, "symbol": code})
            sample = [
                {
                    "display_name": x.get("underlying_symbol_name") or x.get("display_name"),
                    "symbol": x.get("underlying_symbol") or x.get("symbol")
                }
                for x in symbols[:5]
            ]
            raise RuntimeError(
                f"Could not resolve '{settings.symbol_name}'. "
                f"Crash 500 candidates: {candidates}; active_symbols_count={len(symbols)}; sample={sample}"
            )

        item = matches[0]
        symbol = item.get("underlying_symbol") or item.get("symbol")
        display = (item.get("underlying_symbol_name") or item.get("display_name")
                   or item.get("name") or settings.symbol_name)
        pip_size = item.get("pip_size", item.get("pip"))
        if not symbol:
            raise RuntimeError(f"Resolved Crash 500 entry has no symbol identifier: {item}")
        return symbol, display, float(pip_size) if pip_size is not None else None

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
