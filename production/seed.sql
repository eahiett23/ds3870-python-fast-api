-- Demo data, fresh development database only. Random passwords discarded.
-- Set new Argon2id hashes using a secure provisioning/reset process before login.
USE swollenhippo_industries;
SET time_zone = '+00:00';
START TRANSACTION;
INSERT INTO users (id,email,password_hash,role,first_name,last_name,company_name) VALUES
(1,'admin@swollenhippo.example','$argon2id$v=19$m=65536,t=3,p=4$Oy/UU8XDgAVX7Qw01ZjCzA$gmv19t1Lhc1tyxVXkftLNDpKE+jkzcya2oI+9RsbKUs','admin','Hippo','Admin','SwollenHippo Industries'),
(2,'customer@example.test','$argon2id$v=19$m=65536,t=3,p=4$qou/NFQzWI2WZ9KQ92aVXQ$sUTut2U5ba1Y7ralXXMwe07vvMaGuvEhMfnpznTXsPI','customer','Alex','Rivera','Prototype Labs');
SET @app_actor_id = 1;
INSERT INTO inquiries (id,customer_id,contact_name,contact_email,company_name,inquiry_type,description,target_budget,target_completion_at,status) VALUES
(1,2,'Alex Rivera','customer@example.test','Prototype Labs','3d_printing','Print a functional nylon enclosure.',1250.00,'2026-10-25 17:00:00','converted'),
(2,2,'Alex Rivera','customer@example.test','Prototype Labs','cnc','Machine two aluminum sensor brackets.',2100.00,'2026-10-01 17:00:00','converted');
INSERT INTO jobs (id,job_number,customer_id,inquiry_id,title,description,service_type,updated_by_admin_id,target_completion_at) VALUES
(1,'SH-2026-0001',2,1,'Nylon enclosure','SLS PA12 enclosure with press-fit inserts.','3d_printing',1,'2026-10-25 17:00:00'),
(2,'SH-2026-0002',2,2,'Sensor brackets','CNC 6061-T6 brackets; critical bore tolerance +/-0.02 mm.','cnc',1,'2026-10-01 17:00:00');
UPDATE jobs SET status='toolpathing_design',progress_percentage=20,version=version+1 WHERE id=1;
INSERT INTO job_milestones (job_id,admin_id,stage,progress_percentage,note) VALUES
(1,1,'toolpathing_design',20,'CAD reviewed; orientation and supports approved.');
UPDATE jobs SET status='in_production',progress_percentage=55,version=version+1 WHERE id=1;
UPDATE jobs SET status='in_production',progress_percentage=60,version=version+1 WHERE id=2;
UPDATE jobs SET status='ready_to_ship',progress_percentage=95,estimated_ship_at='2026-09-29 12:00:00',version=version+1 WHERE id=2;
UPDATE jobs SET status='shipped',progress_percentage=98,actual_ship_at='2026-09-29 14:30:00',carrier_name='UPS',tracking_number='DEMO-SH-0002',tracking_url='https://www.ups.com/track?tracknum=DEMO-SH-0002',version=version+1 WHERE id=2;
UPDATE jobs SET status='delivered',progress_percentage=100,version=version+1 WHERE id=2;
UPDATE jobs SET status='completed',actual_completion_at='2026-10-01 15:00:00',archived_at='2026-10-02 09:00:00',version=version+1 WHERE id=2;
INSERT INTO job_milestones (job_id,admin_id,stage,progress_percentage,note) VALUES
(2,1,'completed',100,'Dimensional inspection passed; delivery confirmed by customer.');
INSERT INTO job_attachments (job_id,uploaded_by_user_id,kind,original_filename,storage_reference,content_type,size_bytes) VALUES
(1,2,'cad','enclosure.step','jobs/SH-2026-0001/enclosure.step','application/octet-stream',184320),
(2,1,'qc_photo','bracket-qc.jpg','jobs/SH-2026-0002/bracket-qc.jpg','image/jpeg',98304);
COMMIT;
SET @app_actor_id = NULL;
