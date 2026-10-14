
-- Trusted backend sets authenticated actor on the SAME connection/transaction.
-- This is an assertion boundary, not authentication of a SQL client.
DELIMITER $$
-- Exposes only schema readiness; callers need EXECUTE, not TRIGGER privileges.
CREATE PROCEDURE production_schema_ready()
SQL SECURITY DEFINER
BEGIN
  SELECT COUNT(*) AS installed_triggers FROM information_schema.TRIGGERS
  WHERE TRIGGER_SCHEMA = DATABASE() AND TRIGGER_NAME IN
    ('jobs_before_insert', 'jobs_before_update', 'jobs_before_delete',
     'milestones_before_insert', 'milestones_before_update', 'milestones_before_delete',
     'jobs_after_insert', 'jobs_after_update');
END$$
CREATE PROCEDURE assert_admin(IN actor BIGINT UNSIGNED)
SQL SECURITY DEFINER
BEGIN
  IF actor IS NULL OR NOT EXISTS (SELECT 1 FROM users WHERE id=actor AND role='admin' AND is_active=1) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Active administrator required';
  END IF;
END$$
CREATE TRIGGER jobs_before_insert BEFORE INSERT ON jobs FOR EACH ROW
BEGIN
  CALL assert_admin(@app_actor_id);
  IF NOT (NEW.updated_by_admin_id <=> @app_actor_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Job actor mismatch';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM users WHERE id=NEW.customer_id AND role='customer') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Job owner must be a customer';
  END IF;
END$$
CREATE TRIGGER jobs_before_update BEFORE UPDATE ON jobs FOR EACH ROW
BEGIN
  CALL assert_admin(@app_actor_id);
  IF NOT (NEW.updated_by_admin_id <=> @app_actor_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Job actor mismatch';
  END IF;
  IF NEW.id <> OLD.id OR NEW.customer_id <> OLD.customer_id OR NOT (NEW.inquiry_id <=> OLD.inquiry_id) OR NOT (NEW.legacy_id <=> OLD.legacy_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Job identity and ownership are immutable';
  END IF;
  IF NEW.version <> OLD.version + 1 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Job version must increment exactly once';
  END IF;
END$$
CREATE TRIGGER jobs_before_delete BEFORE DELETE ON jobs FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Archive jobs instead of deleting history';
END$$
CREATE TRIGGER milestones_before_insert BEFORE INSERT ON job_milestones FOR EACH ROW
BEGIN
  CALL assert_admin(@app_actor_id);
  IF NOT (NEW.admin_id <=> @app_actor_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Milestone actor mismatch';
  END IF;
END$$
CREATE TRIGGER milestones_before_update BEFORE UPDATE ON job_milestones FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Timeline is append-only';
END$$
CREATE TRIGGER milestones_before_delete BEFORE DELETE ON job_milestones FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Timeline is append-only';
END$$
CREATE TRIGGER jobs_after_insert AFTER INSERT ON jobs FOR EACH ROW
BEGIN
  INSERT INTO job_milestones (job_id,admin_id,stage,progress_percentage,note,event_type)
  VALUES (NEW.id,NEW.updated_by_admin_id,NEW.status,NEW.progress_percentage,
    IF(NEW.legacy_id IS NULL, 'Job created', CONCAT('Job imported from SQLite; legacy ID: ', NEW.legacy_id, '; Pending progress initialized to 0% during migration')), 'created');
END$$
CREATE TRIGGER jobs_after_update AFTER UPDATE ON jobs FOR EACH ROW
BEGIN
  INSERT INTO job_milestones (job_id,admin_id,stage,progress_percentage,note,event_type)
  VALUES (NEW.id,NEW.updated_by_admin_id,NEW.status,NEW.progress_percentage,
    CAST(JSON_OBJECT('version',NEW.version,'title',NEW.title,'description',NEW.description,
      'contact_name',NEW.contact_name,'contact_email',NEW.contact_email,'company_name',NEW.company_name,
      'service_type',NEW.service_type,'target_completion_at',NEW.target_completion_at,
      'actual_completion_at',NEW.actual_completion_at,'estimated_ship_at',NEW.estimated_ship_at,
      'actual_ship_at',NEW.actual_ship_at,'carrier_name',NEW.carrier_name,
      'tracking_number',NEW.tracking_number,'tracking_url',NEW.tracking_url,
      'archived_at',NEW.archived_at) AS CHAR), 'updated');
END$$
DELIMITER ;
