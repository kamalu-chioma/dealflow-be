-- Company profile (one per user) for tailoring AI comparisons/analysis
CREATE TABLE IF NOT EXISTS company_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  company_name TEXT,
  website_url TEXT,
  industry TEXT,
  geography TEXT,
  description TEXT,
  offerings TEXT,
  ideal_customer_profile TEXT,
  target_sectors TEXT,
  constraints TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id)
);

-- RLS
ALTER TABLE company_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "company_profiles_own" ON company_profiles FOR ALL USING (auth.uid() = user_id);

-- Updated_at trigger
DROP TRIGGER IF EXISTS company_profiles_updated ON company_profiles;
CREATE TRIGGER company_profiles_updated BEFORE UPDATE ON company_profiles FOR EACH ROW EXECUTE PROCEDURE set_updated_at();

