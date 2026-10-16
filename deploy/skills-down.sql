-- MANUAL ONLY, after exporting Skills and backing up the database.
-- Prefer rolling back application code and retaining this table.
-- No effect on prompts or authentication data.
DROP TABLE IF EXISTS skills;
