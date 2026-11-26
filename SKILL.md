---
name: industrial-ontology
description: 构建或审查工业设备的实体、数据和物理三视图本体。用于协作编写 YAML、导入带宏的模板、校验设备和数据接口、编译 OWL，以及执行 OWL 2 RL 推理验收。
---

# 工业设备本体构建

编辑前先找项目中的物理视图入口，由它定位安装、数据与型号模板。各专业维护自己掌握的事实。专业手册和计算程序保留原格式，集成人员登记其中的关键量、适用条件、证据与现场数据的对应关系。读取 [建模与检查规则](references/rules.md) 了解输入契约和自动检查的范围。

## 工作方式

1. 为设备、进程、文档分配稳定 ID，沿用已发布的端口和量名。在拥有该事实的模块中修改，将其他视图的关系写为引用。
2. 从 [SBPM 样例](examples/sbpm/束测机箱-物理.yaml) 或用户已有项目开始。复用型号时写带 `${参数}` 的模板，通过相对路径导入。先用 `expand` 核对展开结果。
3. 运行 `check` 核对三个视图。错误须定位并修复，缺少现场依据的项目保留为待确认。把明确的验证问题写入项目验收 YAML，例如“能否从 PV 反查发布进程”。
4. 运行 `compile`，再用 `verify` 重新读取生成的 OWL 并检查推理结果。报告实际执行的用例、未覆盖内容和现场待确认项。

## 执行

工具只需要本地 Python 3.11+ 和 [依赖清单](requirements.txt)。下例以技能目录为当前目录，可在独立虚拟环境运行。处理用户项目时，将示例路径换成项目入口，将输出放在用户指定的构建目录。

```sh
python -m pip install -r requirements.txt
python scripts/ontology.py expand examples/sbpm/双板模板复用.yaml
python scripts/ontology.py check examples/sbpm/束测机箱-物理.yaml
python scripts/ontology.py compile examples/sbpm/束测机箱-物理.yaml --base urn:plant:demo: -o build/device.owl
python scripts/ontology.py verify build/device.owl --tests examples/sbpm/验收.yaml
```

`expand -o 文件.yaml` 可保存 UTF-8 展开结果。用 `--base` 为不同项目分配不同的稳定绝对命名空间。退出码 0 表示本次检查通过，非零时读取标准错误。示例名、地址和现场参数只用于演示。

## 分发与使用

保留整个 `industrial-ontology/` 目录。Codex 项目安装位置为 `.agents/skills/industrial-ontology/`，Claude Code 为 `.claude/skills/industrial-ontology/`。在团队项目中解压到相应位置后，提示 agent：“使用 industrial-ontology 检查此设备本体，生成 OWL 并验证发布者和实体隶属关系。” 其他支持 Agent Skills 的客户端按其发现目录安装；具备本地 Python 执行能力的 agent 也可以直接读取本文件并运行相同命令。
