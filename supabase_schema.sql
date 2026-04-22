create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  role text not null default 'staff' check (role in ('manager', 'staff')),
  created_at timestamptz not null default now()
);

create table if not exists public.inventory (
  id bigint generated always as identity primary key,
  location text not null,
  item text not null,
  qty integer not null default 0,
  updated_at timestamptz not null default now(),
  unique (location, item)
);

create table if not exists public.movements (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  action text not null,
  from_location text not null,
  to_location text not null,
  item text not null,
  qty integer not null,
  user_id uuid references public.profiles(id)
);

create table if not exists public.signup_allowed_emails (
  email text primary key,
  added_by uuid references public.profiles(id),
  created_at timestamptz not null default now()
);

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

create or replace function public.is_manager()
returns boolean
language sql
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.profiles
    where id = auth.uid() and role = 'manager'
  );
$$;

create or replace function public.is_signup_email_allowed(p_email text)
returns boolean
language sql
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.signup_allowed_emails
    where email = lower(trim(p_email))
  );
$$;

create or replace function public.add_signup_allowed_email(p_email text)
returns text
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.is_manager() then
    raise exception 'Only managers can allow signup emails';
  end if;

  insert into public.signup_allowed_emails (email, added_by)
  values (lower(trim(p_email)), auth.uid())
  on conflict (email) do update
  set added_by = excluded.added_by;

  return 'Email approved for signup';
end;
$$;

create or replace function public.remove_signup_allowed_email(p_email text)
returns text
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.is_manager() then
    raise exception 'Only managers can remove signup emails';
  end if;

  delete from public.signup_allowed_emails
  where email = lower(trim(p_email));

  return 'Email removed from signup allowlist';
end;
$$;

create or replace function public.list_signup_allowed_emails()
returns table (email text, created_at timestamptz)
language sql
security definer
set search_path = public
as $$
  select s.email, s.created_at
  from public.signup_allowed_emails s
  where public.is_manager()
  order by s.email;
$$;

create or replace function public.add_stock(
  p_location text,
  p_item text,
  p_qty integer
)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  current_qty integer;
begin
  if not public.is_manager() then
    raise exception 'Only managers can add stock';
  end if;

  if p_qty <= 0 then
    raise exception 'Quantity must be greater than 0';
  end if;

  select qty into current_qty
  from public.inventory
  where location = p_location and item = p_item;

  insert into public.inventory (location, item, qty, updated_at)
  values (p_location, p_item, coalesce(current_qty, 0) + p_qty, now())
  on conflict (location, item)
  do update set
    qty = public.inventory.qty + excluded.qty,
    updated_at = now();

  insert into public.movements (
    action, from_location, to_location, item, qty, user_id, created_at
  )
  values ('Add', '-', p_location, p_item, p_qty, auth.uid(), now());

  return format('Added %s %s to %s.', p_qty, p_item, p_location);
end;
$$;

create or replace function public.transfer_inventory(
  p_from_location text,
  p_to_location text,
  p_item text,
  p_qty integer
)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  from_qty integer;
begin
  if auth.uid() is null then
    raise exception 'Authentication required';
  end if;

  if p_qty <= 0 then
    raise exception 'Quantity must be greater than 0';
  end if;

  select qty into from_qty
  from public.inventory
  where location = p_from_location and item = p_item;

  if coalesce(from_qty, 0) < p_qty then
    raise exception 'Not enough stock in %', p_from_location;
  end if;

  update public.inventory
  set qty = qty - p_qty, updated_at = now()
  where location = p_from_location and item = p_item;

  insert into public.inventory (location, item, qty, updated_at)
  values (p_to_location, p_item, p_qty, now())
  on conflict (location, item)
  do update set
    qty = public.inventory.qty + excluded.qty,
    updated_at = now();

  insert into public.movements (
    action, from_location, to_location, item, qty, user_id, created_at
  )
  values ('Transfer', p_from_location, p_to_location, p_item, p_qty, auth.uid(), now());

  return format('Moved %s %s from %s to %s.', p_qty, p_item, p_from_location, p_to_location);
end;
$$;

alter table public.profiles enable row level security;
alter table public.inventory enable row level security;
alter table public.movements enable row level security;
alter table public.signup_allowed_emails enable row level security;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own"
on public.profiles
for select
to authenticated
using (id = auth.uid());

drop policy if exists "inventory_read_authenticated" on public.inventory;
create policy "inventory_read_authenticated"
on public.inventory
for select
to authenticated
using (true);

drop policy if exists "movement_read_authenticated" on public.movements;
create policy "movement_read_authenticated"
on public.movements
for select
to authenticated
using (true);

drop policy if exists "signup_allowlist_manager_select" on public.signup_allowed_emails;
create policy "signup_allowlist_manager_select"
on public.signup_allowed_emails
for select
to authenticated
using (public.is_manager());

grant execute on function public.add_stock(text, text, integer) to authenticated;
grant execute on function public.transfer_inventory(text, text, text, integer) to authenticated;
grant execute on function public.is_signup_email_allowed(text) to anon, authenticated;
grant execute on function public.add_signup_allowed_email(text) to authenticated;
grant execute on function public.remove_signup_allowed_email(text) to authenticated;
grant execute on function public.list_signup_allowed_emails() to authenticated;

-- Run this once in Supabase SQL editor to promote your own account:
-- update public.profiles
-- set role = 'manager'
-- where email = 'your-email@example.com';
