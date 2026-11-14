from app.storage import Store

def test_ticks_and_candles_persist(tmp_path):
    s = Store(str(tmp_path))
    s.insert_tick("CRASH500", 120, 100.0, 2, "live")
    s.upsert_candle("CRASH500", 60, 120, 100.0)
    s.insert_tick("CRASH500", 121, 99.5, 2, "live")
    s.upsert_candle("CRASH500", 60, 121, 99.5)
    stats = s.stats("CRASH500")
    assert stats["tick_count"] == 2
    candle = s.recent_candles("CRASH500", 60, 1)[0]
    assert candle["open"] == 100.0
    assert candle["low"] == 99.5
    assert candle["close"] == 99.5

def test_history_seed_is_idempotent(tmp_path):
    s = Store(str(tmp_path))
    first = s.insert_history_ticks("CRASH500", [100, 101], [10.0, 10.1], 2)
    second = s.insert_history_ticks("CRASH500", [100, 101], [10.0, 10.1], 2)
    assert len(first) == 2
    assert second == []
