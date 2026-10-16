-- Idempotent additive migration, also executed by app.skills.install_skills.
-- Back up SQLite first. No change to the prompts table.
CREATE TABLE IF NOT EXISTS skills (
    owner_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (owner_id, skill_id)
);
