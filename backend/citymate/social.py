import base64
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, delete
from .models import User, Note, Like, Follow, Checkin, public
from .service import fail, uid


class Social:
    def people(self, user_id):
        with self.db() as db:
            following = set(
                db.scalars(select(Follow.target_id).where(Follow.user_id == user_id)).all()
            )
            users = db.scalars(select(User).where(User.id != user_id).limit(50)).all()
            return [
                {"id": u.id, "nickname": u.nickname, "bio": u.bio, "following": u.id in following}
                for u in users
            ]

    def create_note(self, user_id, values):
        if values.get("shop_id"):
            self.shop(values["shop_id"])
        note_id = self.identifier()
        with self.db.begin() as db:
            note = Note(
                id=note_id,
                user_id=user_id,
                shop_id=values.get("shop_id") or None,
                title=values["title"],
                body=values["body"],
                images=json.dumps(values.get("images", [])),
            )
            db.add(note)
            self.emit(db, "note", {"note_id": note_id})
        return self.note(note_id, user_id)

    def note(self, note_id, viewer):
        with self.db() as db:
            note = db.get(Note, note_id)
            if not note:
                fail(404, "笔记不存在")
            data = public(note)
            data["author"] = db.get(User, note.user_id).nickname
            data["images"] = json.loads(note.images)
            data["likes"] = db.scalar(
                select(func.count()).select_from(Like).where(Like.note_id == note_id)
            )
            data["liked"] = bool(db.get(Like, (viewer, note_id)))
            data["following"] = bool(db.get(Follow, (viewer, note.user_id)))
            first = db.execute(
                select(User.id, User.nickname)
                .join(Like, Like.user_id == User.id)
                .where(Like.note_id == note_id)
                .order_by(Like.created_at, User.id)
                .limit(5)
            ).all()
            data["first_likers"] = [{"id": i, "nickname": n} for i, n in first]
            return data

    def notes(self, viewer, page=1):
        with self.db() as db:
            ids = db.scalars(
                select(Note.id)
                .order_by(Note.created_at.desc(), Note.id.desc())
                .offset((page - 1) * 20)
                .limit(20)
            ).all()
        return [self.note(i, viewer) for i in ids]

    def like(self, user_id, note_id, enabled):
        with self.r.lock(self.key("lock:like:" + note_id), timeout=10, blocking_timeout=3):
            with self.db.begin() as db:
                if not db.get(Note, note_id):
                    fail(404, "笔记不存在")
                old = db.get(Like, (user_id, note_id))
                if enabled and not old:
                    db.add(Like(user_id=user_id, note_id=note_id))
                elif not enabled and old:
                    db.delete(old)
            with self.db() as db:
                likes = db.scalars(select(Like).where(Like.note_id == note_id)).all()
                mapping = {
                    v.user_id: v.created_at.replace(tzinfo=timezone.utc).timestamp() * 1000
                    for v in likes
                }
                pipe = self.r.pipeline()
                pipe.delete(self.key("likes:" + note_id))
                if mapping:
                    pipe.zadd(self.key("likes:" + note_id), mapping)
                pipe.execute()
        return self.note(note_id, user_id)

    def _sync_follows(self, user_id):
        with self.db() as db:
            ids = db.scalars(select(Follow.target_id).where(Follow.user_id == user_id)).all()
        pipe = self.r.pipeline()
        pipe.delete(self.key("following:" + user_id))
        if ids:
            pipe.sadd(self.key("following:" + user_id), *ids)
        pipe.execute()
        return ids

    def follow(self, user_id, target_id, enabled):
        if user_id == target_id:
            fail(400, "不能关注自己")
        self.user(target_id)
        with self.r.lock(self.key("lock:follow:" + user_id), timeout=10, blocking_timeout=3):
            with self.db.begin() as db:
                old = db.get(Follow, (user_id, target_id))
                if enabled and not old:
                    db.add(Follow(user_id=user_id, target_id=target_id))
                elif not enabled and old:
                    db.delete(old)
            self._sync_follows(user_id)
            self.rebuild_feed(user_id)
        return {"following": enabled}

    def common(self, user_id, target_id):
        self.user(target_id)
        self._sync_follows(user_id)
        self._sync_follows(target_id)
        ids = self.r.sinter(self.key("following:" + user_id), self.key("following:" + target_id))
        return [self.user(i) for i in sorted(ids)]

    def rebuild_feed(self, user_id):
        with self.db() as db:
            notes = db.scalars(
                select(Note)
                .join(Follow, Follow.target_id == Note.user_id)
                .where(Follow.user_id == user_id)
                .order_by(Note.created_at.desc(), Note.id.desc())
                .limit(500)
            ).all()
        pipe = self.r.pipeline()
        pipe.delete(self.key("feed:" + user_id))
        if notes:
            pipe.zadd(
                self.key("feed:" + user_id),
                {
                    n.id: int(n.created_at.replace(tzinfo=timezone.utc).timestamp() * 1000)
                    for n in notes
                },
            )
        pipe.set(self.key("feed-built:" + user_id), "1", ex=3600)
        pipe.execute()

    def deliver_note(self, note_id, db):
        note = db.get(Note, note_id)
        if not note:
            return
        followers = db.scalars(select(Follow.user_id).where(Follow.target_id == note.user_id)).all()
        score = int(note.created_at.replace(tzinfo=timezone.utc).timestamp() * 1000)
        pipe = self.r.pipeline()
        for user_id in followers:
            pipe.zadd(self.key("feed:" + user_id), {note_id: score})
            pipe.zremrangebyrank(self.key("feed:" + user_id), 0, -501)
        pipe.execute()

    def feed(self, user_id, cursor=None):
        if not self.r.exists(self.key("feed-built:" + user_id)):
            self.rebuild_feed(user_id)
        score, offset = "+inf", 0
        if cursor:
            try:
                score, offset = json.loads(base64.urlsafe_b64decode(cursor).decode())
                score, offset = float(score), int(offset)
                if offset < 0 or offset > 500:
                    raise ValueError()
            except Exception:
                fail(400, "分页游标无效")
        rows = self.r.zrevrangebyscore(
            self.key("feed:" + user_id), score, "-inf", start=offset, num=10, withscores=True
        )
        result = []
        with self.db() as db:
            following = set(
                db.scalars(select(Follow.target_id).where(Follow.user_id == user_id)).all()
            )
        for note_id, _ in rows:
            note = self.note(note_id, user_id)
            if note["user_id"] in following:
                result.append(note)
        next_cursor = None
        if len(rows) == 10:
            end = rows[-1][1]
            ties = sum(1 for _, s in rows if s == end) + (offset if end == score else 0)
            next_cursor = base64.urlsafe_b64encode(json.dumps([end, ties]).encode()).decode()
        return {"items": result, "next_cursor": next_cursor}

    def checkin(self, user_id):
        today = datetime.now(ZoneInfo(self.cfg.timezone)).date().isoformat()
        with self.r.lock(self.key("lock:checkin:" + user_id), timeout=10, blocking_timeout=3):
            with self.db.begin() as db:
                replayed = db.get(Checkin, (user_id, today)) is not None
                if not replayed:
                    db.add(Checkin(user_id=user_id, day=today))
            result = self.checkin_stats(user_id)
        return {**result, "replayed": replayed}

    def checkin_stats(self, user_id):
        today = datetime.now(ZoneInfo(self.cfg.timezone)).date()
        with self.db() as db:
            rows = db.scalars(select(Checkin).where(Checkin.user_id == user_id)).all()
        days = {r.day for r in rows}
        pipe = self.r.pipeline()
        for day in days:
            date = datetime.strptime(day, "%Y-%m-%d").date()
            key = self.key(f"sign:{user_id}:{date:%Y%m}")
            pipe.setbit(key, date.day - 1, 1)
        points = sum(r.points for r in rows)
        pipe.zadd(self.key("ranking"), {user_id: points})
        pipe.execute()
        streak, cursor = 0, today if today.isoformat() in days else today - timedelta(days=1)
        while cursor.isoformat() in days:
            streak += 1
            cursor -= timedelta(days=1)
        month_key = self.key(f"sign:{user_id}:{today:%Y%m}")
        return {
            "signed_today": today.isoformat() in days,
            "streak": streak,
            "points": points,
            "month_days": self.r.bitcount(month_key),
            "date": today.isoformat(),
        }

    def ranking(self):
        # SQL ledger permits a deterministic rebuild after Redis loss.
        with self.r.lock(self.key("lock:ranking"), timeout=10, blocking_timeout=2):
            with self.db() as db:
                points = {
                    user_id: int(total)
                    for user_id, total in db.execute(
                        select(Checkin.user_id, func.sum(Checkin.points)).group_by(Checkin.user_id)
                    ).all()
                }
            if points:
                self.r.zadd(self.key("ranking"), points)
            rows = self.r.zrevrange(self.key("ranking"), 0, 19, withscores=True)
        return [{"user": self.user(i), "points": int(p)} for i, p in rows]
