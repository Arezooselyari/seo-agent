-- Schema چت‌بات — این فایل را یک‌بار در SQL Editor همان پروژه‌ی Supabase ریشه اجرا کن.
-- جدول‌های موتور SEO (001_init.sql) را لمس نمی‌کند؛ فقط جدول‌های جدید اضافه می‌شود.

create extension if not exists vector;

-- ──────────────────────────────────────────
-- مکالمات و پیام‌ها (حافظه‌ی کوتاه‌مدت)
-- ──────────────────────────────────────────
create table if not exists conversations (
    id               bigint generated always as identity primary key,
    tenant_id        bigint not null default 1,
    channel          text   not null,  -- telegram | web | widget
    external_user_id text   not null,  -- tg:<chat_id> | web:<uuid> | widget:<site_key>:<uuid>
    started_at       timestamptz not null default now(),
    last_active_at   timestamptz not null default now(),
    status           text not null default 'active'
);
create index if not exists idx_conversations_identity
    on conversations (tenant_id, channel, external_user_id, status);

create table if not exists messages (
    id              bigint generated always as identity primary key,
    tenant_id       bigint not null default 1,
    conversation_id bigint not null references conversations (id),
    role            text   not null,  -- user | model | tool
    content         text,
    tool_calls      jsonb,
    tool_results    jsonb,
    created_at      timestamptz not null default now()
);
create index if not exists idx_messages_conversation
    on messages (conversation_id, created_at);

-- ──────────────────────────────────────────
-- حافظه‌ی بلندمدت — یک ردیف به ازای هر external_user_id
-- ──────────────────────────────────────────
create table if not exists user_profiles (
    id                bigint generated always as identity primary key,
    tenant_id         bigint not null default 1,
    external_user_id  text   not null,
    display_name      text,
    phone             text,
    summary           text,
    facts             jsonb not null default '[]',
    updated_at        timestamptz not null default now(),
    unique (tenant_id, external_user_id)
);

-- ──────────────────────────────────────────
-- پایگاه دانش RAG — محتوای وردپرس
-- ──────────────────────────────────────────
create table if not exists kb_documents (
    id           bigint generated always as identity primary key,
    tenant_id    bigint not null default 1,
    source_type  text   not null default 'wordpress',
    wp_id        bigint,
    wp_type      text,   -- post | page
    url          text,
    title        text,
    content_hash text,
    fetched_at   timestamptz not null default now(),
    unique (tenant_id, wp_type, wp_id)
);

create table if not exists kb_chunks (
    id           bigint generated always as identity primary key,
    tenant_id    bigint not null default 1,
    document_id  bigint not null references kb_documents (id) on delete cascade,
    chunk_index  int    not null,
    content      text   not null,
    embedding    vector(768),
    token_count  int
);
create index if not exists idx_kb_chunks_document on kb_chunks (document_id);
create index if not exists idx_kb_chunks_embedding
    on kb_chunks using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- ──────────────────────────────────────────
-- لید و وضعیت درخواست مشاوره
-- ──────────────────────────────────────────
create table if not exists leads (
    id              bigint generated always as identity primary key,
    tenant_id       bigint not null default 1,
    conversation_id bigint references conversations (id),
    name            text,
    phone           text,
    topic           text,
    message         text,
    reference_code  text unique,
    created_at      timestamptz not null default now()
);

-- status: pending -> contacted -> done (یا cancelled)
create table if not exists consultation_requests (
    id             bigint generated always as identity primary key,
    tenant_id      bigint not null default 1,
    lead_id        bigint references leads (id),
    reference_code text unique,
    phone          text,
    status         text not null default 'pending',
    notes          text,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);
create index if not exists idx_consultation_phone on consultation_requests (tenant_id, phone);
create index if not exists idx_consultation_status on consultation_requests (tenant_id, status);

-- ──────────────────────────────────────────
-- جست‌وجوی برداری — supabase-py نمی‌تواند عملگر <=> را مستقیم صدا بزند،
-- پس از طریق یک تابع SQL و client.rpc(...) فراخوانی می‌شود.
-- ──────────────────────────────────────────
create or replace function match_kb_chunks(
    query_embedding vector(768),
    match_tenant_id bigint,
    match_count int default 5
) returns table (
    chunk_id    bigint,
    document_id bigint,
    content     text,
    similarity  float,
    url         text,
    title       text
)
language sql stable as $$
    select c.id, c.document_id, c.content,
           1 - (c.embedding <=> query_embedding) as similarity,
           d.url, d.title
    from kb_chunks c
    join kb_documents d on d.id = c.document_id
    where c.tenant_id = match_tenant_id
    order by c.embedding <=> query_embedding
    limit match_count;
$$;
