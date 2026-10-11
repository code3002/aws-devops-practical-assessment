-- Superuser, replication and bypass-RLS default to false; existing elevation is rejected first.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'assessment_app') THEN
    CREATE ROLE assessment_app LOGIN NOCREATEDB NOCREATEROLE;
  END IF;
END $$;
ALTER ROLE assessment_app LOGIN NOCREATEDB NOCREATEROLE;
REVOKE ALL ON DATABASE assessment FROM PUBLIC;
REVOKE ALL ON DATABASE assessment FROM assessment_app;
GRANT CONNECT ON DATABASE assessment TO assessment_app;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM assessment_app;
GRANT USAGE ON SCHEMA public TO assessment_app;
CREATE TABLE IF NOT EXISTS public.messages (id BIGSERIAL PRIMARY KEY, text VARCHAR(200) NOT NULL);
REVOKE ALL ON TABLE public.messages FROM PUBLIC, assessment_app;
GRANT SELECT ON TABLE public.messages TO assessment_app;
GRANT INSERT (text) ON TABLE public.messages TO assessment_app;
REVOKE ALL ON SEQUENCE public.messages_id_seq FROM PUBLIC, assessment_app;
GRANT USAGE ON SEQUENCE public.messages_id_seq TO assessment_app;
ALTER ROLE assessment_app IN DATABASE assessment SET search_path = public;
