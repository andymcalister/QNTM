-- QNTM analytics event mirror.
-- Lightweight server-side copy of PostHog events so the internal dashboard can
-- show core metrics without calling the PostHog API.
--
-- RLS posture: the running app may connect with the anon key, so INSERT is open
-- (event logging must never fail), but SELECT is restricted to the service role
-- — normal users / the anon key cannot read analytics. The admin dashboard reads
-- via _get_supabase(), which uses the service key in the deployed app.

create table if not exists public.qntm_events (
    id           bigint generated always as identity primary key,
    event        text not null,
    distinct_id  text,
    utm_source   text,
    utm_medium   text,
    utm_campaign text,
    referrer     text,
    properties   jsonb,
    created_at   timestamptz not null default now()
);

create index if not exists qntm_events_event_idx      on public.qntm_events (event);
create index if not exists qntm_events_created_at_idx  on public.qntm_events (created_at desc);
create index if not exists qntm_events_distinct_idx    on public.qntm_events (distinct_id);

alter table public.qntm_events enable row level security;

-- Logging is allowed for everyone (so a missing service key never drops events)…
drop policy if exists qntm_events_insert on public.qntm_events;
create policy qntm_events_insert on public.qntm_events
    for insert to anon, authenticated, service_role with check (true);

-- …but reads are service-role only. No anon/authenticated SELECT policy exists,
-- so RLS blocks reads for them. (service_role bypasses RLS; this is explicit.)
drop policy if exists qntm_events_select_service on public.qntm_events;
create policy qntm_events_select_service on public.qntm_events
    for select to service_role using (true);
