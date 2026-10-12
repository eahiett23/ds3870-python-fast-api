-- Only needed when DATABASE_MODE=production (MySQL).
-- In demo mode the app makes this table by itself.
-- Run it once in the production database:  mysql -u your_user -p your_database < auth_sessions.sql
-- If the FOREIGN KEY line gives an error, check that the users table has an email column
-- with the same type, or delete that line.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash VARCHAR(64) NOT NULL,
    user_email VARCHAR(254) NOT NULL,
    expires_at DATETIME NOT NULL,
    PRIMARY KEY (token_hash),
    INDEX ix_sessions_user_email (user_email),
    FOREIGN KEY (user_email) REFERENCES users (email) ON DELETE CASCADE
) ENGINE=InnoDB;
