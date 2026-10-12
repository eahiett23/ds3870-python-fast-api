"""Offline mapping/DDL/seed checks; does not require a running MySQL server."""
from pathlib import Path
import re
from argon2 import extract_parameters
from argon2.low_level import Type
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable, CreateIndex
from models import Base

obj_root = Path(__file__).resolve().parent
configure_mappers()
str_schema = (obj_root / 'schema.sql').read_text(encoding='utf-8')
assert set(Base.metadata.tables) == {'users', 'user_sessions', 'inquiries', 'jobs', 'job_milestones', 'job_attachments'}
for obj_table in Base.metadata.sorted_tables:
    assert str(CreateTable(obj_table).compile(dialect=mysql.dialect())) + ';' in str_schema, obj_table.name
    for obj_index in obj_table.indexes:
        assert str(CreateIndex(obj_index).compile(dialect=mysql.dialect())) + ';' in str_schema
    for obj_fk in obj_table.foreign_key_constraints:
        assert obj_fk.ondelete in {'CASCADE', 'RESTRICT', 'SET NULL'}
        assert obj_fk.onupdate == 'RESTRICT'
assert (obj_root / 'triggers.sql').read_text(encoding='utf-8') in str_schema
assert str_schema.count('CREATE TRIGGER ') == 8
assert 'progress_percentage BETWEEN 0 AND 100' in str_schema
assert 'ck_attachment_parent' in str_schema
str_seed = (obj_root / 'seed.sql').read_text(encoding='utf-8')
lst_hashes = re.findall(r"\$argon2id\$[^']+", str_seed)
assert len(lst_hashes) == 2
for str_hash in lst_hashes:
    obj_parameters = extract_parameters(str_hash)
    assert obj_parameters.type == Type.ID and obj_parameters.memory_cost >= 65536
print('PASS: six tables, relationships, MySQL DDL parity, FK policies, eight triggers, constraints and two Argon2id seed hashes.')
