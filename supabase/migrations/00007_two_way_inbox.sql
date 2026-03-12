-- Two-way inbox: threading and reply-only inbound
-- Add columns to lead_messages for Message-ID tracking and inbound sender

ALTER TABLE lead_messages
  ADD COLUMN IF NOT EXISTS email_message_id TEXT,
  ADD COLUMN IF NOT EXISTS in_reply_to_message_id UUID REFERENCES lead_messages(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS from_email TEXT;

-- status already supports: queued | sent | failed; add pending_approval as valid value (no constraint change)
-- Index for matching inbound replies by In-Reply-To
CREATE INDEX IF NOT EXISTS idx_lead_messages_email_message_id ON lead_messages(email_message_id)
  WHERE email_message_id IS NOT NULL;

-- Index for thread lookups
CREATE INDEX IF NOT EXISTS idx_lead_messages_in_reply_to ON lead_messages(in_reply_to_message_id)
  WHERE in_reply_to_message_id IS NOT NULL;
