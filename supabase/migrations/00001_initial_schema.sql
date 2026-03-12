-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Profiles (user onboarding)
CREATE TABLE IF NOT EXISTS profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  user_type TEXT,
  goal TEXT,
  preferred_sector TEXT,
  preferred_geography TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id)
);

-- Leads
CREATE TABLE IF NOT EXISTS leads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  company_name TEXT NOT NULL,
  website_url TEXT NOT NULL,
  geography TEXT,
  industry TEXT,
  note TEXT,
  lead_status TEXT DEFAULT 'New Lead',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Lead analyses (one per run; we take latest)
CREATE TABLE IF NOT EXISTS lead_analyses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  company_summary TEXT,
  offering_summary TEXT,
  sector_guess TEXT,
  geography_guess TEXT,
  fit_score INTEGER,
  risk_score INTEGER,
  confidence_score INTEGER,
  recommendation TEXT,
  recommendation_reason TEXT,
  strengths_json JSONB DEFAULT '[]',
  red_flags_json JSONB DEFAULT '[]',
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Sources (for RAG chunks)
CREATE TABLE IF NOT EXISTS sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  source_type TEXT,
  source_url TEXT,
  title TEXT,
  raw_text TEXT,
  chunk_text TEXT,
  embedding vector(1536),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sources_lead_id ON sources(lead_id);

-- Contacts
CREATE TABLE IF NOT EXISTS contacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  contact_type TEXT,
  contact_value TEXT,
  source_url TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Notes
CREATE TABLE IF NOT EXISTS notes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Chat
CREATE TABLE IF NOT EXISTS chat_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Comparisons
CREATE TABLE IF NOT EXISTS comparisons (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  lead_a_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  lead_b_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  summary TEXT,
  preferred_lead_id UUID REFERENCES leads(id) ON DELETE SET NULL,
  tradeoff_notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- RLS
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE lead_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE comparisons ENABLE ROW LEVEL SECURITY;

-- Policies: users see only their own data
CREATE POLICY "profiles_own" ON profiles FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "leads_own" ON leads FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "lead_analyses_own" ON lead_analyses FOR ALL USING (
  EXISTS (SELECT 1 FROM leads WHERE leads.id = lead_analyses.lead_id AND leads.user_id = auth.uid())
);
CREATE POLICY "sources_own" ON sources FOR ALL USING (
  EXISTS (SELECT 1 FROM leads WHERE leads.id = sources.lead_id AND leads.user_id = auth.uid())
);
CREATE POLICY "contacts_own" ON contacts FOR ALL USING (
  EXISTS (SELECT 1 FROM leads WHERE leads.id = contacts.lead_id AND leads.user_id = auth.uid())
);
CREATE POLICY "notes_own" ON notes FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "chat_sessions_own" ON chat_sessions FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "chat_messages_own" ON chat_messages FOR ALL USING (
  EXISTS (SELECT 1 FROM chat_sessions WHERE chat_sessions.id = chat_messages.session_id AND chat_sessions.user_id = auth.uid())
);
CREATE POLICY "comparisons_own" ON comparisons FOR ALL USING (auth.uid() = user_id);

-- Updated_at trigger for profiles and leads
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS profiles_updated ON profiles;
CREATE TRIGGER profiles_updated BEFORE UPDATE ON profiles FOR EACH ROW EXECUTE PROCEDURE set_updated_at();
DROP TRIGGER IF EXISTS leads_updated ON leads;
CREATE TRIGGER leads_updated BEFORE UPDATE ON leads FOR EACH ROW EXECUTE PROCEDURE set_updated_at();
