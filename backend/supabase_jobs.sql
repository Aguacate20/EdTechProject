-- v3.12 · estado de los trabajos de extracción (sobrevive al reinicio del Space)
create table if not exists jobs (
  id text primary key,
  status text,
  student_id text,
  course_id text,
  error text,
  filename text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
