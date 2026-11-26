"""Expand parameterized imports in the human-readable device view files."""

import argparse
import copy
import re
import sys
from pathlib import Path

import yaml


MACRO = re.compile(r"\$\{([^{}]+)\}")


class ViewLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        keys = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in keys:
                raise ValueError(f"无效或重复的键 {key!r}（第 {key_node.start_mark.line + 1} 行）")
            keys.add(key)
        return super().construct_mapping(node, deep=deep)

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError("请使用导入引用模板，不能展开 YAML 别名")
        return super().compose_node(parent, index)


def expand_view(entry: Path) -> dict:
    def read(path, params, stack):
        path = path.resolve()
        if path in stack:
            raise ValueError("循环导入：" + " → ".join(p.name for p in (*stack, path)))
        used = set()

        def substitute(value):
            def resolve(match):
                name = match[1]
                if name not in params:
                    raise ValueError(f"缺少宏参数 {name}")
                used.add(name)
                return copy.deepcopy(params[name])

            whole = MACRO.fullmatch(value)
            if whole:
                return resolve(whole)

            def embed(match):
                item = resolve(match)
                if not isinstance(item, (str, float, int)) or isinstance(item, bool):
                    raise ValueError(f"宏 {match[1]} 嵌入文本时须为字符串或数字")
                return str(item)

            return MACRO.sub(embed, value)

        def expand(value):
            if isinstance(value, str):
                return substitute(value)
            if isinstance(value, list):
                return [expand(item) for item in value]
            if not isinstance(value, dict):
                return value

            result = {}

            def insert(key, item):
                if not isinstance(key, str) or key in result:
                    raise ValueError(f"展开后的键无效或冲突：{key!r}")
                result[key] = item

            imports = value.get("导入", [])
            if not isinstance(imports, list):
                raise ValueError("导入须为列表")
            for spec in imports:
                if isinstance(spec, str):
                    spec = {"文件": spec}
                if (not isinstance(spec, dict) or "文件" not in spec
                        or set(spec) - {"文件", "参数"}
                        or not isinstance(spec["文件"], str)
                        or not isinstance(spec.get("参数", {}), dict)):
                    raise ValueError(f"导入项需指定文件和可选参数：{spec!r}")
                child = Path(spec["文件"])
                if child.is_absolute() or child.drive or child.root:
                    raise ValueError("导入文件须使用相对路径")
                arguments = {key: expand(arg) for key, arg in spec.get("参数", {}).items()}
                contents = read(path.parent / child, arguments, (*stack, path))
                for key, item in contents.items():
                    insert(key, item)
            for key, item in value.items():
                if key != "导入":
                    insert(substitute(key), expand(item))
            return result

        try:
            source = yaml.load(path.read_text(encoding="utf-8-sig"), Loader=ViewLoader)
            if not isinstance(source, dict):
                raise ValueError("本体文件顶层须为映射")
            result = expand(source)
            unused = params.keys() - used
            if unused:
                raise ValueError("未使用的宏参数：" + "、".join(sorted(unused)))
            return result
        except (ValueError, OSError, yaml.YAMLError) as error:
            raise ValueError(f"{path}: {error}") from error

    return read(entry, {}, ())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        result = expand_view(args.file)
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    sys.stdout.buffer.write(yaml.safe_dump(result, allow_unicode=True, sort_keys=False).encode("utf-8"))


if __name__ == "__main__":
    main()
