-- brandcal schema (SPEC 5.3). Applied by db.init_db; safe to run repeatedly.
-- Connection pragmas (foreign_keys, WAL, busy_timeout) are set by db.open_db.
-- Trigger errors are RAISE(ABORT, 'CODE: message') with CODE an errors.ErrorCode name.

CREATE TABLE IF NOT EXISTS agents (
  id   TEXT PRIMARY KEY,
  role TEXT NOT NULL CHECK (role IN ('manager','writer','approver','contributor','admin','system'))
);

CREATE TABLE IF NOT EXISTS platforms (
  id TEXT PRIMARY KEY, limits TEXT NOT NULL CHECK (json_valid(limits))
);

CREATE TABLE IF NOT EXISTS posts (
  id            TEXT PRIMARY KEY,
  slug          TEXT NOT NULL,
  title         TEXT NOT NULL,
  platform      TEXT NOT NULL REFERENCES platforms(id),
  post_type     TEXT NOT NULL CHECK (post_type IN
                ('text','image','carousel','thread','article','reshare','video','comment')),
  status        TEXT NOT NULL DEFAULT 'pending_approval' CHECK (status IN
                ('pending_approval','changes_requested','approved','missed','published','cancelled')),
  owner         TEXT NOT NULL REFERENCES agents(id),
  window        TEXT,
  window_start_utc TEXT GENERATED ALWAYS AS (datetime(substr(window, 1, instr(window,'/') - 1))) STORED,
  window_end_utc   TEXT GENERATED ALWAYS AS (datetime(substr(window, instr(window,'/') + 1))) STORED,
  series_id     TEXT, series_pos INTEGER,
  campaign      TEXT, pillar TEXT,
  keywords      TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(keywords)),
  first_comment TEXT,
  target_url    TEXT,
  delegation_msg_id TEXT, delegation_words TEXT,
  hold_until    TEXT, hold_reason TEXT,
  source_doc    TEXT,
  content_version INTEGER NOT NULL DEFAULT 1,
  content_hash  TEXT NOT NULL,
  native_scheduled_at TEXT,
  claimed_by    TEXT REFERENCES agents(id), claim_expires TEXT,
  platform_post_id TEXT, platform_url TEXT, published_at TEXT,
  cancel_kind   TEXT CHECK (cancel_kind IN ('idea','version','plan')),
  notes         TEXT,
  legacy_id     TEXT UNIQUE,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, closed_at TEXT,
  CHECK (window GLOB '????-??-??T??:??:??[+-]??:??/????-??-??T??:??:??[+-]??:??'),
  CHECK (window_end_utc > window_start_utc),
  CHECK (window IS NOT NULL OR (legacy_id IS NOT NULL AND status = 'published')),
  CHECK (post_type <> 'comment' OR (delegation_msg_id IS NOT NULL AND delegation_words IS NOT NULL)),
  CHECK (post_type NOT IN ('comment','reshare') OR target_url IS NOT NULL),
  CHECK ((status = 'cancelled') = (cancel_kind IS NOT NULL)),
  CHECK ((status IN ('published','cancelled')) = (closed_at IS NOT NULL)),
  CHECK (status <> 'published' OR platform_url IS NOT NULL OR legacy_id IS NOT NULL),
  CHECK (status = 'approved' OR (native_scheduled_at IS NULL AND claimed_by IS NULL AND claim_expires IS NULL)),
  CHECK ((claimed_by IS NULL) = (claim_expires IS NULL)),
  CHECK (native_scheduled_at IS NULL OR claimed_by IS NULL)
);

CREATE TABLE IF NOT EXISTS parts (
  id      INTEGER PRIMARY KEY,
  post_id TEXT NOT NULL REFERENCES posts(id),
  pos     INTEGER NOT NULL CHECK (pos >= 1),
  text    TEXT NOT NULL,
  platform_post_id TEXT, platform_url TEXT,
  UNIQUE (post_id, pos)
);

