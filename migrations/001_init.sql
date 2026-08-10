-- Schema اولیه‌ی Supabase — این فایل را یک‌بار در SQL Editor داشبورد Supabase اجرا کن.
-- همه‌ی جدول‌ها tenant_id دارند تا مهاجرت به SaaS چندکاربره بدون درد باشد.

-- منابع خبری (seed از config.yaml انجام می‌شود)
create table if not exists sources (
    id         bigint generated always as identity primary key,
    tenant_id  bigint not null default 1,
    name       text   not null,
    url        text   not null,
    type       text   not null default 'rss',
    active     boolean not null default true,
    unique (tenant_id, url)
);

-- موضوع‌های پیداشده از RSS (قبلاً جدول articles در SQLite)
-- status: new -> selected -> drafted | skipped
create table if not exists topics (
    id           bigint generated always as identity primary key,
    tenant_id    bigint not null default 1,
    source       text   not null,
    url          text   not null,
    url_hash     text   not null,
    title        text,
    summary      text,
    fetched_at   timestamptz not null,
    score        numeric,
    score_reason text,
    status       text not null default 'new',
    unique (tenant_id, url_hash)
);
create index if not exists idx_topics_status on topics (tenant_id, status, fetched_at desc);

-- خلاصه‌ی تحقیق (خروجی Research Brief — LLM دوم)
create table if not exists research_briefs (
    id                  bigint generated always as identity primary key,
    tenant_id           bigint not null default 1,
    topic_id            bigint not null references topics (id),
    summary             text,
    key_points          jsonb not null default '[]',
    claims              jsonb not null default '[]',
    angles              jsonb not null default '[]',
    hallucination_risks jsonb not null default '[]',
    created_at          timestamptz not null default now()
);

-- مقاله‌های تولیدشده (قبلاً جدول drafts در SQLite)
-- status: pending -> approved -> published | rejected
create table if not exists articles (
    id                bigint generated always as identity primary key,
    tenant_id         bigint not null default 1,
    topic_id          bigint not null references topics (id),
    research_brief_id bigint references research_briefs (id),
    title_fa          text,
    body_html         text,
    meta_description  text,
    slug              text,
    tags              jsonb not null default '[]',
    internal_links    jsonb not null default '[]',
    status            text not null default 'pending',
    created_at        timestamptz not null default now()
);
create index if not exists idx_articles_status on articles (tenant_id, status);

-- وضعیت انتشار در وردپرس
-- status: draft -> published
create table if not exists publishing (
    id           bigint generated always as identity primary key,
    tenant_id    bigint not null default 1,
    article_id   bigint not null references articles (id),
    wp_post_id   bigint,
    wp_edit_url  text,
    published_at timestamptz,
    status       text not null default 'draft'
);
create index if not exists idx_publishing_status on publishing (tenant_id, status);

-- تنظیمات هر tenant (در فاز اول یک ردیف)
create table if not exists settings (
    tenant_id            bigint primary key,
    website_url          text,
    wordpress_api_url    text,
    linkedin_profile_url text,
    language             text not null default 'fa',
    tone                 text,
    category_defaults    jsonb not null default '[]'
);
