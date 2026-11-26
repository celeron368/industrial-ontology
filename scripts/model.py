"""Compile the three device views into an OWL graph after reference checks."""
from pathlib import Path
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from view_imports import expand_view

V = Namespace("urn:industrial-ontology:vocab:")


def require(ok, message):
    if not ok:
        raise ValueError(message)


class Model:
    def __init__(self, base):
        self.base = base
        self.graph = Graph()
        self.graph.bind("v", V)
        self.graph.add((URIRef(base), RDF.type, OWL.Ontology))
        self.entities = {}
        self.ports = {}
        self.warnings = []
        for prop, inverse in [('partOf', 'hasPart'), ('runsOn', 'hosts'), ('publishes', 'publishedBy')]:
            self.graph.add((V[prop], OWL.inverseOf, V[inverse]))
        self.graph.add((V.partOf, RDF.type, OWL.TransitiveProperty))
        self.graph.add((V.connectedTo, RDF.type, OWL.SymmetricProperty))

    def node(self, kind, *parts):
        return URIRef(self.base + kind + '/' + '/'.join(quote(str(x), safe='') for x in parts))

    def link(self, source, prop, target):
        self.graph.add((V[prop], RDF.type, OWL.ObjectProperty))
        self.graph.add((source, V[prop], target))

    def value(self, subject, prop, value):
        self.graph.add((V[prop], RDF.type, OWL.DatatypeProperty))
        self.graph.add((subject, V[prop], Literal(value)))

    def typed(self, subject, kind, label):
        self.graph.add((kind, RDF.type, OWL.Class))
        self.graph.add((subject, RDF.type, kind))
        self.graph.add((subject, RDFS.label, Literal(label)))
        return subject

    def entity(self, key):
        require(key in self.entities, f"未定义实体 {key}")
        return self.node('entity', key)

    def register(self, key, spec, folder):
        require(key not in self.entities, f"重复实体 ID {key}")
        require(isinstance(spec.get('类型'), str) and spec['类型'], f"{key} 缺少类型")
        self.entities[key] = spec
        entity = self.typed(self.entity(key), self.node('class', spec['类型']), key)
        history = expand_view(folder / '历史' / (key + '.yaml'))
        require(history.get('实体ID') == key and isinstance(history.get('操作记录'), list),
                f"{key} 历史文件不匹配")
        self.value(entity, 'historyFile', f'历史/{key}.yaml')
        for attr, val in spec.get('属性', {}).items():
            if val is None:
                self.warnings.append(f"{key}.{attr} 待补")
                continue
            require(isinstance(val, (str, float, bool, int)), f"{key}.{attr} 应为标量")
            # RDF/XML predicates need an XML-safe local name even for labels containing spaces.
            prop = self.node('attribute', 'a' + attr.encode('utf-8').hex())
            self.graph.add((prop, RDF.type, OWL.DatatypeProperty))
            self.graph.add((prop, RDFS.label, Literal(attr)))
            self.graph.add((entity, prop, Literal(val)))
        for kind, ports in spec.get('接口', {}).items():
            require(isinstance(ports, list), f"{key}.{kind} 接口须为列表")
            for port in ports:
                name = f'{key}.{port}'
                require(name not in self.ports, f"重复接口 {name}")
                obj = self.typed(self.node('port', key, port), self.node('port-type', kind), name)
                self.ports[name] = (key, kind, obj)
                self.link(obj, 'partOf', entity)
        return entity


