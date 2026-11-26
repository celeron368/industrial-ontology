"""Portable command line for editing, checking and delivering device ontologies."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import yaml
from owlrl import DeductiveClosure, OWLRL_Semantics
from owlrl.Namespaces import ERRNS
from rdflib import Graph, RDF, OWL

from model import Model, V, build, require
from view_imports import expand_view


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        pending = Path(tmp.name)
    try:
        pending.write_bytes(content)
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


def verify(file, cases):
    graph = Graph().parse(file, format='xml')
    names = list(graph.subjects(RDF.type, OWL.Ontology))
    require(len(names) == 1, "需要一个本工具生成的 OWL 本体")
    model = Model(str(names[0]))
    asserted = set(graph)
    DeductiveClosure(OWLRL_Semantics).expand(graph)
    errors = list(graph.objects(None, ERRNS.error))
    require(not errors, 'OWL RL 矛盾：' + '；'.join(map(str, errors)))
    results = []
    for case in cases:
        subject, prop, obj = case['三元组']
        triple = (model.node(*subject), V[prop], model.node(*obj))
        mode = case['预期']
        require(mode in ('存在', '推得', '未导出'), f'不支持的预期 {mode}')
        present = triple in graph
        passed = {'存在': present, '推得': present and triple not in asserted,
                  '未导出': not present}[mode]
        results.append({'用例': case['名称'], '预期': mode, '通过': passed})
    print(json.dumps({'显式三元组': len(asserted), '闭包三元组': len(graph),
                      '用例': results}, ensure_ascii=False, indent=2))
    require(all(r['通过'] for r in results), "推理验收失败")


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    for cmd in ('expand', 'check', 'compile', 'verify'):
        op = sub.add_parser(cmd)
        op.add_argument('file', type=Path)
        if cmd in ('expand', 'compile'):
            op.add_argument('-o', type=Path, required=(cmd == 'compile'))
        if cmd in ('check', 'compile'):
            op.add_argument('--base', default='urn:industrial:example:')
        if cmd == 'verify':
            op.add_argument('--tests', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.cmd == 'verify':
            cases = expand_view(args.tests)['用例']
            require(isinstance(cases, list) and cases, '需要至少一项验收用例')
            verify(args.file, cases)
        elif args.cmd == 'expand':
            raw = yaml.safe_dump(expand_view(args.file), sort_keys=False,
                                 allow_unicode=True).encode('utf-8')
            if args.o:
                require(args.o.resolve() != args.file.resolve(), '请指定独立输出文件')
                write(args.o, raw)
            else:
                sys.stdout.buffer.write(raw)
        else:
            require(args.base.startswith(('urn:', 'https://', 'http://')) and
                    args.base.endswith((':', '/', '#')), '命名空间须为绝对 IRI，以 : / 或 # 结尾')
            model = build(args.file, args.base)
            if args.cmd == 'compile':
                require(args.o.suffix.lower() in ('.owl', '.rdf'), '输出扩展名使用 .owl 或 .rdf')
                raw = model.graph.serialize(format='xml', encoding='utf-8')
                Graph().parse(data=raw, format='xml')
                write(args.o, raw)
            print(json.dumps({'结构检查': '通过', '实体数': len(model.entities),
                              '三元组数': len(model.graph), '待补证据': model.warnings},
                             ensure_ascii=False, indent=2))
    except (ValueError, OSError, TypeError, KeyError, AttributeError, IndexError) as error:
        parser.exit(1, f'{args.file}: {error}\n')


if __name__ == '__main__':
    main()
