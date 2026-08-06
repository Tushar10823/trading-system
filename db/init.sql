-- Trading System MVP schema

CREATE TABLE IF NOT EXISTS market_snapshots (
    id          SERIAL PRIMARY KEY,
    symbol      VARCHAR(10)  NOT NULL,
    price_json  JSONB        NOT NULL,
    news_json   JSONB        NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol_created
    ON market_snapshots (symbol, created_at DESC);

CREATE TABLE IF NOT EXISTS signals (
    id               SERIAL PRIMARY KEY,
    symbol           VARCHAR(10)  NOT NULL,
    action           VARCHAR(10)  NOT NULL CHECK (action IN ('BUY', 'SELL', 'HOLD')),
    confidence       INTEGER      NOT NULL CHECK (confidence BETWEEN 0 AND 100),
    reasoning        TEXT         NOT NULL,
    raw_llm_response TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signals_symbol_created
    ON signals (symbol, created_at DESC);

CREATE TABLE IF NOT EXISTS trades (
    id              SERIAL PRIMARY KEY,
    signal_id       INTEGER      REFERENCES signals(id),
    symbol          VARCHAR(10)  NOT NULL,
    side            VARCHAR(10)  NOT NULL CHECK (side IN ('buy', 'sell')),
    qty             NUMERIC(12, 4) NOT NULL,
    entry_price     NUMERIC(12, 4),
    alpaca_order_id VARCHAR(64),
    status          VARCHAR(32)  NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol_created
    ON trades (symbol, created_at DESC);
