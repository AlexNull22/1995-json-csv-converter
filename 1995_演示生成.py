"""自造数据、真实桌面按钮与逐单元格转换验收。"""
import argparse
import csv
from decimal import Decimal
import hashlib
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
import time
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent


def load_desktop():
    spec = importlib.util.spec_from_file_location("desktop1995", HERE / "1995_桌面工具.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def report_page(summary, headers, rows, target):
    esc = lambda x: html.escape(str(x))
    head = ''.join('<th>' + esc(x) + '</th>' for x in headers)
    body = ''.join('<tr>' + ''.join('<td>' + esc(x) + '</td>' for x in row) + '</tr>' for row in rows[:30])
    target.write_text(f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>1995 JSON转CSV · 独立演示验收</title><style>
*{{box-sizing:border-box}}body{{margin:0;color:#293944;background:#f5f7f8;font:15px/1.6 "Segoe UI","Microsoft Yahei",sans-serif}}header{{padding:35px 4vw;background:#e4edf2}}small{{letter-spacing:3px;color:#4c7186}}h1{{font-size:36px;margin:8px 0}}p{{color:#637a87}}main{{margin:24px 3vw}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}}.card,.panel{{background:white;border:1px solid #d6e1e6;border-radius:12px;padding:22px}}b{{font-size:30px;display:block}}.panel{{margin-top:22px}}.scroll{{overflow:auto;max-height:460px}}table{{border-collapse:collapse;font-size:12px;white-space:nowrap;width:100%}}th,td{{padding:10px 14px;border-bottom:1px solid #e4edf2;text-align:left;max-width:360px;overflow:hidden;text-overflow:ellipsis}}th{{position:sticky;top:0;background:#315971;color:white}}tr:nth-child(even){{background:#f2f7fa}}td:nth-child(5){{white-space:pre-line}}code{{font-size:11px;word-break:break-all}}h2{{font-size:21px;margin:0 0 15px}}a{{color:#315971}}
</style><header><small>1995 / 结构化数据转换工具</small><h1>把结构化数据，变成清楚的列。</h1><p>JSON → CSV · 真实桌面按钮执行 · 结果逐单元格核对 · 自造数据独立演示</p></header><main><div class="cards"><div class="card">已转换记录<b>{summary['rows']:,}</b></div><div class="card">合并字段列<b>{summary['columns']}</b></div><div class="card">单元格核对<b>全部一致</b></div><div class="card">原始JSON<b>保持不变</b></div></div><section class="panel"><h2>读取实际CSV文件的前30行</h2><div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div><p>嵌套对象与数组保留为紧凑JSON单元格。缺失和null为空白；字符串不清洗、不调价、不做数据库导入。此页为结果验收预览，桌面工具另含前15行预览。</p><a href="1995_转换结果.csv">下载本次实际CSV</a></section><section class="panel"><h2>来源与输出核验</h2><p>输入SHA-256：<code>{summary['input_sha256']}</code><br>CSV SHA-256：<code>{summary['csv_sha256']}</code></p><p>UTF-8 BOM / CRLF / RFC 4180 引号规则。数值精确写出；CSV不保存表格类型或样式，应用程序的自动类型解释未在本作品中验证。</p></section></main></html>''', encoding="utf-8")


def generate(output):
    desktop = load_desktop()
    output = output.absolute()
    desktop.core._no_links(output)
    if output.exists():
        raise ValueError("演示输出目录必须尚不存在")
    started = time.perf_counter()
    output.mkdir(parents=True)
    source = output / "1995_自造输入.json"
    records = []
    for i in range(1, 1001):
        record = {"编号": f"{i:06d}", "商品": f"自造商品 {i:04d}", "售价": 10 + i / 100,
                  "可用": i % 4 != 0, "备注": '含逗号,与"引号"\n第二行' if i % 20 == 0 else "正常",
                  "规格": {"颜色": "蓝色", "包装数": 6}, "标签": ["自造", f"组{i % 5}"], "可选值": None}
        if i >= 501:
            record["后出现字段"] = "仅第二批记录含有"
        records.append(record)
    # 构造源JSON后再显式植入精确小数/大整数，避免演示生成器先损失精度。
    text = json.dumps(records, ensure_ascii=False, indent=2)
    text = text.replace('"售价": 10.01,', '"售价": 12345678901234567890.123456789,', 1)
    source.write_text(text, encoding="utf-8")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = desktop.self_check(source, output / "1995_转换输出")
    csv_path = Path(result["directory"]) / "1995_转换结果.csv"
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        content = list(csv.reader(handle))
    headers, rows = content[0], content[1:]
    expected_headers = ["编号", "商品", "售价", "可用", "备注", "规格", "标签", "可选值", "后出现字段"]
    assert headers == expected_headers and len(rows) == 1000 and result["columns"] == 9
    for i, row in enumerate(rows, 1):
        assert len(row) == 9
        assert row[0] == f"{i:06d}" and row[1] == f"自造商品 {i:04d}"
        expected_price = Decimal("12345678901234567890.123456789") if i == 1 else Decimal(str(records[i-1]["售价"]))
        assert Decimal(row[2]) == expected_price
        assert row[3] == ("true" if i % 4 != 0 else "false")
        assert row[4] == records[i-1]["备注"]
        assert json.loads(row[5]) == records[i-1]["规格"] and json.loads(row[6]) == records[i-1]["标签"]
        assert row[7] == "" and row[8] == ("仅第二批记录含有" if i >= 501 else "")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == result["csv_sha256"]
    assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")
    try:
        desktop.core.convert(source, Path(result["directory"]))
    except ValueError:
        pass
    else:
        raise AssertionError("已有目录必须拒绝覆盖")
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == result["csv_sha256"]
    report_page(result, headers, rows, output / "1995_预览报告.html")
    metrics = {"independent_demo": True, "rows": 1000, "columns": 9, "cells_verified": 9000,
               "desktop_button_passed": True, "desktop_preview_rows": 15,
               "source_unchanged": True, "reject_overwrite_passed": True,
               "exact_decimal_preserved": True, "nested_values_preserved": True,
               "csv_sha256": result["csv_sha256"], "input_sha256": before,
               "elapsed_seconds": round(time.perf_counter() - started, 3)}
    (output / "1995_演示核验.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics


def serve(output, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            name = unquote(urlsplit(self.path).path).lstrip("/")
            files = {"1995_预览报告.html": (output / "1995_预览报告.html", "text/html; charset=utf-8"),
                     "1995_转换结果.csv": (output / "1995_转换输出" / "1995_转换结果.csv", "text/csv; charset=utf-8")}
            if name not in files:
                self.send_error(404)
                return
            file, kind = files[name]
            try:
                blob = file.read_bytes()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(blob)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"1995本机预览已启动，端口{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="1995独立演示生成与预览")
    parser.add_argument("--output", type=Path, default=HERE / "1995_演示数据")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8795)
    args = parser.parse_args()
    if args.serve:
        serve(args.output, args.port)
    else:
        print(json.dumps(generate(args.output), ensure_ascii=False, indent=2))
