-- Enforce camp and clinic participant limits atomically, per session.
-- Run against the existing booking database before deploying the matching app code.
begin;

create or replace function public.reserve_camp_registration(
    p_id uuid,
    p_offering_id uuid,
    p_session_label text,
    p_price_label text,
    p_amount_cents bigint,
    p_guardian_name text,
    p_guardian_email text,
    p_guardian_phone text,
    p_participant_name text,
    p_participant_grade text
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_capacity integer;
    v_enrolled bigint;
begin
    -- Serialize registration attempts for this program so concurrent checkouts
    -- cannot reserve the last seat more than once.
    select o.capacity
      into v_capacity
      from public.offerings as o
     where o.id = p_offering_id
       and o.category in ('camp', 'clinic')
       and o.published
       and not o.archived
     for update;

    if not found then
        raise exception 'Camp or clinic is not accepting registrations.' using errcode = 'P0002';
    end if;

    -- A retry with the same idempotency key must not reserve a second seat.
    if exists (
        select 1 from public.camp_registrations as r where r.request_id = p_id
    ) then
        return;
    end if;

    if v_capacity is not null then
        select count(*)
          into v_enrolled
          from public.camp_registrations as r
         where r.offering_id = p_offering_id
           and r.session_label = p_session_label
           and r.status in ('awaiting_payment', 'paid');

        if v_enrolled >= v_capacity then
            raise exception 'Camp session is full.' using errcode = 'P0001';
        end if;
    end if;

    insert into public.camp_registrations (
        id, request_id, offering_id, session_label, price_label, amount_cents,
        guardian_name, guardian_email, guardian_phone, participant_name,
        participant_grade, waiver_confirmed
    ) values (
        p_id, p_id, p_offering_id, p_session_label, p_price_label, p_amount_cents,
        p_guardian_name, p_guardian_email, p_guardian_phone, p_participant_name,
        p_participant_grade, true
    );
end;
$$;

revoke all on function public.reserve_camp_registration(
    uuid, uuid, text, text, bigint, text, text, text, text, text
) from public, anon, authenticated;
grant execute on function public.reserve_camp_registration(
    uuid, uuid, text, text, bigint, text, text, text, text, text
) to service_role;

commit;
