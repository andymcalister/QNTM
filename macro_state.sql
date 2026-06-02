-- QNTM — macro_state table
-- Run ONCE in the Supabase SQL editor (Dashboard → SQL Editor → New query → paste → Run).
-- Stores the latest live macro overlay as a single row so the macro pass, the
-- intraday pass, and the app all read one source of truth.

CREATE TABLE IF NOT EXISTS public.macro_state (
    id          INT PRIMARY KEY DEFAULT 1,
    overlay     JSONB NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT macro_state_singleton CHECK (id = 1)
);

ALTER TABLE public.macro_state ENABLE ROW LEVEL SECURITY;

-- Public read so the app can show the live regime via the anon key.
-- Writes happen only from the refresh job using the service key (bypasses RLS).
CREATE POLICY "Macro state public read" ON public.macro_state
    FOR SELECT USING (true);
