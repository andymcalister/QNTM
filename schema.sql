-- QuantEdge Platform — Supabase PostgreSQL Schema
-- Run this in your Supabase SQL editor

-- Users table (extends Supabase auth.users)
CREATE TABLE IF NOT EXISTS public.users (
    id              UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email           TEXT UNIQUE NOT NULL,
    full_name       TEXT,
    plan            TEXT DEFAULT 'free' CHECK (plan IN ('free','pro','institutional')),
    totp_secret     TEXT,                          -- encrypted TOTP seed
    mfa_enabled     BOOLEAN DEFAULT FALSE,
    notifications   JSONB DEFAULT '{"email":true,"signals":true,"alerts":true}'::jsonb,
    cookies_accepted BOOLEAN DEFAULT FALSE,
    cookies_accepted_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login      TIMESTAMPTZ,
    stripe_customer_id TEXT
);

-- Holdings table
CREATE TABLE IF NOT EXISTS public.holdings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    ticker          TEXT NOT NULL,
    shares          NUMERIC(12,4) NOT NULL,
    avg_cost        NUMERIC(12,4),
    entry_date      DATE,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, ticker)
);

-- Signal log (model outputs, stored daily)
CREATE TABLE IF NOT EXISTS public.signal_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker          TEXT NOT NULL,
    signal_date     DATE NOT NULL DEFAULT CURRENT_DATE,
    composite       NUMERIC(5,1),
    momentum        NUMERIC(5,1),
    quality         NUMERIC(5,1),
    volume          NUMERIC(5,1),
    value           NUMERIC(5,1),
    sentiment       NUMERIC(5,1),
    signal          TEXT,                          -- STRONG_ALIGN, HIGH_ALIGN, etc
    macro_overlay   NUMERIC(5,3),
    adj_composite   NUMERIC(5,1),
    is_hidden_gem   BOOLEAN DEFAULT FALSE,
    hidden_gem_reason TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ticker, signal_date)
);

-- Notification queue
CREATE TABLE IF NOT EXISTS public.notifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    ticker          TEXT,
    notification_type TEXT CHECK (notification_type IN ('buy_signal','sell_signal','hidden_gem','macro_alert','system')),
    title           TEXT NOT NULL,
    body            TEXT,
    is_read         BOOLEAN DEFAULT FALSE,
    sent_email      BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Backtest results (pre-computed, stored for display)
CREATE TABLE IF NOT EXISTS public.backtest_cache (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy        TEXT NOT NULL,                 -- 'conviction_bah', 'rotation'
    period_label    TEXT NOT NULL,                 -- '12M', '52W'
    metrics         JSONB NOT NULL,
    computed_at     TIMESTAMPTZ DEFAULT NOW()
);

-- RLS Policies
ALTER TABLE public.users     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.holdings  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users see own data" ON public.users
    FOR ALL USING (auth.uid() = id);

CREATE POLICY "Users manage own holdings" ON public.holdings
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Users see own notifications" ON public.notifications
    FOR ALL USING (auth.uid() = user_id);

-- Signal log and backtest cache are public read
CREATE POLICY "Signal log public read" ON public.signal_log
    FOR SELECT USING (true);

CREATE POLICY "Backtest cache public read" ON public.backtest_cache
    FOR SELECT USING (true);