CREATE TABLE IF NOT EXISTS media (
  id TEXT PRIMARY KEY,
  part_id INTEGER NOT NULL REFERENCES parts(id), pos INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('image','video','pdf','gif')),
  path TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
  alt_text TEXT NOT NULL CHECK (length(alt_text) > 0),
  bytes INTEGER NOT NULL, width INTEGER, height INTEGER, duration_s REAL,
  source_url TEXT, credit TEXT, licence TEXT,
  UNIQUE (part_id, pos)
);

CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY,
  post_id TEXT NOT NULL REFERENCES posts(id),
  decision TEXT NOT NULL CHECK (decision IN ('approve','request_changes','cancel','reschedule')),
  content_version INTEGER NOT NULL, content_hash TEXT NOT NULL,
  window TEXT NOT NULL,
  decided_by  TEXT NOT NULL REFERENCES agents(id),
  channel     TEXT NOT NULL CHECK (channel IN ('card','writer-session','legacy')),
  relayed_by  TEXT NOT NULL REFERENCES agents(id),
  recorded_by TEXT NOT NULL REFERENCES agents(id),
  source_message_id TEXT NOT NULL,
  approver_words TEXT NOT NULL,
  changes_requested TEXT,
  decided_at TEXT NOT NULL,
  signature TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL,
  actor TEXT NOT NULL REFERENCES agents(id),
  post_id TEXT,
  action TEXT NOT NULL,
  from_status TEXT, to_status TEXT,
  detail TEXT CHECK (detail IS NULL OR json_valid(detail)),
  reason TEXT,
  chain TEXT NOT NULL,
  prev_hash TEXT, row_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS archive_lock (
  id INTEGER PRIMARY KEY CHECK (id = 1), active INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO archive_lock VALUES (1, 0);

CREATE TABLE IF NOT EXISTS transitions (
  from_status TEXT NOT NULL, to_status TEXT NOT NULL, roles TEXT NOT NULL,
  PRIMARY KEY (from_status, to_status)
);

-- T-a: new posts start at pending_approval (legacy rows come from migration only).
CREATE TRIGGER IF NOT EXISTS posts_insert_status
BEFORE INSERT ON posts
WHEN NEW.status <> 'pending_approval' AND NEW.legacy_id IS NULL
BEGIN
  SELECT RAISE(ABORT, 'BAD_TRANSITION: a new post must start at pending_approval');
END;

-- T-b: a status change must be a row in transitions.
CREATE TRIGGER IF NOT EXISTS posts_status_transition
BEFORE UPDATE OF status ON posts
WHEN NEW.status <> OLD.status AND NOT EXISTS
  (SELECT 1 FROM transitions WHERE from_status = OLD.status AND to_status = NEW.status)
BEGIN
  SELECT RAISE(ABORT, 'BAD_TRANSITION: this status change is not in the state machine');
END;

-- T-c: approved needs an approval for the current version and hash: 'approve' from
-- pending_approval, a time-only 'reschedule' from missed. Only checked for listed
-- transitions, so an unlisted change reports BAD_TRANSITION (from T-b) first.
CREATE TRIGGER IF NOT EXISTS posts_approved_needs_approval
BEFORE UPDATE OF status ON posts
WHEN NEW.status = 'approved' AND OLD.status <> 'approved'
  AND EXISTS (SELECT 1 FROM transitions WHERE from_status = OLD.status AND to_status = 'approved')
  AND NOT EXISTS
  (SELECT 1 FROM approvals
   WHERE post_id = NEW.id AND content_version = NEW.content_version
     AND content_hash = NEW.content_hash
     AND ((OLD.status <> 'missed' AND decision = 'approve')
          OR (OLD.status = 'missed' AND decision = 'reschedule')))
BEGIN
  SELECT RAISE(ABORT, 'STALE_APPROVAL: no approval for the current version and hash');
END;

-- T-d: published needs an approval for the current version (legacy rows excepted).
CREATE TRIGGER IF NOT EXISTS posts_published_needs_approval
BEFORE UPDATE OF status ON posts
WHEN NEW.status = 'published' AND OLD.status <> 'published' AND NEW.legacy_id IS NULL
  AND EXISTS (SELECT 1 FROM transitions WHERE from_status = OLD.status AND to_status = 'published')
  AND NOT EXISTS
  (SELECT 1 FROM approvals
   WHERE post_id = NEW.id AND content_version = NEW.content_version
     AND content_hash = NEW.content_hash AND decision IN ('approve','reschedule'))
BEGIN
  SELECT RAISE(ABORT, 'STALE_APPROVAL: no approval for the current version and hash');
END;

-- T-e: refuse content and window edits while the post is queued or claimed.
-- Part updates are limited to text, pos and post_id so that recording platform_url
-- after publishing is not an edit.
CREATE TRIGGER IF NOT EXISTS parts_ins_edit_while_queued
BEFORE INSERT ON parts
BEGIN
  SELECT RAISE(ABORT, 'EDIT_WHILE_SCHEDULED: post is natively scheduled; unschedule it first')
    FROM posts WHERE id = NEW.post_id AND native_scheduled_at IS NOT NULL;
  SELECT RAISE(ABORT, 'EDIT_WHILE_CLAIMED: post is claimed for publishing')
    FROM posts WHERE id = NEW.post_id AND claimed_by IS NOT NULL;
END;

CREATE TRIGGER IF NOT EXISTS parts_upd_edit_while_queued
BEFORE UPDATE ON parts
WHEN NEW.text IS NOT OLD.text OR NEW.pos IS NOT OLD.pos OR NEW.post_id IS NOT OLD.post_id
BEGIN
  SELECT RAISE(ABORT, 'EDIT_WHILE_SCHEDULED: post is natively scheduled; unschedule it first')
    FROM posts WHERE id IN (OLD.post_id, NEW.post_id) AND native_scheduled_at IS NOT NULL;
  SELECT RAISE(ABORT, 'EDIT_WHILE_CLAIMED: post is claimed for publishing')
    FROM posts WHERE id IN (OLD.post_id, NEW.post_id) AND claimed_by IS NOT NULL;
END;

CREATE TRIGGER IF NOT EXISTS parts_del_edit_while_queued
BEFORE DELETE ON parts
BEGIN
  SELECT RAISE(ABORT, 'EDIT_WHILE_SCHEDULED: post is natively scheduled; unschedule it first')
    FROM posts WHERE id = OLD.post_id AND native_scheduled_at IS NOT NULL;
  SELECT RAISE(ABORT, 'EDIT_WHILE_CLAIMED: post is claimed for publishing')
    FROM posts WHERE id = OLD.post_id AND claimed_by IS NOT NULL;
END;

CREATE TRIGGER IF NOT EXISTS media_ins_edit_while_queued
BEFORE INSERT ON media
BEGIN
  SELECT RAISE(ABORT, 'EDIT_WHILE_SCHEDULED: post is natively scheduled; unschedule it first')
    FROM posts WHERE native_scheduled_at IS NOT NULL
      AND id = (SELECT post_id FROM parts WHERE id = NEW.part_id);
  SELECT RAISE(ABORT, 'EDIT_WHILE_CLAIMED: post is claimed for publishing')
    FROM posts WHERE claimed_by IS NOT NULL
      AND id = (SELECT post_id FROM parts WHERE id = NEW.part_id);
END;

CREATE TRIGGER IF NOT EXISTS media_upd_edit_while_queued
BEFORE UPDATE ON media
BEGIN
  SELECT RAISE(ABORT, 'EDIT_WHILE_SCHEDULED: post is natively scheduled; unschedule it first')
    FROM posts WHERE native_scheduled_at IS NOT NULL
      AND id IN (SELECT post_id FROM parts WHERE id IN (OLD.part_id, NEW.part_id));
  SELECT RAISE(ABORT, 'EDIT_WHILE_CLAIMED: post is claimed for publishing')
    FROM posts WHERE claimed_by IS NOT NULL
      AND id IN (SELECT post_id FROM parts WHERE id IN (OLD.part_id, NEW.part_id));
END;

CREATE TRIGGER IF NOT EXISTS media_del_edit_while_queued
BEFORE DELETE ON media
BEGIN
  SELECT RAISE(ABORT, 'EDIT_WHILE_SCHEDULED: post is natively scheduled; unschedule it first')
    FROM posts WHERE native_scheduled_at IS NOT NULL
      AND id = (SELECT post_id FROM parts WHERE id = OLD.part_id);
  SELECT RAISE(ABORT, 'EDIT_WHILE_CLAIMED: post is claimed for publishing')
    FROM posts WHERE claimed_by IS NOT NULL
      AND id = (SELECT post_id FROM parts WHERE id = OLD.part_id);
END;

CREATE TRIGGER IF NOT EXISTS posts_edit_while_queued
BEFORE UPDATE OF first_comment, target_url, post_type, window ON posts
WHEN NEW.first_comment IS NOT OLD.first_comment OR NEW.target_url IS NOT OLD.target_url
  OR NEW.post_type IS NOT OLD.post_type OR NEW.window IS NOT OLD.window
BEGIN
  SELECT RAISE(ABORT, 'EDIT_WHILE_SCHEDULED: post is natively scheduled; unschedule it first')
    WHERE OLD.native_scheduled_at IS NOT NULL;
  SELECT RAISE(ABORT, 'EDIT_WHILE_CLAIMED: post is claimed for publishing')
    WHERE OLD.claimed_by IS NOT NULL;
END;

-- T-f: a content change bumps content_version; an approved or missed post goes back to
-- pending_approval and the change is logged on the post's hash chain. The subquery with
-- LIMIT keeps bc_now() evaluated once, so the stored time is the hashed time.
CREATE TRIGGER IF NOT EXISTS parts_ins_content_bump
AFTER INSERT ON parts
BEGIN
  INSERT INTO events (at, actor, post_id, action, from_status, to_status, reason, chain,
                      prev_hash, row_hash)
  SELECT n.at, 'system', p.id, 'edit', p.status, 'pending_approval', 'content edited',
         'post:' || p.id, n.prev,
         bc_row_hash(n.prev, n.at, 'system', p.id, 'edit', p.status, 'pending_approval',
                     NULL, 'content edited', 'post:' || p.id)
  FROM posts p,
       (SELECT bc_now() AS at,
               (SELECT row_hash FROM events WHERE chain = 'post:' || NEW.post_id
                ORDER BY id DESC LIMIT 1) AS prev LIMIT 1) n
  WHERE p.id = NEW.post_id AND p.status IN ('approved','missed');
  UPDATE posts SET content_version = content_version + 1, updated_at = bc_now(),
    status = CASE WHEN status IN ('approved','missed') THEN 'pending_approval' ELSE status END
  WHERE id = NEW.post_id;
END;

CREATE TRIGGER IF NOT EXISTS parts_upd_content_bump
AFTER UPDATE ON parts
WHEN NEW.text IS NOT OLD.text OR NEW.pos IS NOT OLD.pos OR NEW.post_id IS NOT OLD.post_id
BEGIN
  INSERT INTO events (at, actor, post_id, action, from_status, to_status, reason, chain,
                      prev_hash, row_hash)
  SELECT n.at, 'system', p.id, 'edit', p.status, 'pending_approval', 'content edited',
         'post:' || p.id, n.prev,
         bc_row_hash(n.prev, n.at, 'system', p.id, 'edit', p.status, 'pending_approval',
                     NULL, 'content edited', 'post:' || p.id)
  FROM posts p,
       (SELECT bc_now() AS at,
               (SELECT row_hash FROM events WHERE chain = 'post:' || NEW.post_id
                ORDER BY id DESC LIMIT 1) AS prev LIMIT 1) n
  WHERE p.id = NEW.post_id AND p.status IN ('approved','missed');
  UPDATE posts SET content_version = content_version + 1, updated_at = bc_now(),
    status = CASE WHEN status IN ('approved','missed') THEN 'pending_approval' ELSE status END
  WHERE id = NEW.post_id;
END;

CREATE TRIGGER IF NOT EXISTS parts_del_content_bump
AFTER DELETE ON parts
BEGIN
  INSERT INTO events (at, actor, post_id, action, from_status, to_status, reason, chain,
                      prev_hash, row_hash)
  SELECT n.at, 'system', p.id, 'edit', p.status, 'pending_approval', 'content edited',
         'post:' || p.id, n.prev,
         bc_row_hash(n.prev, n.at, 'system', p.id, 'edit', p.status, 'pending_approval',
                     NULL, 'content edited', 'post:' || p.id)
  FROM posts p,
       (SELECT bc_now() AS at,
               (SELECT row_hash FROM events WHERE chain = 'post:' || OLD.post_id
                ORDER BY id DESC LIMIT 1) AS prev LIMIT 1) n
  WHERE p.id = OLD.post_id AND p.status IN ('approved','missed');
  UPDATE posts SET content_version = content_version + 1, updated_at = bc_now(),
    status = CASE WHEN status IN ('approved','missed') THEN 'pending_approval' ELSE status END
  WHERE id = OLD.post_id;
END;

CREATE TRIGGER IF NOT EXISTS media_ins_content_bump
AFTER INSERT ON media
BEGIN
  INSERT INTO events (at, actor, post_id, action, from_status, to_status, reason, chain,
                      prev_hash, row_hash)
  SELECT n.at, 'system', p.id, 'edit', p.status, 'pending_approval', 'content edited',
         'post:' || p.id, n.prev,
         bc_row_hash(n.prev, n.at, 'system', p.id, 'edit', p.status, 'pending_approval',
                     NULL, 'content edited', 'post:' || p.id)
  FROM posts p,
       (SELECT bc_now() AS at,
               (SELECT row_hash FROM events
                WHERE chain = 'post:' || (SELECT post_id FROM parts WHERE id = NEW.part_id)
                ORDER BY id DESC LIMIT 1) AS prev LIMIT 1) n
  WHERE p.id = (SELECT post_id FROM parts WHERE id = NEW.part_id)
    AND p.status IN ('approved','missed');
  UPDATE posts SET content_version = content_version + 1, updated_at = bc_now(),
    status = CASE WHEN status IN ('approved','missed') THEN 'pending_approval' ELSE status END
  WHERE id = (SELECT post_id FROM parts WHERE id = NEW.part_id);
END;

CREATE TRIGGER IF NOT EXISTS media_upd_content_bump
AFTER UPDATE ON media
BEGIN
  INSERT INTO events (at, actor, post_id, action, from_status, to_status, reason, chain,
                      prev_hash, row_hash)
  SELECT n.at, 'system', p.id, 'edit', p.status, 'pending_approval', 'content edited',
         'post:' || p.id, n.prev,
         bc_row_hash(n.prev, n.at, 'system', p.id, 'edit', p.status, 'pending_approval',
                     NULL, 'content edited', 'post:' || p.id)
  FROM posts p,
       (SELECT bc_now() AS at,
               (SELECT row_hash FROM events
                WHERE chain = 'post:' || (SELECT post_id FROM parts WHERE id = NEW.part_id)
                ORDER BY id DESC LIMIT 1) AS prev LIMIT 1) n
  WHERE p.id = (SELECT post_id FROM parts WHERE id = NEW.part_id)
    AND p.status IN ('approved','missed');
  UPDATE posts SET content_version = content_version + 1, updated_at = bc_now(),
    status = CASE WHEN status IN ('approved','missed') THEN 'pending_approval' ELSE status END
  WHERE id = (SELECT post_id FROM parts WHERE id = NEW.part_id);
END;

CREATE TRIGGER IF NOT EXISTS media_del_content_bump
AFTER DELETE ON media
BEGIN
  INSERT INTO events (at, actor, post_id, action, from_status, to_status, reason, chain,
                      prev_hash, row_hash)
  SELECT n.at, 'system', p.id, 'edit', p.status, 'pending_approval', 'content edited',
         'post:' || p.id, n.prev,
         bc_row_hash(n.prev, n.at, 'system', p.id, 'edit', p.status, 'pending_approval',
                     NULL, 'content edited', 'post:' || p.id)
  FROM posts p,
       (SELECT bc_now() AS at,
               (SELECT row_hash FROM events
                WHERE chain = 'post:' || (SELECT post_id FROM parts WHERE id = OLD.part_id)
                ORDER BY id DESC LIMIT 1) AS prev LIMIT 1) n
  WHERE p.id = (SELECT post_id FROM parts WHERE id = OLD.part_id)
    AND p.status IN ('approved','missed');
  UPDATE posts SET content_version = content_version + 1, updated_at = bc_now(),
    status = CASE WHEN status IN ('approved','missed') THEN 'pending_approval' ELSE status END
  WHERE id = (SELECT post_id FROM parts WHERE id = OLD.part_id);
END;

CREATE TRIGGER IF NOT EXISTS posts_content_bump
AFTER UPDATE OF first_comment, target_url, post_type ON posts
WHEN NEW.first_comment IS NOT OLD.first_comment OR NEW.target_url IS NOT OLD.target_url
  OR NEW.post_type IS NOT OLD.post_type
BEGIN
  INSERT INTO events (at, actor, post_id, action, from_status, to_status, reason, chain,
                      prev_hash, row_hash)
  SELECT n.at, 'system', p.id, 'edit', p.status, 'pending_approval', 'content edited',
         'post:' || p.id, n.prev,
         bc_row_hash(n.prev, n.at, 'system', p.id, 'edit', p.status, 'pending_approval',
                     NULL, 'content edited', 'post:' || p.id)
  FROM posts p,
       (SELECT bc_now() AS at,
               (SELECT row_hash FROM events WHERE chain = 'post:' || NEW.id
                ORDER BY id DESC LIMIT 1) AS prev LIMIT 1) n
  WHERE p.id = NEW.id AND p.status IN ('approved','missed');
  UPDATE posts SET content_version = content_version + 1, updated_at = bc_now(),
    status = CASE WHEN status IN ('approved','missed') THEN 'pending_approval' ELSE status END
  WHERE id = NEW.id;
END;

-- T-g: events and approvals are append-only.
CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
  SELECT RAISE(ABORT, 'APPEND_ONLY: events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS approvals_no_update
BEFORE UPDATE ON approvals
BEGIN
  SELECT RAISE(ABORT, 'APPEND_ONLY: approvals are append-only');
END;

-- T-h: deletes happen only inside an archive run.
CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
WHEN (SELECT active FROM archive_lock WHERE id = 1) IS NOT 1
BEGIN
  SELECT RAISE(ABORT, 'APPEND_ONLY: events can only be deleted by an archive run');
END;

CREATE TRIGGER IF NOT EXISTS approvals_no_delete
BEFORE DELETE ON approvals
WHEN (SELECT active FROM archive_lock WHERE id = 1) IS NOT 1
BEGIN
  SELECT RAISE(ABORT, 'APPEND_ONLY: approvals can only be deleted by an archive run');
END;

-- T-i: roles on an approval.
CREATE TRIGGER IF NOT EXISTS approvals_roles
BEFORE INSERT ON approvals
BEGIN
  SELECT RAISE(ABORT, 'ROLE_NOT_ALLOWED: decided_by must be an approver')
    WHERE NOT EXISTS (SELECT 1 FROM agents WHERE id = NEW.decided_by AND role = 'approver');
  SELECT RAISE(ABORT, 'ROLE_NOT_ALLOWED: relayed_by must be a manager or writer')
    WHERE NOT EXISTS (SELECT 1 FROM agents
                      WHERE id = NEW.relayed_by AND role IN ('manager','writer'));
  SELECT RAISE(ABORT, 'ROLE_NOT_ALLOWED: recorded_by must be a manager')
    WHERE NOT EXISTS (SELECT 1 FROM agents WHERE id = NEW.recorded_by AND role = 'manager');
END;
