-- ---------------------------------------------------------------------------
-- CRM: ساعات کاری، مرخصی/تعطیلی، خدمات و پروفایل مشتری
--
-- منبع حقیقتِ ساعات کاری از chatbot/config.yaml به این جدول‌ها منتقل می‌شود
-- تا صاحب کسب‌وکار بتواند از پنل CRM تغییرشان بدهد، بدون ویرایش فایل و ری‌استارت.
--
-- این فایل را یک‌بار در SQL Editor پروژه‌ی Supabase چت‌بات اجرا کن
-- (همان پروژه‌ای که 002 و 003 در آن اجرا شده‌اند).
-- ---------------------------------------------------------------------------


-- ===========================================================================
-- ۱) ساعات کاری هفتگی
-- ===========================================================================
-- weekday طبق قرارداد پایتون date.weekday():
--   0=دوشنبه  1=سه‌شنبه  2=چهارشنبه  3=پنج‌شنبه  4=جمعه  5=شنبه  6=یکشنبه
-- عمداً همین قرارداد نگه داشته شده تا در booking.py هیچ تبدیلی لازم نباشد
-- (منبع باگ‌های off-by-one). ترتیب نمایش شنبه‌محور در لایه‌ی UI اعمال می‌شود.
create table if not exists availability_rules (
  id         bigint generated always as identity primary key,
  tenant_id  bigint   not null default 1,
  weekday    smallint not null check (weekday between 0 and 6),
  is_open    boolean  not null default false,
  start_time text     not null default '09:00',
  end_time   text     not null default '17:00',
  updated_at timestamptz not null default now(),
  unique (tenant_id, weekday)
);


-- ===========================================================================
-- ۲) استثناها — مرخصی/تعطیلی یا ساعت متفاوت برای روز(های) خاص
-- ===========================================================================
-- kind = 'closed'       → آن بازه کلاً بسته است (مرخصی، تعطیلی رسمی، سفر)
-- kind = 'custom_hours' → آن بازه باز است ولی با ساعتی غیر از ساعت هفتگی
-- تک‌روز = start_date برابر end_date. بازه‌ی چندروزه = end_date بزرگ‌تر.
-- استثنا همیشه بر availability_rules اولویت دارد.
create table if not exists availability_exceptions (
  id         bigint generated always as identity primary key,
  tenant_id  bigint not null default 1,
  start_date date   not null,
  end_date   date   not null,
  kind       text   not null default 'closed' check (kind in ('closed', 'custom_hours')),
  start_time text,
  end_time   text,
  reason     text,
  created_at timestamptz not null default now(),
  check (end_date >= start_date),
  -- ساعت سفارشی بدون ساعت شروع/پایان بی‌معنی است
  check (kind <> 'custom_hours' or (start_time is not null and end_time is not null))
);

create index if not exists idx_avail_exc_range
  on availability_exceptions (tenant_id, start_date, end_date);


-- ===========================================================================
-- ۳) تنظیمات عمومی رزرو — جایگزین بخش booking در config.yaml
-- ===========================================================================
create table if not exists booking_settings (
  tenant_id        bigint primary key,
  enabled          boolean not null default true,
  slot_minutes     int     not null default 30,
  timezone         text    not null default 'Asia/Tehran',
  min_notice_hours int     not null default 2,
  max_advance_days int     not null default 60,
  updated_at       timestamptz not null default now()
);


-- ===========================================================================
-- ۴) خدمات و قیمت‌ها
-- ===========================================================================
create table if not exists services (
  id               bigint generated always as identity primary key,
  tenant_id        bigint  not null default 1,
  name             text    not null,
  description      text,
  duration_minutes int     not null default 30,
  price_toman      bigint,
  active           boolean not null default true,
  sort_order       int     not null default 0,
  created_at       timestamptz not null default now()
);

create index if not exists idx_services_active
  on services (tenant_id, active, sort_order);


-- ===========================================================================
-- ۵) پروفایل مشتری — کلید یکتا شماره تماس است
-- ===========================================================================
-- leads هر بار یک ردیف جدید می‌سازد؛ این جدول یک نمای واحد از هر شخص می‌دهد
-- تا یادداشت و سابقه‌اش در طول زمان جمع شود.
create table if not exists customers (
  id         bigint generated always as identity primary key,
  tenant_id  bigint not null default 1,
  phone      text   not null,
  name       text,
  email      text,
  notes      text,
  tags       jsonb  not null default '[]',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, phone)
);


-- ===========================================================================
-- ۶) افزودن ستون به جدول‌های موجود
-- ===========================================================================
alter table consultation_requests
  add column if not exists service_id       bigint references services (id),
  add column if not exists reminder_sent_at timestamptz;

alter table leads
  add column if not exists email text;


-- ===========================================================================
-- ۷) Seed — دقیقاً معادل مقادیر فعلی config.yaml
-- ===========================================================================
-- هدف: بلافاصله بعد از اجرای این مایگریشن رفتار صفحه‌ی رزرو هیچ تغییری نکند.
-- config.yaml: شنبه تا چهارشنبه ۰۹:۰۰–۱۷:۰۰ باز، پنج‌شنبه و جمعه بسته،
--              اسلات ۳۰ دقیقه، Asia/Tehran، حداقل ۲ ساعت فاصله.

insert into booking_settings (tenant_id, enabled, slot_minutes, timezone, min_notice_hours, max_advance_days)
values (1, true, 30, 'Asia/Tehran', 2, 60)
on conflict (tenant_id) do nothing;

insert into availability_rules (tenant_id, weekday, is_open, start_time, end_time)
values
  (1, 5, true,  '09:00', '17:00'),  -- شنبه
  (1, 6, true,  '09:00', '17:00'),  -- یکشنبه
  (1, 0, true,  '09:00', '17:00'),  -- دوشنبه
  (1, 1, true,  '09:00', '17:00'),  -- سه‌شنبه
  (1, 2, true,  '09:00', '17:00'),  -- چهارشنبه
  (1, 3, false, '09:00', '17:00'),  -- پنج‌شنبه (بسته)
  (1, 4, false, '09:00', '17:00')   -- جمعه (بسته)
on conflict (tenant_id, weekday) do nothing;
