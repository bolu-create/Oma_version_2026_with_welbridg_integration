-- Label each chat exchange with the channel it happened on, so the web chat
-- can show which messages came from WhatsApp. Existing rows are all WhatsApp.
-- Backward compatible: code that doesn't set the column gets the default.
ALTER TABLE oma_chat_history
  ADD COLUMN channel VARCHAR(16) NOT NULL DEFAULT 'whatsapp';
