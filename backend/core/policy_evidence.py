"""Retrieve applicable curated policy clauses, then query only their registered facts.

Natural-language policy text and executable predicates are reviewed together in the
knowledge file. Arbitrary uploaded text is never executed as SQL or Python.
"""
from datetime import date
import hashlib
import json
import operator
from pathlib import Path

POLICY_FILE = Path(__file__).resolve().parents[1] / 'data/demo_docs/transfer_policies.json'
OPS = {'eq': operator.eq, 'ne': operator.ne, 'gt': operator.gt,
       'gte': operator.ge, 'lt': operator.lt, 'lte': operator.le}
SOURCE_FIELDS = {'class_id': 'e.class_id', 'course': 'c.course', 'progress': 'c.progress',
                 'paid_cents': 'e.paid_cents', 'remaining': 'e.remaining'}
TARGET_FIELDS = {key: key for key in ('id', 'course', 'progress', 'seats', 'price_cents', 'day', 'period')}


class PolicyEvidence:
    def __init__(self, path=None):
        self.path = Path(path or POLICY_FILE)

    def retrieve(self, topic, course, as_of=None):
        today = as_of or date.today().isoformat()
        try:
            policies = json.loads(self.path.read_text(encoding='utf-8'))
            hits = [p for p in policies if p['topic'] == topic and p['course'] in ('*', course)
                    and p['effective_from'] <= today <= p['effective_to']]
            specific = [p for p in hits if p['course'] == course and course is not None]
            hits = specific or hits
            if len(hits) != 1:
                return {'status': 'unknown', 'reason': '没有适用政策' if not hits else '适用政策版本冲突，需人工核验',
                        'documents': hits}
            policy = hits[0]
            digest = hashlib.sha256(json.dumps(policy, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            return {'status': 'found', 'document': policy, 'fingerprint': digest}
        except (OSError, ValueError, KeyError, TypeError):
            return {'status': 'unknown', 'reason': '政策索引不可用或格式错误', 'documents': []}

    def assess(self, db, user_id, target_id=None, topic='free_transfer', as_of=None):
        # Course identity is required before choosing a course-specific policy.
        identity = db.execute('SELECT c.course FROM enrollments e JOIN classes c ON c.id=e.class_id WHERE e.user_id=?', (user_id,)).fetchone()
        if not identity:
            return {'status': 'unknown', 'reason': '未找到当前学员报名，无法确定适用政策',
                    'missing_fields': ['source.enrollment'], 'checks': [], 'facts': {}}
        found = self.retrieve(topic, identity['course'], as_of)
        if found['status'] != 'found':
            return {**found, 'checks': [], 'facts': {}, 'missing_fields': []}
        policy = found['document']
        try:
            required = set()
            for clause in policy['clauses']:
                if clause['op'] not in OPS or ('right_field' in clause) == ('value' in clause):
                    raise ValueError('政策条件未注册')
                required.add(clause['left'])
                if 'right_field' in clause:
                    required.add(clause['right_field'])
            if not required:
                raise ValueError('空政策不能判定通过')
            facts = {}
            queries = []
            for field in sorted(required):
                side, key = field.split('.', 1)
                if side == 'source' and key in SOURCE_FIELDS:
                    sql = f'SELECT {SOURCE_FIELDS[key]} AS value FROM enrollments e JOIN classes c ON c.id=e.class_id WHERE e.user_id=?'
                    params = (user_id,)
                    provenance = f'enrollments/current_user + classes/current_enrollment:{key}'
                elif side == 'target' and key in TARGET_FIELDS:
                    sql = f'SELECT {TARGET_FIELDS[key]} AS value FROM classes WHERE id=?'
                    params = (target_id,)
                    provenance = f'classes/{target_id or "unselected"}:{key}'
                else:
                    raise ValueError(f'未注册的事实字段：{field}')
                row = db.execute(sql, params).fetchone() if params[0] is not None else None
                facts[field] = {'value': row['value'] if row else None, 'source': provenance}
                queries.append({'field': field, 'source': provenance})
            checks, missing = [], set()
            for clause in policy['clauses']:
                left = facts[clause['left']]['value']
                right = facts[clause['right_field']]['value'] if 'right_field' in clause else clause['value']
                if left is None:
                    missing.add(clause['left'])
                if right is None and 'right_field' in clause:
                    missing.add(clause['right_field'])
                verdict = 'unknown' if left is None or right is None else ('pass' if OPS[clause['op']](left, right) else 'fail')
                checks.append({'clause_id': clause['id'], 'text': clause['text'], 'status': verdict,
                               'left': left, 'right': right, 'citation': f"{policy['id']}#{clause['id']}",
                               'fields': [clause['left']] + ([clause['right_field']] if 'right_field' in clause else [])})
            status = 'ineligible' if any(c['status'] == 'fail' for c in checks) else ('unknown' if missing else 'eligible')
            return {'status': status, 'policy_id': policy['id'], 'version': policy['version'],
                    'title': policy['title'], 'fingerprint': found['fingerprint'], 'checks': checks,
                    'facts': facts, 'query_plan': queries, 'missing_fields': sorted(missing),
                    'question': '你想转到哪个目标班级？' if not target_id else None,
                    'demo': True}
        except (KeyError, TypeError, ValueError):
            return {'status': 'unknown', 'policy_id': policy.get('id'), 'reason': '政策包含未支持或不合法的条件，不能自动作出结论',
                    'checks': [], 'facts': {}, 'missing_fields': []}
