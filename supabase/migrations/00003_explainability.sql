-- Explainability and opportunity score for lead_analyses
ALTER TABLE lead_analyses
  ADD COLUMN IF NOT EXISTS fit_reasoning TEXT,
  ADD COLUMN IF NOT EXISTS risk_reasoning TEXT,
  ADD COLUMN IF NOT EXISTS top_evidence_signals JSONB DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS confidence_reasoning TEXT,
  ADD COLUMN IF NOT EXISTS opportunity_score INTEGER;
