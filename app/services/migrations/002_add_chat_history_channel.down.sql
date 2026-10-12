-- Removes the channel label (the web/WhatsApp distinction is lost).
ALTER TABLE oma_chat_history DROP COLUMN channel;
