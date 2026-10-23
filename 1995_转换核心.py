"""标准库 JSON → CSV 文件转换：保留原文与数值精度，不清洗数据。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_ROWS = 100000
MAX_COLUMNS = 1000
CSV_NAME = "1995_转换结果.csv"
NOTES_NAME = "1995_转换说明.json"


def _no_links(path):
    """解析之前检查路径和所有祖先；不创建文件或目录。"""
    try:
        path = Path(path).absolute()
        for item in (path, *path.parents):
            if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
                raise ValueError("不允许符号链接、目录连接点或带链接的祖先路径")
        return path
    except (TypeError, OSError):
        raise ValueError("文件路径无效或不可访问") from None


def _read_source(input_path):
    path = _no_links(input_path)
    try:
        if not path.is_file():
            raise ValueError("输入必须是存在的普通文件")
        before = path.stat()
        if before.st_size > MAX_INPUT_BYTES:
            raise ValueError("输入文件超过20MiB限制")
        with path.open("rb") as stream:
            payload = stream.read(MAX_INPUT_BYTES + 1)
        after = path.stat()
        if len(payload) > MAX_INPUT_BYTES:
            raise ValueError("输入文件超过20MiB限制")
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns or len(payload) != before.st_size:
            raise ValueError("读取过程中输入文件发生变化")
        return payload
    except OSError:
        raise ValueError("无法读取输入文件") from None


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON对象存在重复字段")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("JSON不允许NaN或Infinity")


def _check_values(value):
    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("JSON数值必须有限")
    elif isinstance(value, dict):
        for key, item in value.items():
            key.encode("utf-8")
            _check_values(item)
    elif isinstance(value, list):
        for item in value:
            _check_values(item)


def _headers(records):
    """按全体记录中字段首次出现的次序取并集，空字段名同样保留。"""
    fields = {}
    for record in records:
        for name in record:
            fields.setdefault(name, None)
            if len(fields) > MAX_COLUMNS:
                raise ValueError("字段总数超过1000列限制")
    if not fields:
        raise ValueError("记录没有任何字段，无法建立CSV表头")
    return list(fields)


def load_records(input_path, records_key=None):
    """读取UTF-8（可带BOM）JSON，返回记录列表和原始字节SHA256。"""
    if records_key is not None and not isinstance(records_key, str):
        raise ValueError("记录字段名必须是字符串或None")
    payload = _read_source(input_path)
    try:
        data = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unique_pairs,
                          parse_int=Decimal, parse_float=Decimal, parse_constant=_reject_constant)
        _check_values(data)
    except (UnicodeError, ValueError, InvalidOperation, RecursionError, OverflowError):
        raise ValueError("输入必须是有效UTF-8严格JSON，不允许重复字段、非有限数值或无效字符") from None
    if records_key is not None:
        if not isinstance(data, dict) or records_key not in data or not isinstance(data[records_key], list):
            raise ValueError("指定记录字段必须是顶层对象中存在的数组；不解释点分隔路径")
        records = data[records_key]
    elif isinstance(data, dict):
        records = [data]
    elif isinstance(data, list):
        records = data
    else:
        raise ValueError("JSON顶层必须是对象或对象数组")
    if not records:
        raise ValueError("记录数组为空，无法转换")
    if len(records) > MAX_ROWS:
        raise ValueError("记录数量超过100000行限制")
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("记录数组的每一项都必须是对象")
    _headers(records)
    return records, hashlib.sha256(payload).hexdigest()


def _nested_json(value):
    """直接序列化Decimal数值，避免转成float或把嵌套数值变成字符串。"""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("嵌套JSON数值必须有限")
        return str(value)
    if isinstance(value, list):
        return "[" + ",".join(_nested_json(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + _nested_json(item) for key, item in value.items()) + "}"
    raise ValueError("记录含有不支持的JSON值类型")


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, Decimal):
        return str(value)
    return _nested_json(value)


def convert(input_path, output_dir, records_key=None):
    """先完整验证、在同父目录暂存，再发布新的输出目录。"""
    records, source_sha = load_records(input_path, records_key)
    headers = _headers(records)
    raw_output = _no_links(output_dir)
    output = raw_output.resolve()
    if output.exists():
        raise ValueError("输出目录必须不存在，已有空目录也不覆盖")
    stage = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        _no_links(output.parent)
        stage = Path(tempfile.mkdtemp(prefix="1995_转换暂存_", dir=output.parent))
        csv_path = stage / CSV_NAME
        with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream, dialect="excel", lineterminator="\r\n")
            writer.writerow(headers)
            for record in records:
                writer.writerow([_cell(record.get(name)) for name in headers])
        csv_sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        notes = {
            "format_version": 1, "rows": len(records), "columns": len(headers),
            "input_sha256": source_sha, "csv_sha256": csv_sha,
            "files": {"csv": CSV_NAME, "notes": NOTES_NAME},
            "records_key_used": records_key is not None,
            "rules": {
                "encoding": "UTF-8 BOM", "record_newline": "CRLF", "csv_quoting": "RFC4180 csv.writer",
                "column_order": "全表字段按首次出现的顺序取并集",
                "null_and_missing": "null和缺失字段均写为空单元格",
                "boolean": "小写true和false", "nested_objects_and_arrays": "紧凑JSON，嵌套数值保持精确Decimal语义",
                "text": "字符串和文本编号原样保留，不裁剪、清洗或添加公式转义前缀",
                "numbers": "Decimal精确数值，不做金额舍入；科学记法可能规范为E形式，不保证原数字词法逐字相同",
                "spreadsheet_import": "CSV没有Excel单元格类型；打开软件对前导零、公式和数值的解释取决于导入方式",
            },
        }
        (stage / NOTES_NAME).write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
        if hashlib.sha256(_read_source(input_path)).hexdigest() != source_sha:
            raise ValueError("输入文件已变化，未发布转换结果")
        _no_links(output)
        if output.exists():
            raise ValueError("输出目录已经存在，未覆盖任何内容")
        os.rename(stage, output)
        stage = None
        return {"rows": len(records), "columns": len(headers), "headers": headers,
                "input_sha256": source_sha, "csv_sha256": csv_sha, "directory": str(output)}
    except ValueError:
        raise
    except Exception:
        raise ValueError("转换或写入失败，未发布部分结果") from None
    finally:
        if stage is not None and stage.parent.resolve() == output.parent and stage.name.startswith("1995_转换暂存_"):
            shutil.rmtree(stage)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="以标准库将严格JSON转换为UTF-8 CSV")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--records-key", default=None)
    args = parser.parse_args(argv)
    try:
        result = convert(args.input, args.output, args.records_key)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except ValueError as exc:
        print("错误：" + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
