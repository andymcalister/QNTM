-- ============================================================
-- QNTM — California Automatic Renewal Law (AB 2863) compliance
-- Run in the Supabase SQL editor.
--
-- FLAG FOR ATTORNEY REVIEW: implements the recordkeeping required by
-- Bus. & Prof. Code §17602(a)(6) and the notice log under §17602(g)/(h).
-- Confirm retention and content with fintech counsel before taking paying users.
-- ============================================================

-- 1. Affirmative-consent artifact (§17602(a)(6)). One row per paid-subscription
--    signup. Append-only — never updated or deleted. Retain >= 3 years, or
--    1 year after termination, whichever is longer.
create table if not exists arl_consent_log (
    id             uuid primary key default gen_random_uuid(),
    user_id        text not null,
    created_at     timestamptz not null default now(),
    plan           text not null,
    trial_terms    text not null,          -- e.g. "7-day free trial"
    renewal_price  text not null,          -- e.g. "$29.00/month"
    disclosure_text text not null,         -- exact 1A block shown
    checkbox_text  text not null,          -- exact 1B label shown
    terms_version  text not null,
    ip_address     text
);

-- 2. Notice log (§17602(g)/(h) + acknowledgment + cancellation confirmation).
--    Append-only audit of every compliance email sent.
create table if not exists notices_sent (
    id              uuid primary key default gen_random_uuid(),
    user_id         text not null,
    notice_type     text not null,         -- acknowledgment | annual_reminder |
                                           -- price_change | material_change |
                                           -- cancellation_confirmation
    created_at      timestamptz not null default now(),
    content_version text not null,
    delivered       boolean not null default false  -- false while send is stubbed
);

-- Block UPDATE/DELETE on both tables (append-only).
create or replace function _qntm_block_arl_mutation()
returns trigger language plpgsql as $$
begin
    raise exception '% is append-only; % not allowed', tg_table_name, tg_op;
end;
$$;

drop trigger if exists trg_arl_consent_no_update on arl_consent_log;
drop trigger if exists trg_arl_consent_no_delete on arl_consent_log;
create trigger trg_arl_consent_no_update before update on arl_consent_log
    for each row execute function _qntm_block_arl_mutation();
create trigger trg_arl_consent_no_delete before delete on arl_consent_log
    for each row execute function _qntm_block_arl_mutation();

drop trigger if exists trg_notices_no_update on notices_sent;
drop trigger if exists trg_notices_no_delete on notices_sent;
create trigger trg_notices_no_update before update on notices_sent
    for each row execute function _qntm_block_arl_mutation();
create trigger trg_notices_no_delete before delete on notices_sent
    for each row execute function _qntm_block_arl_mutation();

-- Index for the annual-reminder cron (find subscribers due a notice).
create index if not exists idx_notices_user_type on notices_sent (user_id, notice_type, created_at desc);
