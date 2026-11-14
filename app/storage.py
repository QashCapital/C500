import sqlite3
from pathlib import Path
from typing import Iterable

class Store:
    def __init__(self, data_dir: str):
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.path = str(Path(data_dir) / "crash500_research.sqlite3")
        self._init()

    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA busy_timeout=30000")
        return con

    def _init(self):
        with self.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS ticks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                quote REAL NOT NULL,
                pip_size INTEGER,
                source TEXT NOT NULL,
                received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_ticks_epoch ON ticks(epoch);
            CREATE INDEX IF NOT EXISTS idx_ticks_symbol_epoch ON ticks(symbol, epoch);
            CREATE TABLE IF NOT EXISTS candles (
                symbol TEXT NOT NULL,
                timeframe INTEGER NOT NULL,
                bucket INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                tick_count INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(symbol, timeframe, bucket)
            );
            CREATE TABLE IF NOT EXISTS spike_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                previous_quote REAL NOT NULL,
                quote REAL NOT NULL,
                delta REAL NOT NULL,
                threshold REAL NOT NULL,
                classification TEXT NOT NULL DEFAULT 'CANDIDATE',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, epoch, quote)
            );
            CREATE TABLE IF NOT EXISTS service_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """)

    def insert_tick(self, symbol: str, epoch: int, quote: float,
                    pip_size: float | None, source: str = "live"):
        with self.connect() as c:
            cur = c.execute(
                "INSERT INTO ticks(symbol,epoch,quote,pip_size,source) VALUES(?,?,?,?,?)",
                (symbol, int(epoch), float(quote), pip_size, source)
            )
            return cur.lastrowid

    def insert_history_ticks(self, symbol: str, times: Iterable[int],
                             prices: Iterable[float], pip_size: float | None):
        inserted_rows = []
        with self.connect() as c:
            for epoch, quote in zip(times, prices):
                exists = c.execute(
                    "SELECT 1 FROM ticks WHERE symbol=? AND epoch=? AND quote=? AND source='history' LIMIT 1",
                    (symbol, int(epoch), float(quote))
                ).fetchone()
                if exists:
                    continue
                c.execute(
                    "INSERT INTO ticks(symbol,epoch,quote,pip_size,source) VALUES(?,?,?,?,'history')",
                    (symbol, int(epoch), float(quote), pip_size)
                )
                inserted_rows.append((int(epoch), float(quote)))
        return inserted_rows

    def upsert_candle(self, symbol: str, timeframe: int, epoch: int, quote: float):
        bucket = (int(epoch) // timeframe) * timeframe
        with self.connect() as c:
            row = c.execute(
                "SELECT open,high,low,tick_count FROM candles WHERE symbol=? AND timeframe=? AND bucket=?",
                (symbol, timeframe, bucket)
            ).fetchone()
            if row is None:
                c.execute(
                    """INSERT INTO candles(symbol,timeframe,bucket,open,high,low,close,tick_count)
                       VALUES(?,?,?,?,?,?,?,1)""",
                    (symbol, timeframe, bucket, quote, quote, quote, quote)
                )
            else:
                c.execute(
                    """UPDATE candles SET high=?, low=?, close=?, tick_count=tick_count+1,
                       updated_at=CURRENT_TIMESTAMP WHERE symbol=? AND timeframe=? AND bucket=?""",
                    (max(row["high"], quote), min(row["low"], quote), quote,
                     symbol, timeframe, bucket)
                )

    def insert_spike(self, symbol, epoch, previous, quote, delta, threshold):
        with self.connect() as c:
            c.execute(
                """INSERT OR IGNORE INTO spike_events
                   (symbol,epoch,previous_quote,quote,delta,threshold)
                   VALUES(?,?,?,?,?,?)""",
                (symbol, int(epoch), float(previous), float(quote), float(delta), float(threshold))
            )

    def set_state(self, key: str, value: str):
        with self.connect() as c:
            c.execute("""INSERT INTO service_state(key,value) VALUES(?,?)
                         ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                         updated_at=CURRENT_TIMESTAMP""", (key, value))

    def get_state(self):
        with self.connect() as c:
            return {r["key"]: r["value"] for r in c.execute("SELECT key,value FROM service_state")}

    def stats(self, symbol: str):
        with self.connect() as c:
            ticks = c.execute("SELECT COUNT(*) n, MIN(epoch) first, MAX(epoch) last FROM ticks WHERE symbol=?", (symbol,)).fetchone()
            spikes = c.execute("SELECT COUNT(*) n, MAX(epoch) last FROM spike_events WHERE symbol=?", (symbol,)).fetchone()
            candles = c.execute("SELECT timeframe,COUNT(*) n FROM candles WHERE symbol=? GROUP BY timeframe", (symbol,)).fetchall()
            latest = c.execute("SELECT epoch,quote,source FROM ticks WHERE symbol=? ORDER BY epoch DESC,id DESC LIMIT 1", (symbol,)).fetchone()
            return {
                "tick_count": ticks["n"], "first_tick_epoch": ticks["first"],
                "last_tick_epoch": ticks["last"], "spike_candidate_count": spikes["n"],
                "last_spike_epoch": spikes["last"],
                "candles": {str(r["timeframe"]): r["n"] for r in candles},
                "latest_tick": dict(latest) if latest else None
            }

    def recent_ticks(self, symbol: str, limit: int = 100):
        with self.connect() as c:
            rows = c.execute(
                "SELECT epoch,quote,source FROM ticks WHERE symbol=? ORDER BY epoch DESC,id DESC LIMIT ?",
                (symbol, limit)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def recent_spikes(self, symbol: str, limit: int = 50):
        with self.connect() as c:
            rows = c.execute(
                """SELECT epoch,previous_quote,quote,delta,threshold,classification
                   FROM spike_events WHERE symbol=? ORDER BY epoch DESC LIMIT ?""",
                (symbol, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def recent_candles(self, symbol: str, timeframe: int, limit: int = 100):
        with self.connect() as c:
            rows = c.execute(
                """SELECT bucket,open,high,low,close,tick_count FROM candles
                   WHERE symbol=? AND timeframe=? ORDER BY bucket DESC LIMIT ?""",
                (symbol, timeframe, limit)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]
