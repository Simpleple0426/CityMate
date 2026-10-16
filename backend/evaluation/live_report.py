"""Render a readable summary of saved evaluation evidence."""
import argparse
import json
from pathlib import Path


def render(report):
    s = report.get('summary', {})
    lines = ['# CoursePilot 真实模型评测', '',
             f"模型：{report['model']}；模式：{report['mode']}；状态：{report['status']}", '',
             f"程序检查通过 {s.get('passed', 0)}/{s.get('executed', 0)}，计划 {s.get('planned', 0)} 个场景。",
             f"聊天请求 {s.get('chat_calls', '未区分')}，远端向量请求 {s.get('embedding_calls', '未统计')}，服务端返回 token 总量 {s.get('total_tokens', 0)}。",
             f"每轮耗时 P50/P95：{s.get('turn_p50_ms')} / {s.get('turn_p95_ms')} ms。", '',
             '| 场景 | 结果 | 模型请求数 | 未通过检查 |', '|---|---|---:|---|']
    for row in report['cases']:
        failed = [f"第{i+1}轮 {c['check']}" for i, t in enumerate(row['turns']) for c in t['checks'] if not c['passed']]
        if row.get('error_type'):
            failed.append(row['error_type'])
        lines.append(f"| {row['id']} | {'通过' if row['passed'] else '失败'} | {row.get('model_calls', 0)} | {'；'.join(failed) or '—'} |")
    lines += ['', '## 解释范围', '',
              '- full 经 ASGI HTTP 调用真实后端、Redis、Chroma 和 MCP，未操作浏览器。',
              '- 人工回归集，只检查预设业务状态与工具行为；回复质量仍需人工审阅。',
              '- 每轮 JSON 包含实际回复、工具轨迹及数据库快照；确定性处理成功不等于模型推理成功。',
              '- 请求数不单独统计 SDK 内部重试或 Chroma 本地 embedding，token 数不等于费用。',
              '- 未执行 Skill 对照时，不能声称 Skill 带来量化提升。']
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('report')
    path = Path(parser.parse_args().report)
    path.with_suffix('.md').write_text(render(json.loads(path.read_text(encoding='utf-8'))), encoding='utf-8')
