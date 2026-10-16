"""Constraint-aware ranking and explainable policy/database assessment."""
from collections import Counter
from math import log2

from core.transfer_requirements import violations


LABELS = {'days': '上课日期', 'excluded_days': '不可上课日期', 'periods': '上课时段',
          'excluded_periods': '不可上课时段', 'max_fee_cents': '补费上限',
          'same_teacher': '原授课老师', 'target_id': '指定班级'}


def advise(store, db, user_id, conv_id):
    state = store.requirements(user_id, conv_id, db=db)
    if state.get('ambiguities'):
        return {'demo': True, 'status': 'needs_clarification', 'requirements': state,
                'candidates': [], 'question': '；'.join(state['ambiguities'])}
    source = db.execute('SELECT e.*, c.course, m.teacher FROM enrollments e JOIN classes c ON e.class_id=c.id '
                        'LEFT JOIN class_metadata m ON c.id=m.class_id WHERE e.user_id=?', (user_id,)).fetchone()
    if not source:
        return {'demo': True, 'status': 'unknown', 'requirements': state, 'candidates': [],
                'question': '未找到当前学员报名，无法筛选转班方案。演示身份为 student_demo。'}
    rows = [dict(r) for r in db.execute('SELECT c.*, m.teacher FROM classes c LEFT JOIN class_metadata m ON c.id=m.class_id '
                                       'WHERE c.id<>? AND c.course=? ORDER BY c.id', (source['class_id'], source['course']))]
    candidates, rejected = [], []
    for row in rows:
        assessment = store.policy_evidence.assess(db, user_id, row['id'], topic='transfer')
        row['fee_cents'] = max(0, row['price_cents'] - source['paid_cents'])
        failed = violations(state['slots'], row, source['teacher'])
        row['policy'] = assessment
        row['violations'] = failed
        row['preference_score'] = int(state['slots'].get('same_teacher') == 'preferred' and source['teacher'] is not None and row['teacher'] == source['teacher'])
        if assessment['status'] == 'eligible' and not failed:
            candidates.append(row)
        else:
            rejected.append(row)
    candidates.sort(key=lambda r: (-r['preference_score'], r['fee_cents'], r['id']))
    # Explain only single-constraint relaxations that actually produce feasible candidates.
    alternatives = [{'target_id': row['id'], 'requires_relaxation': row['violations'][0],
                     'explanation': f"如果你同意调整{LABELS[row['violations'][0]]}，可考虑 {row['id']}",
                     'fee_cents': row['fee_cents'], 'day': row['day'], 'period': row['period']}
                    for row in rejected if row['policy']['status'] == 'eligible' and len(row['violations']) == 1]
    question = None
    if len(candidates) > 1:
        choices = []
        for field, column in [('days', 'day'), ('periods', 'period')]:
            values = Counter(row[column] for row in candidates)
            entropy = -sum((n / len(candidates)) * log2(n / len(candidates)) for n in values.values())
            if len(values) > 1:
                choices.append((entropy, field, list(values)))
        if choices:
            _, field, values = max(choices, key=lambda item: item[0])
            question = f"你希望{LABELS[field]}是{'还是'.join(values)}？"
        else:
            question = '有多个符合条件的班级，你希望选择哪个班级？'
    elif len(candidates) == 1:
        question = f"{candidates[0]['id']} 符合当前条件。如果想办理，请发送‘帮我转到 {candidates[0]['id']}’。（尚未生成申请）"
    elif alternatives:
        question = '当前条件没有完全匹配的班级。' + alternatives[0]['explanation'] + '，你愿意调整吗？'
    else:
        question = '暂无能确认符合要求的班级。请核对政策或调整条件；当前不会准备申请。'
    return {'demo': True, 'status': 'matched' if candidates else 'no_match', 'requirements': state,
            'candidates': candidates, 'rejected': rejected, 'alternatives': alternatives,
            'question': question, 'ranking': '先满足全部硬性条件，再优先匹配老师偏好，其次费用升序；不会自动放宽条件'}


def render_advice(result):
    lines = ['【演示】根据你当前的要求与适用转班政策：']
    state = result.get('requirements', {})
    for field, value in state.get('slots', {}).items():
        if field == 'max_fee_cents':
            value = f'{value / 100:.2f} 元'
        elif isinstance(value, list):
            value = '、'.join(value) or '无可用选项'
        elif field == 'same_teacher':
            value = '必须不变' if value == 'required' else '最好不变（偏好）'
        lines.append(f"- {LABELS.get(field, field)}：{value}")
    for row in result.get('candidates', []):
        lines.append(f"- {row['id']}：{row['day']}{row['period']}，补差 {row['fee_cents'] / 100:.2f} 元，老师 {row.get('teacher') or '未知'}；依据 {row['policy']['policy_id']}。")
    if not result.get('candidates'):
        for row in result.get('rejected', []):
            reasons = [LABELS[k] + '不满足' for k in row['violations']]
            reasons += [check['text'] for check in row['policy'].get('checks', []) if check['status'] == 'fail']
            if row['policy']['status'] == 'unknown':
                reasons.append(row['policy'].get('reason', '政策证据不足'))
            lines.append(f"- {row['id']}：{'；'.join(reasons)}")
    lines.append(result.get('question') or '')
    lines.append('以上是选班建议，尚未提交申请。明确选择班级后再生成待确认草稿。')
    return '\n'.join(lines)


def render_assessment(result):
    labels = {'eligible': '满足演示免费转班条件', 'ineligible': '不满足演示免费转班条件', 'unknown': '暂时无法确认是否可以免费转班'}
    lines = ['【演示】' + labels[result['status']]]
    if result.get('title'):
        lines.append(f"政策依据：{result['title']}（版本 {result['version']}）。")
    for check in result.get('checks', []):
        label = {'pass': '满足', 'fail': '不满足', 'unknown': '信息不足'}[check['status']]
        values = [check['left'], check['right']]
        for i, field in enumerate(check['fields']):
            if values[i] is not None and field.endswith(('_cents',)):
                values[i] = f'{values[i] / 100:.2f} 元'
        values = ['待查询' if v is None else v for v in values]
        lines.append(f"- {label}：{check['text']} [{check['citation']}]；核验值：{values[0]} / {values[1]}。")
    if result.get('reason'):
        lines.append(result['reason'])
    if result.get('missing_fields'):
        names = {'target.id': '目标班级', 'target.course': '目标课程', 'target.progress': '目标班级进度',
                 'target.seats': '目标班级余位', 'target.price_cents': '目标班级价格', 'source.enrollment': '本人报名记录'}
        lines.append('待补充或核查：' + '、'.join(names.get(f, '报名相关事实') for f in result['missing_fields']))
    if result.get('question'):
        lines.append(result['question'])
    lines.append('以上依据当前报名和班级记录判断，不代表已提交或已审批。')
    return '\n'.join(lines)
