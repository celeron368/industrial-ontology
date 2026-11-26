# Industrial Ontology

用于工业设备三视图建模的 Agent Skill。工具支持 YAML 模板导入与宏展开、跨视图检查、OWL 编译及 OWL 2 RL 推理验收，附带可运行的 SBPM 示例。

## 安装

将本仓库克隆到项目的技能目录，保留目录名 industrial-ontology。

- Codex：`.agents/skills/industrial-ontology/`
- Claude Code：`.claude/skills/industrial-ontology/`

在仓库根目录使用 Python 3.11 或更高版本运行：

```sh
python -m pip install -r requirements.txt
python scripts/ontology.py check examples/sbpm/束测机箱-物理.yaml
python scripts/ontology.py compile examples/sbpm/束测机箱-物理.yaml -o build/device.owl
python scripts/ontology.py verify build/device.owl --tests examples/sbpm/验收.yaml
```

[技能入口](SKILL.md) · [建模与检查规则](references/rules.md)
