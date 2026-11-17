"""列出技能包里的抽取剖面及其字段覆盖。

剖面是示例，不是研究领域白名单。审计文本只用来提示哪一份剖面的字段可能接得上，
不够的字段由项目自己的剖面或草稿解析器补，不改技能包。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', default='output/audit/corpus_files.csv')
    parser.add_argument('--out', default='output/coding/profile_candidates.json')
    args = parser.parse_args(argv)
    skill = Path(__file__).resolve().parents[1]
    profiles = []
    for file in sorted((skill / 'profiles').glob('*.json')):
        data = json.loads(file.read_text(encoding='utf-8'))
        fields = []
        for field in data.get('fields') or []:
            if isinstance(field, dict) and field.get('name'):
                fields.append({'name': field['name'], 'label': field.get('label') or field['name']})
        profiles.append({
            'file': f'profiles/{file.name}',
            'id': data.get('profile') or file.stem,
            'description': data.get('description') or '',
            'fields': fields,
        })
    hint = ''
    audit = Path(args.audit)
    if audit.is_file():
        text = audit.read_text(encoding='utf-8', errors='replace')[:200_000]
        if '人民法院' in text or '判决书' in text or '裁定书' in text:
            hint = '审计文本里出现裁判文书用语。profiles/legal-judgment.json 只是字段形状示例，不决定怎么切段。读样本后把起点、结束符和字段写进项目自己的剖面或 draft/ 解析器。'
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {'profiles': profiles, 'hint': hint}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'profiles: {len(profiles)} -> {out.as_posix()}')
    if hint:
        print(hint)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
