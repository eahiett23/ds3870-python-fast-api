-- MySQL 8.0.16+ (enforced CHECK constraints). Fresh database only.
CREATE DATABASE swollenhippo_industries CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE swollenhippo_industries;
SET time_zone = "+00:00";

CREATE TABLE users (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	email VARCHAR(254) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	`role` ENUM('customer','admin') NOT NULL DEFAULT 'customer', 
	first_name VARCHAR(120) NOT NULL, 
	last_name VARCHAR(120) NOT NULL, 
	phone VARCHAR(32), 
	company_name VARCHAR(200), 
	company_address TEXT, 
	is_active TINYINT UNSIGNED NOT NULL DEFAULT 1, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_users PRIMARY KEY (id), 
	CONSTRAINT ck_user_active CHECK (is_active IN (0, 1)), 
	CONSTRAINT uq_users_email UNIQUE (email)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci

;

CREATE TABLE inquiries (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	customer_id BIGINT UNSIGNED, 
	contact_name VARCHAR(240) NOT NULL, 
	contact_email VARCHAR(254) NOT NULL, 
	contact_phone VARCHAR(32), 
	company_name VARCHAR(200), 
	inquiry_type ENUM('3d_printing','cnc','electronics','software','design') NOT NULL, 
	description TEXT NOT NULL, 
	target_budget NUMERIC(12, 2), 
	currency VARCHAR(3) NOT NULL DEFAULT 'USD', 
	target_completion_at DATETIME(6), 
	status ENUM('pending','reviewed','quoted','converted','rejected') NOT NULL DEFAULT 'pending', 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_inquiries PRIMARY KEY (id), 
	CONSTRAINT ck_inquiry_budget CHECK (target_budget IS NULL OR target_budget >= 0), 
	CONSTRAINT fk_inquiries_customer_id FOREIGN KEY(customer_id) REFERENCES users (id) ON DELETE SET NULL ON UPDATE RESTRICT
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci

;
CREATE INDEX ix_inquiries_customer_created ON inquiries (customer_id, created_at);
CREATE INDEX ix_inquiries_email ON inquiries (contact_email);
CREATE INDEX ix_inquiries_status_created ON inquiries (status, created_at);

CREATE TABLE user_sessions (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	user_id BIGINT UNSIGNED NOT NULL, 
	token_digest BINARY(32) NOT NULL, 
	expires_at DATETIME(6) NOT NULL, 
	revoked_at DATETIME(6), 
	last_used_at DATETIME(6), 
	ip_address VARCHAR(45), 
	user_agent VARCHAR(512), 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_user_sessions PRIMARY KEY (id), 
	CONSTRAINT ck_session_expiry CHECK (expires_at > created_at), 
	CONSTRAINT fk_user_sessions_user_id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE RESTRICT, 
	CONSTRAINT uq_user_sessions_token_digest UNIQUE (token_digest)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci

;
CREATE INDEX ix_sessions_user_expiry ON user_sessions (user_id, expires_at);

CREATE TABLE jobs (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	job_number VARCHAR(32) NOT NULL, 
	customer_id BIGINT UNSIGNED NOT NULL, 
	inquiry_id BIGINT UNSIGNED, 
	title VARCHAR(240) NOT NULL, 
	description TEXT NOT NULL, 
	service_type ENUM('3d_printing','cnc','electronics','software','design') NOT NULL, 
	status ENUM('intake','toolpathing_design','in_production','post_processing_qa','ready_to_ship','shipped','delivered','completed','cancelled') NOT NULL DEFAULT 'intake', 
	progress_percentage TINYINT UNSIGNED NOT NULL DEFAULT 0, 
	target_completion_at DATETIME(6), 
	actual_completion_at DATETIME(6), 
	estimated_ship_at DATETIME(6), 
	actual_ship_at DATETIME(6), 
	carrier_name VARCHAR(100), 
	tracking_number VARCHAR(128), 
	tracking_url VARCHAR(2048), 
	archived_at DATETIME(6), 
	version BIGINT UNSIGNED NOT NULL DEFAULT 1, 
	updated_by_admin_id BIGINT UNSIGNED NOT NULL, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_jobs PRIMARY KEY (id), 
	CONSTRAINT ck_job_progress CHECK (progress_percentage BETWEEN 0 AND 100), 
	CONSTRAINT ck_job_completed CHECK (status <> 'completed' OR (progress_percentage = 100 AND actual_completion_at IS NOT NULL)), 
	CONSTRAINT ck_job_shipping CHECK (status NOT IN ('shipped', 'delivered') OR actual_ship_at IS NOT NULL), 
	CONSTRAINT uq_jobs_job_number UNIQUE (job_number), 
	CONSTRAINT fk_jobs_customer_id FOREIGN KEY(customer_id) REFERENCES users (id) ON DELETE RESTRICT ON UPDATE RESTRICT, 
	CONSTRAINT uq_jobs_inquiry_id UNIQUE (inquiry_id), 
	CONSTRAINT fk_jobs_inquiry_id FOREIGN KEY(inquiry_id) REFERENCES inquiries (id) ON DELETE RESTRICT ON UPDATE RESTRICT, 
	CONSTRAINT fk_jobs_updated_by_admin_id FOREIGN KEY(updated_by_admin_id) REFERENCES users (id) ON DELETE RESTRICT ON UPDATE RESTRICT
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci

;
CREATE INDEX ix_jobs_customer_created ON jobs (customer_id, created_at);
CREATE INDEX ix_jobs_status_created ON jobs (status, created_at);

CREATE TABLE job_attachments (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	job_id BIGINT UNSIGNED, 
	inquiry_id BIGINT UNSIGNED, 
	uploaded_by_user_id BIGINT UNSIGNED, 
	kind ENUM('cad','schematic','drawing','qc_photo','other') NOT NULL, 
	original_filename VARCHAR(255) NOT NULL, 
	storage_reference VARCHAR(2048) NOT NULL, 
	content_type VARCHAR(127) NOT NULL, 
	size_bytes BIGINT UNSIGNED NOT NULL, 
	sha256_digest BINARY(32), 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_job_attachments PRIMARY KEY (id), 
	CONSTRAINT ck_attachment_parent CHECK ((job_id IS NOT NULL) + (inquiry_id IS NOT NULL) = 1), 
	CONSTRAINT ck_attachment_size CHECK (size_bytes >= 0), 
	CONSTRAINT fk_job_attachments_job_id FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE RESTRICT ON UPDATE RESTRICT, 
	CONSTRAINT fk_job_attachments_inquiry_id FOREIGN KEY(inquiry_id) REFERENCES inquiries (id) ON DELETE RESTRICT ON UPDATE RESTRICT, 
	CONSTRAINT fk_job_attachments_uploaded_by_user_id FOREIGN KEY(uploaded_by_user_id) REFERENCES users (id) ON DELETE SET NULL ON UPDATE RESTRICT
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci

;
CREATE INDEX ix_attachments_inquiry_created ON job_attachments (inquiry_id, created_at);
CREATE INDEX ix_attachments_job_created ON job_attachments (job_id, created_at);

CREATE TABLE job_milestones (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	job_id BIGINT UNSIGNED NOT NULL, 
	admin_id BIGINT UNSIGNED NOT NULL, 
	stage ENUM('intake','toolpathing_design','in_production','post_processing_qa','ready_to_ship','shipped','delivered','completed','cancelled') NOT NULL, 
	progress_percentage TINYINT UNSIGNED NOT NULL, 
	note TEXT NOT NULL, 
	event_type ENUM('created','updated','note') NOT NULL DEFAULT 'note', 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_job_milestones PRIMARY KEY (id), 
	CONSTRAINT ck_milestone_progress CHECK (progress_percentage BETWEEN 0 AND 100), 
	CONSTRAINT fk_job_milestones_job_id FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE RESTRICT ON UPDATE RESTRICT, 
	CONSTRAINT fk_job_milestones_admin_id FOREIGN KEY(admin_id) REFERENCES users (id) ON DELETE RESTRICT ON UPDATE RESTRICT
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci

;
CREATE INDEX ix_milestones_job_created ON job_milestones (job_id, created_at, id);

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
  IF NEW.id <> OLD.id OR NEW.customer_id <> OLD.customer_id OR NOT (NEW.inquiry_id <=> OLD.inquiry_id) THEN
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
  VALUES (NEW.id,NEW.updated_by_admin_id,NEW.status,NEW.progress_percentage,'Job created','created');
END$$
CREATE TRIGGER jobs_after_update AFTER UPDATE ON jobs FOR EACH ROW
BEGIN
  INSERT INTO job_milestones (job_id,admin_id,stage,progress_percentage,note,event_type)
  VALUES (NEW.id,NEW.updated_by_admin_id,NEW.status,NEW.progress_percentage,
    CAST(JSON_OBJECT('version',NEW.version,'title',NEW.title,'description',NEW.description,
      'service_type',NEW.service_type,'target_completion_at',NEW.target_completion_at,
      'actual_completion_at',NEW.actual_completion_at,'estimated_ship_at',NEW.estimated_ship_at,
      'actual_ship_at',NEW.actual_ship_at,'carrier_name',NEW.carrier_name,
      'tracking_number',NEW.tracking_number,'tracking_url',NEW.tracking_url,
      'archived_at',NEW.archived_at) AS CHAR), 'updated');
END$$
DELIMITER ;
