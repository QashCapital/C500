from app.research import TickResearch

def test_warmup_does_not_flag_spike():
    r = TickResearch(window=100, multiplier=8, min_spike_pips=10)
    out = None
    for i in range(60):
        out = r.update(1000 + (i % 2) * 0.01, 2)
    assert out is None

def test_large_down_move_flags_candidate_after_warmup():
    r = TickResearch(window=100, multiplier=8, min_spike_pips=10)
    for i in range(80):
        r.update(1000 + (i % 2) * 0.01, 2)
    event = r.update(990.0, 2)
    assert event is not None
    assert event["delta"] < 0
    assert event["threshold"] > 0
