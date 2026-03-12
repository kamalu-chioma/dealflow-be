-- Lead discovery feedback (per-user) to avoid repeats and persist interest decisions
CREATE TABLE IF NOT EXISTS lead_discovery_feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  website_url TEXT NOT NULL,
  domain TEXT NOT NULL,
  company_name TEXT,
  decision TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Constraints
ALTER TABLE lead_discovery_feedback
  ADD CONSTRAINT lead_discovery_feedback_decision_check
  CHECK (decision IN ('interested', 'not_interested'));

-- RLS
ALTER TABLE lead_discovery_feedback ENABLE ROW LEVEL SECURITY;
CREATE POLICY "lead_discovery_feedback_own" ON lead_discovery_feedback FOR ALL USING (auth.uid() = user_id);

-- Indexes
CREATE INDEX IF NOT EXISTS lead_discovery_feedback_user_id_idx ON lead_discovery_feedback(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS lead_discovery_feedback_user_domain_uniq ON lead_discovery_feedback(user_id, domain);

