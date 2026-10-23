"""真实Tk按钮的长字段与失败恢复验收，不打开外部应用。"""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("desktop_test1995", HERE / "1995_桌面工具.py")
desktop = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = desktop
spec.loader.exec_module(desktop)


class DesktopAcceptance(unittest.TestCase):
    def test_long_field_is_saved_fully_through_real_button(self):
        with tempfile.TemporaryDirectory(prefix="1995_桌面验收_") as directory:
            root = Path(directory)
            source = root / "1995_长字段.json"
            text = "长字段,带引号\"\n" * 25000
            source.write_text(json.dumps([{"编号": "000001", "内容": text}], ensure_ascii=False), encoding="utf-8")
            original = hashlib.sha256(source.read_bytes()).hexdigest()
            result = desktop.self_check(source, root / "1995_结果")
            with (Path(result["directory"]) / "1995_转换结果.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows, [["编号", "内容"], ["000001", text]])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original)

    def test_invalid_input_does_not_publish_through_real_button(self):
        with tempfile.TemporaryDirectory(prefix="1995_桌面验收_") as directory:
            root = Path(directory)
            source = root / "1995_坏输入.json"
            source.write_text('{"a":1,"a":2}', encoding="utf-8")
            output = root / "1995_失败结果"
            with self.assertRaises(ValueError):
                desktop.self_check(source, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
