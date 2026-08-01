"""Minimal YAML subset reader/writer for SIPAUTO inventories (stdlib only).

Supports: mappings, lists, scalars (str/int/bool/null), comments, indentation.
Not a full YAML 1.2 implementation — enough for our inventory files.
"""

from __future__ import annotations

import json
import re
from typing import Any


def load(text: str) -> Any:
    text = text.replace("\t", "  ")
    lines = text.splitlines()
    data, _ = _parse_block(lines, 0, 0)
    return data


def dump(data: Any) -> str:
    return _dump_value(data, 0) + ("\n" if not str(data).endswith("\n") else "")


def loads_file(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    if path.endswith(".json"):
        return json.loads(raw)
    return load(raw)


def _parse_block(lines: list[str], idx: int, indent: int) -> tuple[Any, int]:
    # peek first real line
    while idx < len(lines):
        raw = lines[idx]
        if not raw.strip() or raw.lstrip().startswith("#"):
            idx += 1
            continue
        break
    else:
        return {}, idx

    first = lines[idx]
    cur_indent = len(first) - len(first.lstrip(" "))
    if cur_indent < indent:
        return {}, idx
    if first.lstrip().startswith("- "):
        return _parse_list(lines, idx, cur_indent)
    return _parse_map(lines, idx, cur_indent)


def _parse_map(lines: list[str], idx: int, indent: int) -> tuple[dict, int]:
    result: dict[str, Any] = {}
    while idx < len(lines):
        raw = lines[idx]
        if not raw.strip() or raw.lstrip().startswith("#"):
            idx += 1
            continue
        cur = len(raw) - len(raw.lstrip(" "))
        if cur < indent:
            break
        if cur > indent:
            break
        line = raw.strip()
        if line.startswith("- "):
            break
        if ":" not in line:
            idx += 1
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest:
            result[key] = _parse_scalar(rest)
            idx += 1
        else:
            # nested
            child, idx = _parse_block(lines, idx + 1, indent + 2)
            result[key] = child
    return result, idx


def _parse_list(lines: list[str], idx: int, indent: int) -> tuple[list, int]:
    result: list[Any] = []
    while idx < len(lines):
        raw = lines[idx]
        if not raw.strip() or raw.lstrip().startswith("#"):
            idx += 1
            continue
        cur = len(raw) - len(raw.lstrip(" "))
        if cur < indent:
            break
        if cur > indent:
            break
        line = raw.strip()
        if not line.startswith("- "):
            break
        item = line[2:].strip()
        if not item:
            child, idx = _parse_block(lines, idx + 1, indent + 2)
            result.append(child)
        elif item.endswith(":") and ":" == item[-1]:
            # rare "- key:" form
            key = item[:-1].strip()
            child, idx = _parse_block(lines, idx + 1, indent + 2)
            result.append({key: child})
        else:
            # inline map "- key: val" or scalar
            if ":" in item and not item.startswith("{") and not re.match(r"^.+:\s*$", item):
                # could be "key: value" single pair OR scalar with colon
                k, _, v = item.partition(":")
                if v.strip() != "" and " " not in k:
                    # treat as one-line map only if looks like key
                    result.append({k.strip(): _parse_scalar(v.strip())})
                else:
                    result.append(_parse_scalar(item))
            else:
                result.append(_parse_scalar(item))
            idx += 1
    return result, idx


def _parse_flow(text: str) -> Any:
    """Parse simple flow collections: [a, b] or {k: v}."""
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        parts = _split_flow(inner)
        return [_parse_scalar(p.strip()) for p in parts]
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1].strip()
        if not inner:
            return {}
        result = {}
        for part in _split_flow(inner):
            if ":" not in part:
                continue
            k, _, v = part.partition(":")
            result[k.strip()] = _parse_scalar(v.strip())
        return result
    return None


def _split_flow(inner: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    quote = ""
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            continue
        if ch in "[{":
            depth += 1
            buf.append(ch)
            continue
        if ch in "]}":
            depth -= 1
            buf.append(ch)
            continue
        if ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return parts


def _parse_scalar(text: str) -> Any:
    if text.startswith("#"):
        return None
    # strip inline comment for unquoted
    if text and text[0] not in "'\"" and " #" in text:
        text = text.split(" #", 1)[0].rstrip()
    if text in ("null", "~", ""):
        return None
    if text in ("true", "True"):
        return True
    if text in ("false", "False"):
        return False
    flow = _parse_flow(text)
    if flow is not None:
        return flow
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        return text[1:-1]
    try:
        if re.fullmatch(r"-?\d+", text):
            return int(text)
    except ValueError:
        pass
    return text


def _dump_value(data: Any, indent: int) -> str:
    sp = "  " * indent
    if isinstance(data, dict):
        if not data:
            return "{}"
        parts = []
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                parts.append(f"{sp}{k}:")
                nested = _dump_value(v, indent + 1)
                parts.append(nested)
            else:
                parts.append(f"{sp}{k}: {_dump_scalar(v)}")
        return "\n".join(parts)
    if isinstance(data, list):
        if not data:
            return f"{sp}[]" if indent else "[]"
        parts = []
        for item in data:
            if isinstance(item, (dict, list)):
                parts.append(f"{sp}-")
                # awkward for nested; dump dict keys indented
                nested = _dump_value(item, indent + 1)
                parts.append(nested)
            else:
                parts.append(f"{sp}- {_dump_scalar(item)}")
        return "\n".join(parts)
    return f"{sp}{_dump_scalar(data)}"


def _dump_scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "" or any(c in s for c in ":#{}[],&*?|>!%@`") or s.strip() != s:
        return json.dumps(s)
    return s
