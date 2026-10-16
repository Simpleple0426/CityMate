"""Conservative, auditable slot updates for transfer conversations (no model training)."""

'''
把用户分散在多轮对话里面的选课需求，整理成一份结构化的数据
'''


import re
from decimal import Decimal

# 同一金额单位
def money_cents(text):
    if re.fullmatch(r"\d+(?:\.\d{1,2})?", text):
        return int(Decimal(text) * 100)
    digits = {c: i for i, c in enumerate('零一二三四五六七八九')}
    digits['两'] = 2
    total, number = 0, 0
    for c in text:
        if c in digits:
            number = digits[c]
        elif c in {'十', '百', '千'}:
            total += (number or 1) * {'十': 10, '百': 100, '千': 1000}[c]
            number = 0
        else:
            raise ValueError('金额无法确定')
    return (total + number) * 100


def extract_updates(message):
    """Only explicit supported statements change slots; uncertainty is returned for clarification."""
    updates, ambiguities = [], []
    def put(field, value, evidence):
        updates.append({'field': field, 'value': value, 'evidence': evidence})

    # 时间要求 关键词匹配
    if any(w in message for w in ('时间不限', '时间都可以', '时间不限制')):
        for field in ('days', 'excluded_days', 'periods', 'excluded_periods'):
            put(field, None, message)
    else:
        for field, pattern in [('days', r'周[一二三四五六日天]|星期[一二三四五六日天]|周末'),
                               ('periods', r'上午|下午|晚上')]:
            allowed, denied = [], []
            matches = list(re.finditer(pattern, message))
            corrections = list(re.finditer(r'改成|改为|换成|换到|改到', message))
            pivot = corrections[-1].end() if corrections else -1
            has_replacement = pivot >= 0 and any(m.start() >= pivot for m in matches)
            for match in matches:
                value = match.group()
                values = ['周六', '周日'] if value == '周末' else [value.replace('星期', '周').replace('周天', '周日')]
                before = message[max(0, match.start()-5):match.start()]
                after = message[match.end():match.end()+7]
                negative = bool(re.search(r'(?:不是|不选|排除|不要|不能在)$', before) or re.match(r'(?:不行|没时间|不能|不方便|要加班)', after))
                if has_replacement and match.start() < pivot and not negative:
                    continue
                # A plain question about a class does not set a scheduling requirement.
                question = any(w in after for w in ('多少钱', '收费', '是什么', '有什么'))
                if question and not negative:
                    continue
                (denied if negative else allowed).extend(values)
            if set(allowed) & set(denied):
                ambiguities.append(f'{field} 中同时出现允许和排除的相同条件，请确认')
            else:
                if allowed:
                    put(field, list(dict.fromkeys(allowed)), message)
                if denied:
                    put('excluded_' + field, list(dict.fromkeys(denied)), message)
                    
    # 费用要求                
    if any(w in message for w in ('不限制费用', '费用不限', '取消费用限制')):
        put('max_fee_cents', None, message)
    else:
        zero = any(w in message for w in ('不想补钱', '不想再掏钱', '不要加钱', '不加钱', '不要额外花钱', '不增加费用', '不接受补差', '必须免费'))
        amount = re.search(r'(?:最多(?:补|加|花)?|不超过|上限(?:是|为)?|预算(?:是|为)?|可以补|能接受(?:补)?)\s*([\d零一二两三四五六七八九十百千]+(?:\.\d{1,2})?)\s*(?:元|块)?', message)
        if zero and amount and money_cents(amount.group(1)) != 0:
            ambiguities.append('费用要求同时包含不补钱和正数预算，请确认以哪个为准')
        elif amount:
            put('max_fee_cents', money_cents(amount.group(1)), amount.group())
        elif zero:
            put('max_fee_cents', 0, message)
    
    # 老师要求
    if any(w in message for w in ('老师不限', '老师无所谓', '取消老师要求')):
        put('same_teacher', None, message)
    elif any(w in message for w in ('老师不能变', '必须同一老师', '必须同一个老师')):
        put('same_teacher', 'required', message)
    elif any(w in message for w in ('老师最好不变', '最好同一老师', '最好同一个老师')):
        put('same_teacher', 'preferred', message)
    target = re.search(r'\b(?:PY|DA)-[A-Z]+-[A-Z]+\b', message)
    if target and not any(w in message for w in ('不选' + target.group(), '不要' + target.group())):
        put('target_id', target.group(), target.group())
    if '取消目标班级' in message:
        put('target_id', None, '取消目标班级')
    return {'updates': updates, 'ambiguities': ambiguities}

# 更新要求
def apply_updates(state, parsed):
    slots = dict(state.get('slots', {}))
    # Ambiguous turns never partially loosen existing conditions.
    if parsed['ambiguities']:
        return slots
    for update in parsed['updates']:
        field, value = update['field'], update['value']
        if value is None:
            slots.pop(field, None)
        elif field.startswith('excluded_'):
            slots[field] = list(dict.fromkeys(slots.get(field, []) + value))
            positive = field.removeprefix('excluded_')
            if positive in slots:
                slots[positive] = [v for v in slots[positive] if v not in value]
        else:
            slots[field] = value
            if field in ('days', 'periods'):
                excluded = 'excluded_' + field
                slots[excluded] = [v for v in slots.get(excluded, []) if v not in value]
    if any(u['field'] != 'target_id' for u in parsed['updates']):
        if not any(u['field'] == 'target_id' for u in parsed['updates']):
            slots.pop('target_id', None)
    return slots


def violations(slots, candidate, source_teacher=None):
    failed = []
    for field, column in [('days', 'day'), ('periods', 'period')]:
        if field in slots and candidate[column] not in slots[field]:
            failed.append(field)
        if candidate[column] in slots.get('excluded_' + field, []):
            failed.append('excluded_' + field)
    if slots.get('max_fee_cents') is not None and candidate['fee_cents'] > slots['max_fee_cents']:
        failed.append('max_fee_cents')
    if slots.get('same_teacher') == 'required' and (not source_teacher or candidate.get('teacher') != source_teacher):
        failed.append('same_teacher')
    if slots.get('target_id') and slots['target_id'] != candidate['id']:
        failed.append('target_id')
    return failed
