-- ════════════════════════════════════════════════════════════════════════════
-- Migration 001 (DOWN): rollback of the outreach onboarding tables.
--
-- WARNING: dropping these tables permanently deletes the outreach whitelist and
-- any in-flight / historical vouch requests. Only run this if you really want to
-- undo migration 001.
--
-- Neither table is referenced by any other table, so drop order is unimportant.
-- ════════════════════════════════════════════════════════════════════════════

DROP TABLE IF EXISTS oma_outreach_join_requests;
DROP TABLE IF EXISTS oma_outreach_approved_contacts;
