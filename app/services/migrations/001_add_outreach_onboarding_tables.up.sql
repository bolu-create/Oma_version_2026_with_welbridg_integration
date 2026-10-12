-- ════════════════════════════════════════════════════════════════════════════
-- Migration 001 (UP): outreach admin / field-expert onboarding
--
-- Adds two tables used by the outreach sign-up flow:
--   * oma_outreach_approved_contacts  — whitelist of pre-approved phone numbers
--   * oma_outreach_join_requests       — the "vouch" flow (an admin confirms a newcomer)
--
-- DDL is generated from the SQLAlchemy models in db.py (MySQL dialect), so it
-- matches the ORM exactly. Both statements use IF NOT EXISTS and are safe to
-- re-run. No existing table is touched.
--
-- Enum values below are IDENTICAL to the existing oma_outreach_prog_users.role
-- column, so there is no enum conflict.
-- ════════════════════════════════════════════════════════════════════════════


-- ── whitelist of pre-approved phone numbers ────────────────────────────────────
CREATE TABLE IF NOT EXISTS oma_outreach_approved_contacts (
    id            INTEGER      NOT NULL AUTO_INCREMENT,
    phone_number  VARCHAR(20)  NOT NULL,
    name          VARCHAR(255) NULL,
    role          ENUM('admin','field_expert','beneficiary') NOT NULL,
    added_by      VARCHAR(255) NULL,
    is_enrolled   TINYINT(1)   NULL,
    created_at    DATETIME     NULL,
    PRIMARY KEY (id),
    UNIQUE KEY ix_oma_outreach_approved_contacts_phone_number (phone_number)
) ENGINE=InnoDB;


-- ── join / vouch requests (also holds the conversational state) ────────────────
CREATE TABLE IF NOT EXISTS oma_outreach_join_requests (
    id                     INTEGER      NOT NULL AUTO_INCREMENT,
    requester_user_id      INTEGER      NULL,
    requester_wa_id        VARCHAR(20)  NOT NULL,
    requester_name         VARCHAR(255) NULL,
    requested_role         ENUM('admin','field_expert','beneficiary') NOT NULL,
    stage                  ENUM('awaiting_admin_details','awaiting_admin_confirmation','approved','rejected') NOT NULL,
    vouching_admin_name    VARCHAR(255) NULL,
    vouching_admin_phone   VARCHAR(20)  NULL,
    vouching_admin_user_id INTEGER      NULL,
    created_at             DATETIME     NULL,
    resolved_at            DATETIME     NULL,
    PRIMARY KEY (id),
    KEY ix_oma_outreach_join_requests_requester_user_id (requester_user_id),
    KEY ix_oma_outreach_join_requests_requester_wa_id (requester_wa_id),
    KEY ix_oma_outreach_join_requests_vouching_admin_phone (vouching_admin_phone),
    CONSTRAINT fk_ojr_requester_user
        FOREIGN KEY (requester_user_id) REFERENCES oma_user_registration (id) ON DELETE SET NULL,
    CONSTRAINT fk_ojr_vouching_admin_user
        FOREIGN KEY (vouching_admin_user_id) REFERENCES oma_user_registration (id) ON DELETE SET NULL
) ENGINE=InnoDB;
