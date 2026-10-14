"""Build migration schema from the candidate ORM. No database connection or seed."""
from pathlib import Path
import hashlib
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable, CreateIndex
if __package__:
    from .models import Base, SERVICES
else:
    from models import Base, SERVICES

obj_root = Path(__file__).resolve().parent
configure_mappers()
obj_dialect = mysql.dialect()
str_sql = '''-- SwollenHippo MySQL migration schema, MySQL 8.0.16+ / 8.4 LTS.
-- Import into the verified empty swollenhippo_db with a privileged account.
-- Creates tables, indexes, two procedures and eight triggers; no seed/users/grants.
-- It does not migrate SQLite data or change application configuration.
-- Stop on any import error; DDL implicitly commits. No destructive rollback here.
CREATE DATABASE IF NOT EXISTS swollenhippo_db CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE swollenhippo_db;
SET NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci;
SET time_zone = '+00:00';

'''
for obj_table in Base.metadata.sorted_tables:
    str_sql += str(CreateTable(obj_table).compile(dialect=obj_dialect)) + ';\n'
    for obj_index in sorted(obj_table.indexes, key=lambda obj_item: obj_item.name):
        str_sql += str(CreateIndex(obj_index).compile(dialect=obj_dialect)) + ';\n'
str_sql += (obj_root / 'triggers.sql').read_text(encoding='utf-8')
assert len(Base.metadata.tables) == 6
assert str_sql.count('CREATE TRIGGER ') == 8
assert str_sql.count('CREATE PROCEDURE ') == 2
assert 'other' in SERVICES
assert Base.metadata.tables['jobs'].c.legacy_id.unique
for str_column in ('contact_name', 'contact_email', 'company_name'):
    assert str_column in Base.metadata.tables['jobs'].c
for str_table in ('jobs', 'inquiries'):
    for str_column in ('service_label', 'budget_text'):
        assert str_column in Base.metadata.tables[str_table].c
assert 'DROP ' not in str_sql and 'INSERT INTO users' not in str_sql
obj_output = obj_root / 'swollenhippo-mysql-schema.sql'
obj_output.write_text(str_sql, encoding='utf-8', newline='\n')
print('PASS: all mappings configured; six MySQL tables compiled, two procedures and eight triggers included, legacy ID uniqueness and contact snapshots checked; no seed or destructive statements.')
print('SHA256:', hashlib.sha256(obj_output.read_bytes()).hexdigest())
