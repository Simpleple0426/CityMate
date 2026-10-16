"""Offline strategy regression benchmark. No model calls or training data.

Run: python -m evaluation.transfer_benchmark --output data/eval/transfer-strategies.json
This small authored suite is a regression check, not a measure of general language ability.
"""
import argparse
import json
from pathlib import Path
import tempfile
import time

from agents.education_store import EducationStore


CASES = [
    {'name': '保留晚间限制后放宽费用', 'turns': ['周日，不想补钱', '下午不行，只能晚上', '最多补两百元'], 'expected': ['PY-SUN-EVE']},
    {'name': '时间和零费用冲突', 'turns': ['只能周日晚上', '不想补钱'], 'expected': []},
    {'name': '老师硬要求和费用冲突', 'turns': ['老师不能变', '最多补100元'], 'expected': []},
    {'name': '偏好不压过硬预算', 'turns': ['老师最好不变', '不想补钱'], 'expected': ['PY-SUN-PM']},
    {'name': '撤销费用条件后仍保留时间', 'turns': ['只能周日晚上，不想补钱', '费用不限'], 'expected': ['PY-SUN-EVE']},
    {'name': '明确改选时段', 'turns': ['只能周日晚上，最多补200元', '改成下午'], 'expected': ['PY-SUN-PM']},
]


def run_benchmark():
    reports = {}
    for strategy in ('latest_turn_only', 'persistent_requirements'):
        started = time.monotonic()
        results = []
        with tempfile.TemporaryDirectory() as folder:
            store = EducationStore(Path(folder) / 'benchmark.sqlite3')
            for index, case in enumerate(CASES):
                conversation = f'{strategy}-{index}'
                for turn in case['turns']:
                    if strategy == 'latest_turn_only':
                        store.cancel('student_demo', conversation)
                    store.update_requirements('student_demo', conversation, turn)
                result = store.advise_transfer('student_demo', conversation)
                actual = [c['id'] for c in result['candidates']]
                results.append({'case': case['name'], 'expected': case['expected'], 'actual': actual,
                                'passed': actual == case['expected']})
        reports[strategy] = {'passed': sum(r['passed'] for r in results), 'total': len(results),
                             'elapsed_ms': round((time.monotonic() - started) * 1000, 2), 'cases': results}
    return {'scope': '6个人工编写的确定性回归案例；不代表真实模型成功率或泛化能力', 'strategies': reports}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output')
    args = parser.parse_args()
    report = run_benchmark()
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))
