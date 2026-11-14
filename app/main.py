import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .config import settings
from .storage import Store
from .deriv import DerivCollector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
store = Store(settings.data_dir)
collector = DerivCollector(store)
collector_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global collector_task
    collector_task = asyncio.create_task(collector.run_forever())
    yield
    if collector_task:
        collector_task.cancel()
        try:
            await collector_task
        except asyncio.CancelledError:
            pass

app = FastAPI(title="QUINT CAPITAL Crash 500 Intelligence V1", version="1.0.0", lifespan=lifespan)

@app.get("/health")
def health():
    return {"status": "ok", "service": "quint-crash500-intelligence-v1"}

@app.get("/api/status")
def status():
    symbol = collector.symbol or store.get_state().get("resolved_symbol")
    return {
        "service": "QUINT CAPITAL CRASH 500 INTELLIGENCE V1",
        "mode": "SHADOW_RESEARCH_ONLY",
        "broker_execution": False,
        "connected": collector.connected,
        "symbol": symbol,
        "display_name": collector.symbol_display or store.get_state().get("display_name"),
        "last_message_epoch": collector.last_message_at,
        "last_error": collector.last_error,
        "storage": store.stats(symbol) if symbol else {},
        "state": store.get_state()
    }

@app.get("/api/ticks")
def ticks(limit: int = 100):
    symbol = collector.symbol or store.get_state().get("resolved_symbol")
    if not symbol:
        raise HTTPException(503, "Crash 500 symbol has not been resolved yet")
    return store.recent_ticks(symbol, max(1, min(limit, 1000)))

@app.get("/api/spikes")
def spikes(limit: int = 50):
    symbol = collector.symbol or store.get_state().get("resolved_symbol")
    if not symbol:
        raise HTTPException(503, "Crash 500 symbol has not been resolved yet")
    return store.recent_spikes(symbol, max(1, min(limit, 500)))

@app.get("/api/candles/{timeframe}")
def candles(timeframe: int, limit: int = 100):
    if timeframe not in (60, 300, 900, 3600):
        raise HTTPException(400, "Supported timeframes: 60, 300, 900, 3600 seconds")
    symbol = collector.symbol or store.get_state().get("resolved_symbol")
    if not symbol:
        raise HTTPException(503, "Crash 500 symbol has not been resolved yet")
    return store.recent_candles(symbol, timeframe, max(1, min(limit, 1000)))

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse("""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>QUINT Crash 500 Lab</title>
<style>
body{font-family:system-ui;background:#10151d;color:#e8edf5;margin:0;padding:22px}
main{max-width:1050px;margin:auto}h1{font-size:24px} .muted{color:#9aa8ba}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.card{background:#1b2532;border:1px solid #2b394b;border-radius:12px;padding:16px}
.value{font-size:23px;font-weight:700;margin-top:8px;overflow-wrap:anywhere}
table{width:100%;border-collapse:collapse;margin-top:10px}td,th{text-align:left;padding:8px;border-bottom:1px solid #344254;font-size:13px}
section{margin-top:20px}.warn{color:#ffd27a}
</style></head><body><main>
<h1>QUINT CAPITAL — CRASH 500 INTELLIGENCE V1</h1>
<p class="muted">Independent market-data and shadow-research service · No broker execution</p>
<div class="grid">
<div class="card"><div class="muted">Connection</div><div class="value" id="connection">Loading…</div></div>
<div class="card"><div class="muted">Resolved symbol</div><div class="value" id="symbol">—</div></div>
<div class="card"><div class="muted">Stored ticks</div><div class="value" id="ticks">—</div></div>
<div class="card"><div class="muted">Latest quote</div><div class="value" id="quote">—</div></div>
<div class="card"><div class="muted">Spike candidates</div><div class="value" id="spikes">—</div></div>
<div class="card"><div class="muted">Last tick (epoch)</div><div class="value" id="last">—</div></div>
</div>
<section class="card"><h3>Recent downside spike candidates</h3><p class="muted">Statistical event flags only; not trade signals or predictions.</p>
<table><thead><tr><th>Epoch</th><th>Previous</th><th>Price</th><th>Move</th><th>Threshold</th></tr></thead><tbody id="spikeRows"></tbody></table></section>
<section class="card"><h3>Service notes</h3><p id="note" class="muted">Waiting for Deriv public market data.</p>
<p class="warn">Research only. No buy/sell instructions or automated orders are enabled.</p></section>
</main><script>
async function refresh(){
 try{
  const r=await fetch('/api/status'); const s=await r.json();
  document.getElementById('connection').textContent=s.connected?'CONNECTED':'DISCONNECTED';
  document.getElementById('symbol').textContent=s.display_name||s.symbol||'Resolving…';
  document.getElementById('ticks').textContent=(s.storage?.tick_count??0).toLocaleString();
  document.getElementById('quote').textContent=s.storage?.latest_tick?.quote??'—';
  document.getElementById('spikes').textContent=s.storage?.spike_candidate_count??0;
  document.getElementById('last').textContent=s.storage?.last_tick_epoch??'—';
  document.getElementById('note').textContent=s.last_error?'Collector error: '+s.last_error:
    (s.connected?'Live subscription active. Historical seed and live ticks are stored separately.':'Connecting or retrying Deriv public feed…');
  const p=await fetch('/api/spikes?limit=20'); const rows=await p.json();
  document.getElementById('spikeRows').innerHTML=rows.slice().reverse().map(x=>
   `<tr><td>${x.epoch}</td><td>${x.previous_quote}</td><td>${x.quote}</td><td>${x.delta}</td><td>${x.threshold}</td></tr>`
  ).join('')||'<tr><td colspan="5">No candidates recorded yet</td></tr>';
 }catch(e){document.getElementById('note').textContent='Dashboard refresh error: '+e}
}
refresh();setInterval(refresh,5000);
</script></body></html>""")
