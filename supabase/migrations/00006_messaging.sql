-- Email identities: per-user sender profiles (not auth email)
CREATE TABLE IF NOT EXISTS email_identities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  display_name TEXT,
  email_address TEXT NOT NULL,
  is_primary BOOLEAN DEFAULT FALSE,
  status TEXT NOT NULL DEFAULT 'pending_verification', -- pending_verification | verified | disabled
  provider_identity_id TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, email_address)
);

-- Lead messages: outbound/inbound messages linked to leads
CREATE TABLE IF NOT EXISTS lead_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  direction TEXT NOT NULL DEFAULT 'outbound', -- outbound | inbound (future)
  subject TEXT,
  body_text TEXT,
  body_html TEXT,
  from_identity_id UUID REFERENCES email_identities(id) ON DELETE SET NULL,
  to_email TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued', -- queued | sent | failed
  provider_message_id TEXT,
  sent_at TIMESTAMPTZ,
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_lead_messages_lead_id ON lead_messages(lead_id);
CREATE INDEX IF NOT EXISTS idx_lead_messages_user_id_created_at ON lead_messages(user_id, created_at DESC);

-- RLS
ALTER TABLE email_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE lead_messages ENABLE ROW LEVEL SECURITY;

-- Policies: users see only their own data
CREATE POLICY "email_identities_own" ON email_identities FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "lead_messages_own" ON lead_messages FOR ALL USING (
  auth.uid() = user_id
);

-- updated_at trigger for email_identities
CREATE OR REPLACE FUNCTION set_email_identities_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS email_identities_updated ON email_identities;
CREATE TRIGGER email_identities_updated
BEFORE UPDATE ON email_identities
FOR EACH ROW
EXECUTE PROCEDURE set_email_identities_updated_at();

