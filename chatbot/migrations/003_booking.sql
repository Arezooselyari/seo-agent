-- افزودن رزرو تقویمی (تاریخ+ساعت) به درخواست‌های مشاوره‌ی موجود.
-- جدول‌های ۰۰۲ را دست‌نخورده نگه می‌دارد؛ فقط دو ستون و دو ایندکس اضافه می‌کند.
-- این فایل را یک‌بار در SQL Editor همان پروژه‌ی Supabase ریشه اجرا کن.

alter table consultation_requests
  add column if not exists booking_date date,
  add column if not exists booking_time text;

-- جلوگیری از رزرو دوبل همان تاریخ/ساعت (فقط رزروهای واقعی و لغونشده)
create unique index if not exists uq_booking_slot
  on consultation_requests (tenant_id, booking_date, booking_time)
  where booking_date is not null and status <> 'cancelled';

create index if not exists idx_booking_date
  on consultation_requests (tenant_id, booking_date);
