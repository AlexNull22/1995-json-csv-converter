"""1995 独立业务验收：真实 JSON 文件、CSV 解析和文件系统边界。

运行：python -B 1995_验收测试.py
全部输入均为自制数据，临时目录自动清理；不修改核心或正式示例。
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch


BASE = Path(__file__).resolve().parent
CSV_NAME = "1995_转换结果.csv"
NOTE_NAME = "1995_转换说明.json"


def load_engine():
    name = "1995_验收专用转换核心"
    spec = importlib.util.spec_from_file_location(name, BASE / "1995_转换核心.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 1995 转换核心")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ConversionAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = load_engine()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="1995_业务验收_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "1995_输入.json"
        self.output = self.root / "1995_转换输出"

    def write_raw(self, text: str, *, bom: bool = False) -> bytes:
        data = text.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        self.source.write_bytes(data)
        return data

    def write_json(self, data) -> bytes:
        return self.write_raw(json.dumps(data, ensure_ascii=False, separators=(",", ":")))

    def read_csv(self, output: Path | None = None):
        raw = ((output or self.output) / CSV_NAME).read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "CSV 须带 UTF-8 BOM")
        # newline='' prevents Python from normalizing quoted embedded CR/LF.
        stream = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8-sig", newline="")
        with stream:
            rows = list(csv.reader(stream, strict=True))
        return raw, rows

    def convert(self, *, records_key=None, output=None):
        return self.engine.convert(self.source, output or self.output, records_key=records_key)

    def assert_rejected(self, *, records_key=None):
        original = self.source.read_bytes()
        siblings = set(self.root.iterdir())
        with self.assertRaises(ValueError):
            self.convert(records_key=records_key)
        self.assertFalse(self.output.exists(), "拒绝时不得发布输出目录")
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(set(self.root.iterdir()), siblings, "拒绝时不应留下暂存目录")

    def test_01_single_object_bom_crlf_and_independent_hashes(self):
        source = self.write_raw('{"名称":"青瓷杯","数量":2}', bom=True)
        report = self.convert()
        raw, rows = self.read_csv()
        self.assertEqual(rows, [["名称", "数量"], ["青瓷杯", "2"]])
        self.assertEqual(raw[3:], "名称,数量\r\n青瓷杯,2\r\n".encode("utf-8"))
        self.assertEqual(report["rows"], 1)
        self.assertEqual(report["columns"], 2)
        self.assertEqual(report["headers"], ["名称", "数量"])
        self.assertEqual(Path(report["directory"]).resolve(), self.output.resolve())
        self.assertEqual(report["input_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(report["csv_sha256"], hashlib.sha256(raw).hexdigest())
        note = json.loads((self.output / NOTE_NAME).read_text(encoding="utf-8-sig"))
        self.assertIsInstance(note, dict)

    def test_02_union_headers_include_late_fields_in_first_seen_order(self):
        self.write_json([{"编号": "A", "价格": None}, {}, {"库存": 0, "编号": "B"}, {"备注": "后出现", "价格": "9.90"}])
        result = self.convert()
        _, rows = self.read_csv()
        self.assertEqual(result["headers"], ["编号", "价格", "库存", "备注"])
        self.assertEqual(rows, [["编号", "价格", "库存", "备注"], ["A", "", "", ""], ["", "", "", ""], ["B", "", "0", ""], ["", "9.90", "", "后出现"]])
        self.assertEqual(result["rows"], 4)

    def test_03_rfc4180_preserves_commas_quotes_and_embedded_newlines(self):
        text = '一号, "特别版"\r\n第二行\n第三行\r结束'
        self.write_json([{"说明,字段": text, "尾列": "结尾"}])
        self.convert()
        raw, rows = self.read_csv()
        self.assertEqual(rows, [["说明,字段", "尾列"], [text, "结尾"]])
        self.assertIn(b'""', raw)
        self.assertTrue(raw.endswith(b"\r\n"))

    def test_04_strings_keep_leading_zeros_whitespace_unicode_and_formula_text(self):
        values = ["00001234", "  未修剪  ", "=SUM(A1:A2)", "+001", "-001", "@name", "😀 café e\u0301", "true", "null", "1.00"]
        self.write_json([{"原文": value} for value in values])
        self.convert()
        _, rows = self.read_csv()
        self.assertEqual([row[0] for row in rows[1:]], values)

    def test_05_boolean_null_missing_zero_and_empty_text_have_defined_cells(self):
        self.write_json([{"真": True, "假": False, "空": None, "零": 0, "文本": ""}, {"真": False}])
        self.convert()
        _, rows = self.read_csv()
        self.assertEqual(rows, [["真", "假", "空", "零", "文本"], ["true", "false", "", "0", ""], ["false", "", "", "", ""]])

    def test_06_nested_objects_arrays_are_single_compact_exact_json_cells(self):
        self.write_raw('[{"属性":{"折扣":0.123456789012345678901234567890,"有效":true,"空":null,"标签":"a b"},"列表":[90071992547409931234567890,1.2300,{"中文":"值,含逗号"}]}]')
        self.convert()
        _, rows = self.read_csv()
        self.assertEqual(len(rows[1]), 2)
        object_cell = json.loads(rows[1][0], parse_float=Decimal, parse_int=Decimal)
        array_cell = json.loads(rows[1][1], parse_float=Decimal, parse_int=Decimal)
        self.assertEqual(object_cell, {"折扣": Decimal("0.123456789012345678901234567890"), "有效": True, "空": None, "标签": "a b"})
        self.assertEqual(array_cell, [Decimal("90071992547409931234567890"), Decimal("1.2300"), {"中文": "值,含逗号"}])
        self.assertNotIn(": ", rows[1][0])
        self.assertNotIn(", ", rows[1][1])
        self.assertIn("1.2300", rows[1][1])

    def test_07_large_integers_tiny_decimals_and_exponents_never_round(self):
        expected = ["1234567890123456789012345678901234567890", "0.000000000000000000000000000123456789", "1.234567890123456789e+80", "-0.0000", "1e-1000"]
        self.write_raw("[" + ",".join('{"数值":' + value + "}" for value in expected) + "]")
        self.convert()
        _, rows = self.read_csv()
        self.assertEqual([Decimal(row[0]) for row in rows[1:]], [Decimal(value) for value in expected])
        self.assertEqual(rows[1][0], expected[0])

    def test_08_records_key_is_literal_and_can_be_empty(self):
        self.write_json({"元信息": "不应导出", "a.b": [{"编号": "001"}], "a": {"b": [{"错误": "不应解析路径"}]}, "": [{"空键": "允许"}]})
        self.convert(records_key="a.b")
        _, rows = self.read_csv()
        self.assertEqual(rows, [["编号"], ["001"]])
        other = self.root / "1995_空键输出"
        self.convert(records_key="", output=other)
        _, rows = self.read_csv(other)
        self.assertEqual(rows, [["空键"], ["允许"]])

    def test_09_loader_returns_precise_records_and_source_byte_hash(self):
        raw = self.write_raw('{"记录":[{"数":1.234567890123456789,"嵌套":[123456789012345678901]}]}', bom=True)
        records, digest = self.engine.load_records(self.source, records_key="记录")
        self.assertEqual(records[0]["数"], Decimal("1.234567890123456789"))
        self.assertEqual(records[0]["嵌套"][0], Decimal("123456789012345678901"))
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.source.read_bytes(), raw)
        self.assertFalse(self.output.exists())

    def test_10_duplicate_json_keys_rejected_at_every_nesting_level(self):
        for value in ['{"id":1,"id":2}', '[{"a":{"x":1,"x":2}}]', '{"records":[{"a":1}],"records":[{"b":2}]}']:
            with self.subTest(value=value):
                self.write_raw(value)
                self.assert_rejected()

    def test_11_nonfinite_json_numbers_rejected_including_nested_values(self):
        for value in ['{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":[{"n":NaN}]}']:
            with self.subTest(value=value):
                self.write_raw(value)
                self.assert_rejected()

    def test_12_bad_encoding_and_malformed_or_trailing_json_rejected(self):
        for data in [b'{"a":"\xff"}', b'{"a":"\\ud800"}', b'{"a":1,}', b'{"a":1} {"b":2}', b'[{"a":1}', b'\xef\xbb\xbf\xef\xbb\xbf{"a":1}']:
            with self.subTest(data=data):
                self.source.write_bytes(data)
                self.assert_rejected()

    def test_13_scalars_and_non_object_array_rows_are_not_silently_dropped(self):
        for data in [None, True, 1, "text", [1], [[{"a": 1}]], [{"a": 1}, None], [{"a": 1}, "bad"]]:
            with self.subTest(data=data):
                self.write_json(data)
                self.assert_rejected()

    def test_14_empty_record_sets_and_no_field_datasets_rejected(self):
        for data, key in [([], None), ({}, None), ([{}, {}], None), ({"items": []}, "items"), ({"items": [{}]}, "items")]:
            with self.subTest(data=data):
                self.write_json(data)
                self.assert_rejected(records_key=key)

    def test_15_records_key_requires_top_object_exact_key_and_object_list(self):
        for data, key in [([{"a": 1}], "a"), ({"items": [{"a": 1}]}, "ITEMS"), ({"items": {"a": 1}}, "items"), ({"items": None}, "items"), ({"items": [1]}, "items"), ({"items": [{"a": 1}]}, 1), ({"items": [{"a": 1}]}, False)]:
            with self.subTest(data=data, key=key):
                self.write_json(data)
                self.assert_rejected(records_key=key)

    def test_16_existing_empty_or_populated_output_is_never_overwritten(self):
        self.write_json({"编号": "保留"})
        self.output.mkdir()
        with self.assertRaises(ValueError):
            self.convert()
        self.assertEqual(list(self.output.iterdir()), [])
        marker = self.output / "1995_已有文件.txt"
        marker.write_bytes(b"keep-existing-bytes")
        with self.assertRaises(ValueError):
            self.convert()
        self.assertEqual(marker.read_bytes(), b"keep-existing-bytes")
        self.assertEqual(list(self.output.iterdir()), [marker])

    def test_17_success_and_repeat_export_preserve_original_source_bytes(self):
        raw = self.write_raw(' \r\n[{"商品":"0007","金额":5.0000},{"商品":"0010"}]\r\n', bom=True)
        first = self.convert()
        second_output = self.root / "1995_第二次输出"
        second = self.convert(output=second_output)
        self.assertEqual(self.source.read_bytes(), raw)
        self.assertEqual(first["input_sha256"], second["input_sha256"])
        self.assertEqual((self.output / CSV_NAME).read_bytes(), (second_output / CSV_NAME).read_bytes())
        self.assertEqual(first["csv_sha256"], second["csv_sha256"])

    def test_18_mid_write_disk_error_leaves_no_published_or_staging_output(self):
        self.write_json([{"编号": "A"}, {"编号": "B"}])
        raw = self.source.read_bytes()
        before = set(self.root.iterdir())
        original_writer = csv.writer

        class FailingWriter:
            def __init__(self, *args, **kwargs):
                self.writer = original_writer(*args, **kwargs)
                self.calls = 0

            def writerow(self, row):
                self.calls += 1
                if self.calls >= 2:
                    raise OSError("1995 自制磁盘写入失败")
                return self.writer.writerow(row)

            def writerows(self, rows):
                for row in rows:
                    self.writerow(row)

        with patch.object(self.engine.csv, "writer", FailingWriter):
            with self.assertRaises((ValueError, OSError)):
                self.convert()
        self.assertFalse(self.output.exists())
        self.assertEqual(set(self.root.iterdir()), before)
        self.assertEqual(self.source.read_bytes(), raw)

        source = self.source
        changed = b'{"external_change":"1995 changed while conversion is writing"}'

        class SourceChangingWriter:
            def __init__(self, *args, **kwargs):
                self.writer = original_writer(*args, **kwargs)

            def writerow(self, row):
                result = self.writer.writerow(row)
                source.write_bytes(changed)
                return result

            def writerows(self, rows):
                for row in rows:
                    self.writerow(row)

        # Simulate an independent editor changing the source after validation.
        with patch.object(self.engine.csv, "writer", SourceChangingWriter):
            with self.assertRaises(ValueError):
                self.convert()
        self.assertFalse(self.output.exists())
        self.assertEqual(set(self.root.iterdir()), before)
        self.assertEqual(self.source.read_bytes(), changed)

    def make_link(self, link: Path, target: Path, *, directory: bool = False):
        try:
            os.symlink(target, link, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest("当前 Windows 用户不具备创建符号链接的权限：" + type(error).__name__)

    def test_19_input_symlink_and_linked_ancestor_are_rejected(self):
        self.write_json({"编号": "A"})
        link = self.root / "1995_输入链接.json"
        self.make_link(link, self.source)
        with self.assertRaises(ValueError):
            self.engine.convert(link, self.output)
        parent = self.root / "1995_原件目录"
        parent.mkdir()
        source = parent / "1995_原件.json"
        source.write_bytes(self.source.read_bytes())
        alias = self.root / "1995_目录链接"
        self.make_link(alias, parent, directory=True)
        with self.assertRaises(ValueError):
            self.engine.load_records(alias / source.name)
        self.assertFalse(self.output.exists())

    def test_20_directory_links_reject_input_and_output_ancestors(self):
        self.write_json({"编号": "A"})
        target = self.root / "1995_真实目标"
        target.mkdir()
        linked = self.root / "1995_输出链接"
        try:
            os.symlink(target, linked, target_is_directory=True)
        except (OSError, NotImplementedError):
            if os.name != "nt":
                self.skipTest("当前环境不能创建目录符号链接")
            # Windows junctions do not require the symlink privilege and must
            # be refused independently of normal output-exists checks.
            result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(linked), str(target)], capture_output=True)
            if result.returncode or not linked.is_junction():
                self.skipTest("当前 Windows 用户不能创建目录链接或连接点")
        with self.assertRaises(ValueError):
            self.convert(output=linked)
        with self.assertRaises(ValueError):
            self.convert(output=linked / "1995_新输出")
        self.assertEqual(list(target.iterdir()), [])
        copied_source = target / "1995_经过链接的原件.json"
        copied_source.write_bytes(self.source.read_bytes())
        with self.assertRaises(ValueError):
            self.engine.load_records(linked / copied_source.name)
        self.assertEqual(copied_source.read_bytes(), self.source.read_bytes())

    def test_21_input_byte_limit_accepts_exact_boundary_and_rejects_next_byte(self):
        raw = self.write_json({"说明": "青瓷杯"})
        with patch.object(self.engine, "MAX_INPUT_BYTES", len(raw)):
            records, _ = self.engine.load_records(self.source)
            self.assertEqual(records, [{"说明": "青瓷杯"}])
        with patch.object(self.engine, "MAX_INPUT_BYTES", len(raw) - 1):
            self.assert_rejected()

    def test_22_row_limit_counts_all_rows_including_empty_objects(self):
        with patch.object(self.engine, "MAX_ROWS", 3):
            self.write_json([{"编号": 1}, {}, {"编号": 3}])
            result = self.convert()
            self.assertEqual(result["rows"], 3)
            other = self.root / "1995_超行输出"
            self.write_json([{"编号": 1}, {}, {"编号": 3}, {}])
            with self.assertRaises(ValueError):
                self.convert(output=other)
            self.assertFalse(other.exists())

    def test_23_column_limit_applies_to_union_not_first_record_only(self):
        with patch.object(self.engine, "MAX_COLUMNS", 3):
            self.write_json([{"甲": 1}, {"乙": 2}, {"丙": 3}])
            result = self.convert()
            self.assertEqual(result["headers"], ["甲", "乙", "丙"])
            other = self.root / "1995_超列输出"
            self.write_json([{"甲": 1}, {"乙": 2}, {"丙": 3}, {"丁": 4}])
            with self.assertRaises(ValueError):
                self.convert(output=other)
            self.assertFalse(other.exists())

    def test_24_chinese_nested_paths_and_empty_field_names_are_preserved(self):
        folder = self.root / "1995_中文路径与空格 试用"
        folder.mkdir()
        self.source = folder / "1995_商品😀.json"
        self.output = self.root / "1995_中文输出目录" / "1995_结果"
        self.write_json([{"": "空字段名也有数据", "名称😀": "杭州 · 桌面灯"}])
        result = self.convert()
        _, rows = self.read_csv()
        self.assertEqual(rows, [["", "名称😀"], ["空字段名也有数据", "杭州 · 桌面灯"]])
        self.assertEqual(result["headers"], ["", "名称😀"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
