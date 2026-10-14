-- Apply once to the already-installed original migration schema.
-- Keep the application on SQLite. This does not copy data or change services.
-- These nullable fields preserve exact submitted service labels and budget ranges.
-- Numeric target_budget remains available for an actual numeric budget.
-- ALTER TABLE implicitly commits; stop on error and inspect before retrying.
USE swollenhippo_db;
ALTER TABLE inquiries
  ADD COLUMN service_label VARCHAR(100) NULL,
  ADD COLUMN budget_text VARCHAR(80) NULL;
ALTER TABLE jobs
  ADD COLUMN service_label VARCHAR(100) NULL,
  ADD COLUMN budget_text VARCHAR(80) NULL;
