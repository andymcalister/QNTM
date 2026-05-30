-- ============================================================
-- QNTM — Atomic, simultaneous signal publishing  (Part 1)
-- Run in the Supabase SQL editor.
--
-- FLAG FOR ATTORNEY REVIEW: this implements the technical posture
-- described in the compliance task (atomic batch, published_at bright
-- line, append-only audit log). Confirm with fintech counsel before launch.
-- ============================================================

-- 1. Batch identity + publish timestamp on signal_log
alter table signal_log
    add column if not exists batch_id     uuid,
    add column if not exists published_at timestamptz;

-- 2. Immutable, append-only audit log — one row per published batch.
--    No updates/deletes permitted (enforced by trigger below).
create table if not exists signal_batch_audit (
    batch_id      uuid primary key,
    published_at  timestamptz not null,
    signal_date   date not null,
    ticker_count  integer not null,
    tickers       jsonb not null,         -- ordered ticker list
    signals       jsonb not null,         -- {ticker: {adj_composite, signal, ...}}
    content_hash  text not null,          -- sha256 of the canonical batch payload
    created_at    timestamptz not null default now()
);

-- Block UPDATE and DELETE on the audit table (append-only).
create or replace function _qntm_block_audit_mutation()
returns trigger language plpgsql as $$
begin
    raise exception 'signal_batch_audit is append-only; % not allowed', tg_op;
end;
$$;

drop trigger if exists trg_audit_no_update on signal_batch_audit;
drop trigger if exists trg_audit_no_delete on signal_batch_audit;
create trigger trg_audit_no_update before update on signal_batch_audit
    for each row execute function _qntm_block_audit_mutation();
create trigger trg_audit_no_delete before delete on signal_batch_audit
    for each row execute function _qntm_block_audit_mutation();

-- 3. Atomic publish RPC.
--    Replaces the whole day's batch and writes the audit row in ONE
--    transaction. If anything raises, the function aborts and Postgres
--    rolls the entire transaction back — users never see a partial batch.
--
--    p_rows: jsonb array of signal_log row objects (must include ticker,
--            signal_date, composite, adj_composite, etc.)
--    Returns the published_at timestamp.
create or replace function publish_signal_batch(
    p_batch_id     uuid,
    p_signal_date  date,
    p_rows         jsonb,
    p_content_hash text
)
returns timestamptz
language plpgsql
as $$
declare
    v_now timestamptz := now();
    v_row jsonb;
begin
    -- Atomic swap: delete the prior batch for this date, insert the new one.
    delete from signal_log where signal_date = p_signal_date;

    for v_row in select * from jsonb_array_elements(p_rows)
    loop
        insert into signal_log (
            ticker, signal_date, composite, momentum, quality, volume,
            value, sentiment, signal, macro_overlay, adj_composite, price,
            is_hidden_gem, hidden_gem_reason, batch_id, published_at, created_at
        ) values (
            v_row->>'ticker',
            p_signal_date,
            (v_row->>'composite')::numeric,
            (v_row->>'momentum')::numeric,
            (v_row->>'quality')::numeric,
            (v_row->>'volume')::numeric,
            (v_row->>'value')::numeric,
            (v_row->>'sentiment')::numeric,
            v_row->>'signal',
            (v_row->>'macro_overlay')::numeric,
            (v_row->>'adj_composite')::numeric,
            nullif(v_row->>'price','')::numeric,
            coalesce((v_row->>'is_hidden_gem')::boolean, false),
            v_row->>'hidden_gem_reason',
            p_batch_id,
            v_now,
            v_now
        );
    end loop;

    -- Audit row in the same transaction.
    insert into signal_batch_audit (
        batch_id, published_at, signal_date, ticker_count,
        tickers, signals, content_hash
    ) values (
        p_batch_id, v_now, p_signal_date,
        jsonb_array_length(p_rows),
        (select jsonb_agg(r->>'ticker') from jsonb_array_elements(p_rows) r),
        p_rows,
        p_content_hash
    );

    return v_now;
end;
$$;
