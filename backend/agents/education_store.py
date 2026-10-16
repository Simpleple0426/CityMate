"""Local demonstration business data. Never connect this unauthenticated demo to real records."""
import os
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from core.policy_evidence import PolicyEvidence
from core.transfer_requirements import extract_updates, apply_updates, violations


class EducationStore:
    def __init__(self, path=None, policy_path=None):
        self.policy_evidence = PolicyEvidence(policy_path)
        self.path = str(path or os.getenv("COURSEPILOT_EDUCATION_DB", "data/education.sqlite3"))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS classes (
                    id TEXT PRIMARY KEY, course TEXT, title TEXT, day TEXT,
                    period TEXT, level INTEGER, progress INTEGER, seats INTEGER,
                    price_cents INTEGER);
                CREATE TABLE IF NOT EXISTS enrollments (
                    user_id TEXT PRIMARY KEY, class_id TEXT, remaining INTEGER,
                    paid_cents INTEGER);
                CREATE TABLE IF NOT EXISTS drafts (
                    id TEXT PRIMARY KEY, user_id TEXT, conv_id TEXT, target_id TEXT,
                    reason TEXT, status TEXT, source_id TEXT, fee_cents INTEGER);
                CREATE TABLE IF NOT EXISTS applications (
                    id TEXT PRIMARY KEY, draft_id TEXT UNIQUE, user_id TEXT,
                    source_id TEXT, target_id TEXT, reason TEXT, status TEXT,
                    fee_cents INTEGER);
                CREATE TABLE IF NOT EXISTS active_tasks (
                    user_id TEXT, conv_id TEXT, PRIMARY KEY(user_id, conv_id));
                CREATE TABLE IF NOT EXISTS transfer_requirements (
                    user_id TEXT, conv_id TEXT, revision INTEGER, slots TEXT,
                    events TEXT, ambiguities TEXT, PRIMARY KEY(user_id, conv_id));
                CREATE TABLE IF NOT EXISTS class_metadata (class_id TEXT PRIMARY KEY, teacher TEXT);
                CREATE TABLE IF NOT EXISTS draft_evidence (draft_id TEXT PRIMARY KEY, revision INTEGER, policy_fingerprint TEXT);
                CREATE TABLE IF NOT EXISTS transfer_focus (user_id TEXT, conv_id TEXT, purpose TEXT, PRIMARY KEY(user_id, conv_id));
            """)
            db.executemany("INSERT OR IGNORE INTO classes VALUES (?,?,?,?,?,?,?,?,?)", [
                ("PY-SAT-AM", "python", "Python 基础班", "周六", "上午", 0, 4, 5, 200000),
                ("PY-SUN-AM", "python", "Python 基础班", "周日", "上午", 0, 4, 0, 200000),
                ("PY-SUN-PM", "python", "Python 基础班", "周日", "下午", 0, 4, 3, 200000),
                ("PY-SUN-EVE", "python", "Python 小班", "周日", "晚上", 0, 4, 2, 220000),
                ("DA-SUN-PM", "data_analysis", "数据分析进阶班", "周日", "下午", 1, 1, 8, 260000),
            ])
            db.execute("INSERT OR IGNORE INTO enrollments VALUES (?,?,?,?)",
                       ("student_demo", "PY-SAT-AM", 12, 200000))
            db.executemany('INSERT OR IGNORE INTO class_metadata VALUES (?,?)', [
                ('PY-SAT-AM', '张老师'), ('PY-SUN-AM', '张老师'), ('PY-SUN-PM', '李老师'),
                ('PY-SUN-EVE', '张老师'), ('DA-SUN-PM', '陈老师')])

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def result(**values):
        return {"success": True, "demo": True, **values}

    def catalog(self, day="", period="", course="", foundation=None):
        with self.connection() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM classes ORDER BY id")]
        rows = [r for r in rows if (not day or r["day"] == day)
                and (not period or r["period"] == period)
                and (not course or r["course"] == course)
                and (foundation is None or r["level"] <= foundation)]
        return self.result(classes=rows, currency="CNY", note="演示目录；金额字段单位为分；名额以提交时校验为准")

    def enrollment(self, user_id):
        with self.connection() as db:
            row = db.execute("SELECT e.*, c.title, c.day, c.period FROM enrollments e "
                             "JOIN classes c ON e.class_id=c.id WHERE user_id=?", (user_id,)).fetchone()
        return self.result(enrollment=dict(row) if row else None,
                           note="仅 student_demo 有演示报名，其他 ID 不会自动获得他人数据")

    def quote(self, user_id, target_id):
        with self.connection() as db:
            return self._quote(db, user_id, target_id)

    def _quote(self, db, user_id, target_id):
        source = db.execute("SELECT e.*, c.course, c.progress FROM enrollments e "
                            "JOIN classes c ON e.class_id=c.id WHERE user_id=?", (user_id,)).fetchone()
        target = db.execute("SELECT * FROM classes WHERE id=?", (target_id,)).fetchone()
        reasons = []
        if not source:
            reasons.append("未找到当前学员报名")
        if not target:
            reasons.append("目标班级不存在")
        fee = None
        if source and target:
            fee = max(0, target["price_cents"] - source["paid_cents"])
            if source["class_id"] == target_id:
                reasons.append("目标与原班级相同")
            if source["course"] != target["course"]:
                reasons.append("只能在同一课程内转班")
            if source["progress"] != target["progress"]:
                reasons.append("课程进度不匹配")
            if target["seats"] <= 0:
                reasons.append("目标班级已满")
        evidence = self.policy_evidence.assess(db, user_id, target_id, topic='transfer')
        if evidence['status'] != 'eligible':
            reasons.append(evidence.get('reason') or '适用政策条件未全部满足')
        return self.result(eligible=not reasons, reasons=reasons, target_id=target_id,
                           source_id=source["class_id"] if source else None,
                           fee_cents=fee, currency="CNY", policy_version=evidence.get('policy_id'), policy_evidence=evidence,
                           note="演示规则：同课程、同进度且有名额；正差价补缴，低价不自动退款；提交后待人工审核，不立即转班或扣款")

    def activate(self, user_id, conv_id):
        with self.connection() as db:
            db.execute("INSERT OR IGNORE INTO active_tasks VALUES (?,?)", (user_id, conv_id))

    def active(self, user_id, conv_id):
        with self.connection() as db:
            return bool(db.execute("SELECT 1 FROM active_tasks WHERE user_id=? AND conv_id=?",
                                   (user_id, conv_id)).fetchone())

    def latest_draft(self, user_id, conv_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM drafts WHERE user_id=? AND conv_id=? ORDER BY rowid DESC LIMIT 1",
                             (user_id, conv_id)).fetchone()
        return dict(row) if row else None

    def prepare(self, user_id, conv_id, target_id, reason):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            quote = self._quote(db, user_id, target_id)
            if not quote["eligible"]:
                return {**quote, "success": False, "error": "；".join(quote["reasons"])}
            state = self.requirements(user_id, conv_id, db=db)
            failed = self._constraint_failures(db, user_id, state, target_id, quote['fee_cents'])
            if state['ambiguities'] or failed:
                return self.result(success=False, error='目标班级不符合当前要求或需求待澄清', violations=failed, requirements=state)
            db.execute("UPDATE drafts SET status='superseded' WHERE user_id=? AND conv_id=? AND status='awaiting_confirmation'",
                       (user_id, conv_id))
            draft_id = uuid.uuid4().hex[:12]
            db.execute("INSERT INTO drafts VALUES (?,?,?,?,?,?,?,?)",
                       (draft_id, user_id, conv_id, target_id, reason[:200], "awaiting_confirmation",
                        quote["source_id"], quote["fee_cents"]))
            db.execute("INSERT OR IGNORE INTO active_tasks VALUES (?,?)", (user_id, conv_id))
            db.execute('INSERT INTO draft_evidence VALUES (?,?,?)',
                       (draft_id, state['revision'], quote['policy_evidence']['fingerprint']))
        return self.result(draft_id=draft_id, status="awaiting_confirmation", **{
            k: quote[k] for k in ("source_id", "target_id", "fee_cents")},
            confirmation=f"确认提交 {draft_id}", note="只生成草稿，尚未提交。请完整展示班级、原因、差价和确认口令。")

    def submit(self, user_id, conv_id, draft_id):
        """Called only by the deterministic confirmation handler, never exposed as an LLM tool."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            draft = db.execute("SELECT * FROM drafts WHERE id=? AND user_id=? AND conv_id=?",
                               (draft_id, user_id, conv_id)).fetchone()
            if not draft:
                return self.result(success=False, error="未找到当前会话的草稿，请先生成申请")
            existing = db.execute("SELECT * FROM applications WHERE draft_id=?", (draft_id,)).fetchone()
            if existing:
                return self.result(application=dict(existing), replayed=True)
            if draft["status"] != "awaiting_confirmation":
                return self.result(success=False, error="草稿已取消或被更新，请确认最新草稿")
            quote = self._quote(db, user_id, draft["target_id"])
            snapshot = db.execute('SELECT * FROM draft_evidence WHERE draft_id=?', (draft_id,)).fetchone()
            state = self.requirements(user_id, conv_id, db=db)
            stale = (not snapshot or snapshot['revision'] != state['revision']
                     or snapshot['policy_fingerprint'] != quote['policy_evidence'].get('fingerprint'))
            failed = self._constraint_failures(db, user_id, state, draft['target_id'], quote['fee_cents']) if quote['eligible'] else []
            if (not quote["eligible"] or quote["source_id"] != draft["source_id"]
                    or quote["fee_cents"] != draft["fee_cents"] or stale or failed or state['ambiguities']):
                db.execute("UPDATE drafts SET status='invalidated' WHERE id=?", (draft_id,))
                return self.result(success=False, error="班级、费用、政策或用户要求发生变化，请重新生成并确认申请", quote=quote)
            application_id = "T-" + uuid.uuid4().hex[:12]
            db.execute("INSERT INTO applications VALUES (?,?,?,?,?,?,?,?)",
                       (application_id, draft_id, user_id, draft["source_id"], draft["target_id"],
                        draft["reason"], "pending_review", draft["fee_cents"]))
            db.execute("UPDATE drafts SET status='submitted' WHERE id=?", (draft_id,))
            db.execute("DELETE FROM active_tasks WHERE user_id=? AND conv_id=?", (user_id, conv_id))
            db.execute('DELETE FROM transfer_requirements WHERE user_id=? AND conv_id=?', (user_id, conv_id))
            db.execute('DELETE FROM transfer_focus WHERE user_id=? AND conv_id=?', (user_id, conv_id))
            row = db.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone()
        return self.result(application=dict(row), replayed=False)

    def cancel(self, user_id, conv_id):
        with self.connection() as db:
            db.execute("UPDATE drafts SET status='cancelled' WHERE user_id=? AND conv_id=? AND status='awaiting_confirmation'",
                       (user_id, conv_id))
            db.execute("DELETE FROM active_tasks WHERE user_id=? AND conv_id=?", (user_id, conv_id))
            db.execute('DELETE FROM transfer_requirements WHERE user_id=? AND conv_id=?', (user_id, conv_id))
            db.execute('DELETE FROM transfer_focus WHERE user_id=? AND conv_id=?', (user_id, conv_id))
        return self.result(note="已取消当前未提交任务；已提交的申请不会撤回")

    def invalidate_draft(self, user_id, conv_id):
        with self.connection() as db:
            db.execute("UPDATE drafts SET status='superseded' WHERE user_id=? AND conv_id=? AND status='awaiting_confirmation'",
                       (user_id, conv_id))

    def applications(self, user_id):
        with self.connection() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM applications WHERE user_id=? ORDER BY rowid DESC", (user_id,))]
        return self.result(applications=rows, note="pending_review 表示待教务审核；本演示未连接真实审核系统")

    def requirements(self, user_id, conv_id, db=None):
        if db is None:
            with self.connection() as connection:
                return self.requirements(user_id, conv_id, db=connection)
        row = db.execute('SELECT * FROM transfer_requirements WHERE user_id=? AND conv_id=?', (user_id, conv_id)).fetchone()
        if not row:
            return {'revision': 0, 'slots': {}, 'events': [], 'ambiguities': []}
        return {'revision': row['revision'], **{k: json.loads(row[k]) for k in ('slots', 'events', 'ambiguities')}}

    def update_requirements(self, user_id, conv_id, message):
        parsed = extract_updates(message)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self.requirements(user_id, conv_id, db=db)
            if not parsed['updates'] and not parsed['ambiguities']:
                return state
            slots = apply_updates(state, parsed)
            if slots == state['slots'] and parsed['ambiguities'] == state['ambiguities']:
                return state
            revision = state['revision'] + 1
            events = (state['events'] + [{'revision': revision, 'message': message,
                                         'updates': parsed['updates'], 'ambiguities': parsed['ambiguities']}])[-20:]
            db.execute('INSERT OR REPLACE INTO transfer_requirements VALUES (?,?,?,?,?,?)',
                       (user_id, conv_id, revision, json.dumps(slots, ensure_ascii=False),
                        json.dumps(events, ensure_ascii=False), json.dumps(parsed['ambiguities'], ensure_ascii=False)))
            db.execute("UPDATE drafts SET status='superseded' WHERE user_id=? AND conv_id=? AND status='awaiting_confirmation'",
                       (user_id, conv_id))
            return self.requirements(user_id, conv_id, db=db)

    def _constraint_failures(self, db, user_id, state, target_id, fee_cents):
        target = db.execute('SELECT c.*, m.teacher FROM classes c LEFT JOIN class_metadata m ON c.id=m.class_id WHERE c.id=?', (target_id,)).fetchone()
        source = db.execute('SELECT m.teacher FROM enrollments e LEFT JOIN class_metadata m ON e.class_id=m.class_id WHERE e.user_id=?', (user_id,)).fetchone()
        if not target:
            return ['target_id']
        return violations(state['slots'], {**dict(target), 'fee_cents': fee_cents}, source['teacher'] if source else None)

    def advise_transfer(self, user_id, conv_id):
        from agents.transfer_advisor import advise
        with self.connection() as db:
            db.execute('BEGIN')
            return advise(self, db, user_id, conv_id)

    def assess_free_transfer(self, user_id, conv_id, target_id=None):
        with self.connection() as db:
            db.execute('BEGIN')
            target_id = target_id or self.requirements(user_id, conv_id, db=db)['slots'].get('target_id')
            return self.policy_evidence.assess(db, user_id, target_id, topic='free_transfer')

    def focus(self, user_id, conv_id, purpose=None):
        with self.connection() as db:
            if purpose:
                db.execute('INSERT OR REPLACE INTO transfer_focus VALUES (?,?,?)', (user_id, conv_id, purpose))
                db.execute('INSERT OR IGNORE INTO active_tasks VALUES (?,?)', (user_id, conv_id))
            row = db.execute('SELECT purpose FROM transfer_focus WHERE user_id=? AND conv_id=?', (user_id, conv_id)).fetchone()
            return row['purpose'] if row else None