def build(entry: Path, base):
    entry = entry.resolve()
    folder = entry.parent
    physical = expand_view(entry)
    installation = expand_view(folder / physical['安装视图'])
    data_path = folder / physical['数据视图']
    data = expand_view(data_path)
    require((physical['视图'], installation['视图'], data['视图']) == ('物理', '安装', '数据'),
            '视图类型错误')
    require((data_path.parent / data['安装视图']).resolve() == (folder / physical['安装视图']).resolve(),
            '两个视图须引用同一安装文件')
    root = physical['所属实体']
    require(data['所属实体'] == root, '所属实体不一致')
    model = Model(base)
    wires = []

    def install(key, spec):
        entity = model.register(key, spec, folder)
        for child, definition in spec.get('实体', {}).items():
            model.link(install(child, definition), 'partOf', entity)
        wires.extend(spec.get('连接', []))
        return entity

    install(root, installation[root])
    hardware = set(model.entities)
    rules = installation.get('接口连接规则', {})
    occupied = set()
    for a, b in wires:
        _, ka, pa = model.ports[a]
        _, kb, pb = model.ports[b]
        require(kb in rules.get(ka, []) or ka in rules.get(kb, []), f"不兼容的连接 {a} / {b}")
        require(a != b, f"接口自连 {a}")
        for key, kind in ((a, ka), (b, kb)):
            if kind in installation.get('独占接口类型', ['MicroTCA AMC 插槽']):
                require(key not in occupied, f"接口重复占用 {key}")
                occupied.add(key)
        model.link(pa, 'connectedTo', pb)
    for view in (physical, data):
        for key, spec in view.get('实体', {}).items():
            model.register(key, spec, folder)
    interfaces = data.get('数据接口', {})
    paths = data.get('数据连接', {})
    for name, spec in interfaces.items():
        obj = model.typed(model.node('interface', name), V.DataInterface, name)
        model.value(obj, 'interfaceType', spec['类型'])
        model.link(obj, 'carriedBy', model.ports[spec['承载于']][2])
    for name, hops in paths.items():
        require(isinstance(hops, list) and len(hops) >= 2, f"无效路径 {name}")
        path = model.typed(model.node('path', name), V.ControlPath, name)
        for index, hop in enumerate(hops):
            require(hop in interfaces, f"{name} 未定义数据接口 {hop}")
            step = model.node('hop', name, index)
            model.link(path, 'hasHop', step)
            model.value(step, 'index', index)
            model.link(step, 'interface', model.node('interface', hop))

    pv_owners = {}
    def physical_entity(key):
        require(key in hardware, f"实物未定义 {key}")
        return model.entity(key)

    for key, spec in data.get('实体', {}).items():
        obj = model.entity(key)
        if spec['类型'].endswith(('进程', '程序')) or '控制对象' in spec or '运行于' in spec:
            model.link(obj, 'runsOn', physical_entity(spec['运行于']))
        if '参考手册' in spec:
            target = spec['参考手册']
            require(model.entities[target]['类型'] == '文档', f"{target} 应为文档")
            model.link(obj, 'manual', model.entity(target))
        if '接收指令于' in spec:
            interface = spec['接收指令于']
            require(model.ports[interfaces[interface]['承载于']][0] == spec['运行于'], f"{key} 服务接口宿主错误")
            model.link(obj, 'listensOn', model.node('interface', interface))
        for key2, field, pred in [('监测','属性','monitors'), ('操作','指令','operates')]:
            if key2 in spec:
                targets = spec[key2]['对象']
                for target in targets if isinstance(targets, list) else [targets]:
                    for item in spec[key2][field]:
                        capability = model.node('capability', key, key2, target, item)
                        model.link(obj, pred, capability)
                        model.link(capability, 'target', physical_entity(target))
                        model.value(capability, 'name', item)
        for target, route in spec.get('控制对象', {}).items():
            hops = paths[route]
            ends = [model.ports[interfaces[h]['承载于']][0] for h in (hops[0], hops[-1])]
            require(ends == [spec['运行于'], target], f"{key} 控制 {target} 的路径 {route} 端点错误")
            model.link(obj, 'controls', physical_entity(target))
            model.link(obj, 'usesPath', model.node('path', route))
        if spec['类型'] == 'IOC进程':
            listing = data_path.parent / spec['PV列表']
            count = 0
            for line in listing.read_text(encoding='utf-8-sig').splitlines():
                pv = line.strip()
                if not pv or pv.startswith('#'):
                    continue
                require(pv not in pv_owners, f"PV 名重复 {pv}")
                pv_owners[pv] = key
                count += 1
                model.link(obj, 'publishes', model.typed(model.node('pv', pv), V.PV, pv))
            model.value(obj, 'inventory', spec['PV列表'])
            if not count:
                model.warnings.append(f"{key} 的 PV 清单为空，需现场确认")

    template = expand_view(folder / physical['模板']) if '模板' in physical else {}
    mapping = data.get('PV映射', {})
    bindings = mapping.get('板卡绑定', {})
    rules = mapping.get('命名规则', {})
    measurements = physical.get('测量实例', {})
    generated = set()
    for card, binding in bindings.items():
        physical_entity(card)
        ioc = binding['IOC']
        require(model.entities[ioc]['类型'] == 'IOC进程', f"{ioc} 应为 IOC进程")
        require(card in model.entities[ioc].get('控制对象', {}), f"{ioc} 未声明控制 {card}")
        channels = measurements.get(card, {}).get('输入通道', [])
        for term, rule in rules.items():
            grouped = '{通道}' in rule['名称']
            require(not grouped or channels, f"{card}.{term} 缺少通道")
            for ch in channels if grouped else [None]:
                pv = rule['名称'].replace('{前缀}', binding['前缀'])
                if grouped:
                    pv = pv.replace('{通道}', ch)
                require('{' not in pv and '}' not in pv, f"未知 PV 占位符 {pv}")
                require(pv not in generated and pv_owners.get(pv) == ioc, f"{pv} 重复或不在 {ioc} 清单中")
                generated.add(pv)
                pid = model.node('pv', pv)
                model.link(model.node('quantity', card, term), 'boundPV', pid)
                model.link(pid, 'onDevice', physical_entity(card))
                if ch is not None:
                    model.link(pid, 'channel', model.ports[f'{card}.{ch}'][2])
                if rule.get('访问') is None:
                    model.warnings.append(f"{pv} 读写权限待核对")
                else:
                    model.value(pid, 'access', rule['访问'])

    for card, measure in measurements.items():
        device = physical_entity(card)
        if '适用型号' in template:
            require(model.entities[card].get('属性', {}).get('型号') == template['适用型号'], f"{card} 型号不匹配")
        for index, stage in enumerate(template.get('位置测量', {}).get('处理顺序', [])):
            step = model.node('processing', card, index)
            model.link(device, 'processingStep', step)
            model.value(step, 'index', index)
            model.value(step, 'name', stage)
        if '位置测量' in template:
            model.value(device, 'inputQuantity', template['位置测量']['输入'])
            model.value(device, 'outputQuantity', template['位置测量']['输出'])
        for mode in template.get('触发模式', []):
            model.value(device, 'triggerMode', mode)
        if '探头' in measure:
            probe = measure['探头']
            model.link(device, 'measuresWith', physical_entity(probe))
            for channel in measure['输入通道']:
                port = f'{card}.{channel}'
                require(any(port in (a,b) and model.ports[b if a == port else a][0] == probe
                            for a,b in wires), f"{port} 缺少来自 {probe} 的接线")
                model.link(device, 'measurementInput', model.ports[port][2])
        if '参考文档' in measure:
            doc = measure['参考文档']
            spec = model.entities[doc]
            require(spec['类型'] == '文档', f"{doc} 应为文档")
            require((folder / spec['属性']['资源地址']).is_file(), f"{doc} 文档不存在")
            model.link(device, 'references', model.entity(doc))
            for name, term in spec.get('物理量与PV映射', {}).items():
                require(term in rules and card in bindings, f"{card} 文档量 {name} 缺少 PV 映射")
                q = model.typed(model.node('quantity', card, term), V.Quantity, name)
                model.link(model.entity(doc), 'describes', q)
                model.link(q, 'onDevice', device)
    return model
