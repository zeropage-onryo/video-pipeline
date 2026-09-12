"""Private creative projects with optimistic concurrency, backed by Postgres."""
import json
import uuid

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS creative_projects (
    id TEXT PRIMARY KEY,
    account_id BIGINT NOT NULL,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    payload TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS creative_projects_owner
ON creative_projects(account_id, user_id, updated_at DESC);
"""


def init(dsn=None):
    with db.connect(dsn) as conn:
        conn.execute(SCHEMA)
        db.own_table(conn, 'creative_projects')
        # Browser/API roles have no direct access; the server applies both owner predicates.
        conn.execute('ALTER TABLE creative_projects ENABLE ROW LEVEL SECURITY')


def list_projects(account_id, user_id, dsn=None):
    with db.connect(dsn) as conn:
        return [dict(row) for row in conn.execute(
            'SELECT id, title, revision, updated_at FROM creative_projects '
            'WHERE account_id=%s AND user_id=%s ORDER BY updated_at DESC LIMIT 100',
            (account_id, user_id)).fetchall()]


def get(project_id, account_id, user_id, dsn=None):
    with db.connect(dsn) as conn:
        row = conn.execute('SELECT * FROM creative_projects '
                           'WHERE id=%s AND account_id=%s AND user_id=%s',
                           (project_id, account_id, user_id)).fetchone()
        if not row:
            return None
        return {**dict(row), 'payload': json.loads(row['payload'])}


def save(project_id, account_id, user_id, title, payload, revision=0, dsn=None):
    """Return None on stale revision or invisible project, never overwrite it."""
    with db.connect(dsn) as conn:
        if project_id:
            row = conn.execute(
                'UPDATE creative_projects SET title=%s, payload=%s, revision=revision+1, updated_at=now() '
                'WHERE id=%s AND account_id=%s AND user_id=%s AND revision=%s RETURNING id, revision',
                (title, json.dumps(payload), project_id, account_id, user_id, revision)).fetchone()
        else:
            row = conn.execute(
                'INSERT INTO creative_projects(id, account_id, user_id, title, payload) '
                'VALUES (%s,%s,%s,%s,%s) RETURNING id, revision',
                (str(uuid.uuid4()), account_id, user_id, title, json.dumps(payload))).fetchone()
        return dict(row) if row else None
