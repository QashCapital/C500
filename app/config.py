import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    data_dir: str = os.getenv("DATA_DIR", "/app/data/quint_crash500_lab")
    deriv_ws_url: str = os.getenv(
        "DERIV_WS_URL",
        "wss://api.derivws.com/trading/v1/options/ws/public"
    )
    symbol_name: str = os.getenv("DERIV_SYMBOL_NAME", "Crash 500 Index")
    history_count: int = int(os.getenv("HISTORY_TICK_COUNT", "5000"))
    reconnect_seconds: int = int(os.getenv("RECONNECT_SECONDS", "5"))
    rolling_window: int = int(os.getenv("SPIKE_ROLLING_WINDOW", "500"))
    spike_multiplier: float = float(os.getenv("SPIKE_MULTIPLIER", "8.0"))
    min_spike_pips: float = float(os.getenv("MIN_SPIKE_PIPS", "10"))
    app_host: str = os.getenv("HOST", "0.0.0.0")
    app_port: int = int(os.getenv("PORT", "8000"))

settings = Settings()
