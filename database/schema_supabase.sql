-- StudyFlow AI - Schema Supabase
-- Rode no Supabase SQL Editor. Mantenha RLS desligado durante o desenvolvimento.

create extension if not exists "pgcrypto";
create extension if not exists "uuid-ossp";

create table if not exists public.profiles (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    email text unique not null,
    password_hash text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.notebooks (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.profiles(id) on delete cascade,
    title text not null default 'Notebook sem título',
    description text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.documents (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.profiles(id) on delete cascade,
    notebook_id uuid not null references public.notebooks(id) on delete cascade,
    filename text not null,
    original_filename text not null,
    file_type text not null,
    file_size bigint not null default 0,
    storage_bucket text default 'documents',
    storage_path text,
    local_path text,
    status text not null default 'processing',
    error_message text,
    character_count integer not null default 0,
    chunk_count integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint documents_status_check check (status in ('processing', 'processed', 'empty', 'error'))
);

create table if not exists public.document_chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.documents(id) on delete cascade,
    notebook_id uuid not null references public.notebooks(id) on delete cascade,
    user_id uuid not null references public.profiles(id) on delete cascade,
    chunk_index integer not null,
    content text not null,
    page_number integer,
    character_count integer not null default 0,
    created_at timestamptz not null default now(),
    unique(document_id, chunk_index)
);

create table if not exists public.chat_messages (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.profiles(id) on delete cascade,
    notebook_id uuid not null references public.notebooks(id) on delete cascade,
    role text not null,
    content text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint chat_messages_role_check check (role in ('user', 'assistant', 'system', 'tool'))
);

create table if not exists public.generated_materials (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.profiles(id) on delete cascade,
    notebook_id uuid not null references public.notebooks(id) on delete cascade,
    document_id uuid references public.documents(id) on delete set null,
    type text not null,
    title text not null,
    content text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint generated_materials_type_check check (type in ('summary','quiz','flowchart','study_plan','flashcards','quick_review','comparison','free_answer'))
);

create table if not exists public.agent_memory (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.profiles(id) on delete cascade,
    notebook_id uuid references public.notebooks(id) on delete cascade,
    memory_key text not null,
    memory_value text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(user_id, notebook_id, memory_key)
);

create index if not exists idx_notebooks_user_id on public.notebooks(user_id);
create index if not exists idx_documents_user_id on public.documents(user_id);
create index if not exists idx_documents_notebook_id on public.documents(notebook_id);
create index if not exists idx_document_chunks_document_id on public.document_chunks(document_id);
create index if not exists idx_document_chunks_notebook_id on public.document_chunks(notebook_id);
create index if not exists idx_chat_messages_notebook_id on public.chat_messages(notebook_id);
create index if not exists idx_generated_materials_notebook_id on public.generated_materials(notebook_id);
create index if not exists idx_document_chunks_content_search on public.document_chunks using gin(to_tsvector('portuguese', content));

create or replace function public.set_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists set_profiles_updated_at on public.profiles;
create trigger set_profiles_updated_at before update on public.profiles for each row execute function public.set_updated_at();
drop trigger if exists set_notebooks_updated_at on public.notebooks;
create trigger set_notebooks_updated_at before update on public.notebooks for each row execute function public.set_updated_at();
drop trigger if exists set_documents_updated_at on public.documents;
create trigger set_documents_updated_at before update on public.documents for each row execute function public.set_updated_at();
drop trigger if exists set_generated_materials_updated_at on public.generated_materials;
create trigger set_generated_materials_updated_at before update on public.generated_materials for each row execute function public.set_updated_at();
drop trigger if exists set_agent_memory_updated_at on public.agent_memory;
create trigger set_agent_memory_updated_at before update on public.agent_memory for each row execute function public.set_updated_at();

insert into storage.buckets (id, name, public)
values ('documents', 'documents', false)
on conflict (id) do nothing;

insert into public.profiles (id, name, email, password_hash)
values ('00000000-0000-0000-0000-000000000001','Usuário Teste','teste@studyflow.local','local-test-user-disabled')
on conflict (email) do nothing;

insert into public.notebooks (id, user_id, title, description)
values ('00000000-0000-0000-0000-000000000101','00000000-0000-0000-0000-000000000001','Notebook Principal','Notebook padrão criado para testes locais.')
on conflict (id) do nothing;


-- =========================================================
-- Build 10.1 compatibility patch - idempotente
-- =========================================================
alter table public.profiles alter column password_hash drop not null;
alter table public.profiles alter column password_hash set default 'local-test-user-disabled';

alter table public.documents add column if not exists original_filename text;
alter table public.documents add column if not exists storage_bucket text default 'documents';
alter table public.documents add column if not exists storage_path text;
alter table public.documents add column if not exists local_path text;
alter table public.documents add column if not exists character_count integer not null default 0;
alter table public.documents add column if not exists chunk_count integer not null default 0;
alter table public.documents add column if not exists error_message text;
alter table public.documents add column if not exists updated_at timestamptz default now();
alter table public.documents add column if not exists mime_type text;
alter table public.documents add column if not exists processed_at timestamptz;
update public.documents set original_filename = coalesce(original_filename, filename) where original_filename is null;

alter table public.document_chunks add column if not exists user_id uuid references public.profiles(id) on delete cascade;
alter table public.document_chunks add column if not exists page_number integer default 1;
alter table public.document_chunks add column if not exists character_count integer not null default 0;
alter table public.document_chunks add column if not exists metadata jsonb not null default '{}'::jsonb;
alter table public.document_chunks add column if not exists token_count integer not null default 0;

alter table public.chat_messages add column if not exists metadata jsonb not null default '{}'::jsonb;

alter table public.generated_materials add column if not exists user_id uuid references public.profiles(id) on delete cascade;
alter table public.generated_materials add column if not exists metadata jsonb not null default '{}'::jsonb;
alter table public.generated_materials add column if not exists updated_at timestamptz default now();

alter table public.agent_memory add column if not exists notebook_id uuid references public.notebooks(id) on delete cascade;
alter table public.agent_memory add column if not exists updated_at timestamptz default now();

alter table public.documents drop constraint if exists documents_status_check;
alter table public.documents add constraint documents_status_check check (status in ('processing', 'processed', 'failed', 'empty', 'error'));

alter table public.generated_materials drop constraint if exists generated_materials_type_check;
alter table public.generated_materials add constraint generated_materials_type_check check (type in ('summary','quiz','study_plan','flowchart','flashcards','quick_review','compare','comparison','explain_simple','free_answer'));
