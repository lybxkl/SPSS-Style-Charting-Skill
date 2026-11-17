"""列出技能包里的抽取剖面及其字段覆盖。

剖面是字段形状示例，不是研究领域白名单，也不决定怎么切段。读样本后把
起点、结束符和字段写进项目自己的剖面或 draft/ 解析器；不够的字段自己补，
不改技能包。本脚本不嗅探语料、不做任何文体判断。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HINT = ('示例剖面只是字段形状模板：切段起点、取第一次还是最后一次、结束符，'
        '由你读过这批样本后写进项目自己的剖面或 draft/ 解析器；'
        '不要把示例当成这批材料的抽取规则。')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='output/coding/profile_candidates.json')
    args = parser.parse_args(argv)
    skill = Path(__file__).resolve().parents[1]
    profiles = []
    for file in sorted((skill / 'profiles').glob('*.json')):
        data = json.loads(file.read_text(encoding='utf-8'))
        fields = []
        for field in data.get('fields') or []:
            if isinstance(field, dict) and field.get('name'):
                fields.append({'name': field['name'],
                               'label': field.get('label') or field['name']})
        profiles.append({
            'file': f'profiles/{file.name}',
            'id': data.get('profile') or file.stem,
            'description': data.get('description') or '',
            'fields': fields,
        })
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {'profiles': profiles, 'hint': HINT}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
                   encoding='utf-8')
    print(f'profiles: {len(profiles)} -> {out.as_posix()}')
    print(HINT)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
