#!/usr/bin/env python3
"""Configure FBA reminders through a short-lived local form, without chat secrets."""
import argparse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import shlex
import sys
import threading
import time
from urllib.parse import parse_qs

from amazon_spapi import LABELS, load_config, validate_config
from credentials import save_credentials, storage_available
from local_state import ROOT, process_lock, utf8_console
from wechat_notify import load_key, send, validate_key


def make_setup_server(store, port=0):
    token = secrets.token_urlsafe(32)
    path = "/setup/" + token
    store_lock = threading.Lock()
    fields = "".join('<label for="%s">%s</label><input id="%s" name="%s" '
        'type="password" autocomplete="off" spellcheck="false" required maxlength="8192">'
        % (key, label, key, key) for key, label in (
            ("client_id", "LWA Client ID"), ("client_secret", "LWA Client Secret"),
            ("refresh_token", "Refresh Token"), ("sendkey", "Server酱 SendKey")))
    regions = "".join('<option value="%s">%s</option>' % (key, label) for key, label in LABELS.items())

    class Handler(BaseHTTPRequestHandler):
        timeout = 10

        def log_message(self, *_):
            pass

        def reply(self, status, body):
            data = body.encode("utf-8")
            self.send_response(status)
            for key, value in {"Content-Type": "text/html; charset=utf-8",
                "Content-Length": str(len(data)), "Cache-Control": "no-store", "Connection": "close",
                "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY", "Content-Security-Policy":
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"}.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def valid_target(self):
            return self.path == path and self.headers.get("Host") == server.expected_host

        def do_GET(self):
            if not self.valid_target():
                self.reply(404, "Not found")
                return
            self.reply(200, '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>FBA 微信提醒配置</title>
<style>body{font:16px/1.7 system-ui;margin:0;background:#f4f6f8;color:#192c38;padding:24px}
main{max-width:620px;margin:2vh auto;background:white;padding:30px;border-radius:16px}
h1{margin:0 0 12px;font-size:26px}p{color:#536571}label{display:block;font-weight:600;margin-top:14px}
input,select,button{font:inherit;width:100%;padding:10px;box-sizing:border-box;border-radius:8px;border:1px solid #bbc8d0}
button{background:#087b72;color:white;border:0;margin-top:24px;cursor:pointer}</style>
<main><h1>连接亚马逊与微信</h1><p>先在 Server酱绑定微信，再填写下方信息。
凭证保存在当前电脑的系统保护存储中。保存配置不会发送消息或修改货件。</p>
<form method="post"><input type="hidden" name="csrf" value="__TOKEN__">
<label for="region">亚马逊区域</label><select id="region" name="region">__REGIONS__</select>
__FIELDS__<button type="submit">保存配置</button></form>
<p>Client ID 请从 LWA credentials 获取；Application ID 不能代替 Client ID。</p></main></html>'''
                .replace("__TOKEN__", token).replace("__REGIONS__", regions).replace("__FIELDS__", fields))

        def do_POST(self):
            origin = "http://" + server.expected_host
            if not self.valid_target() or self.headers.get("Origin") not in (None, origin):
                self.reply(403, "请求来源不符。")
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
                self.reply(415, "请使用本机配置页面提交。")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 40000:
                    raise ValueError("输入长度不正确。")
                values = parse_qs(self.rfile.read(length).decode("utf-8"), max_num_fields=8)
                if any(len(value) != 1 for value in values.values()):
                    raise ValueError("配置字段重复。")
                if not secrets.compare_digest(values.get("csrf", [""])[0], token):
                    self.reply(403, "配置页面已失效，请重新打开。")
                    return
                config = validate_config({key: value[0] for key, value in values.items()})
                config["sendkey"] = validate_key(values.get("sendkey", [""])[0])
                with store_lock:
                    if server.configured:
                        self.reply(409, "配置已经保存，请关闭页面。")
                        return
                    store(config)
                    server.configured = True
            except (ValueError, RuntimeError, OSError, UnicodeError):
                self.reply(400, "保存失败，请核对四项配置、亚马逊区域，以及系统凭证存储是否可用。")
                return
            self.reply(200, '<!doctype html><meta charset="utf-8"><h1>配置已保存</h1>'
                       '<p>请回到 Codex，继续检查连接并测试微信推送。</p>')

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.expected_host = "127.0.0.1:%d" % server.server_port
    server.page_url = "http://" + server.expected_host + path
    server.configured = False
    server.timeout = 1
    return server


def setup():
    storage_available()
    with process_lock(ROOT / "setup.lock"), make_setup_server(save_credentials) as server:
        print("请在本机浏览器填写凭证：" + server.page_url, flush=True)
        print("不要将凭证粘贴到 Codex 对话。本页面一小时后失效。", flush=True)
        deadline = time.monotonic() + 3600
        while not server.configured and time.monotonic() < deadline:
            server.handle_request()
        if not server.configured:
            raise RuntimeError("配置页面已超时关闭，请重新运行 setup。")
    print("配置已保存，尚未测试 API 或微信送达。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup", "status", "test-wechat", "schedule-info"))
    args = parser.parse_args()
    try:
        if args.command == "setup":
            setup()
        elif args.command == "status":
            config = load_config()
            load_key()
            print("凭证格式有效，区域：%s；尚未验证在线授权。" % LABELS[config["region"]])
            print("本机数据目录：" + str(ROOT))
        elif args.command == "test-wechat":
            send("FBA 微信通道测试", "这是一条由你手动触发的通道测试。收到后请回到 Codex 确认。")
        else:
            command = [sys.executable, str(Path(__file__).resolve().with_name("shipment_reminder.py")), "scheduled"]
            if sys.platform == "win32":
                quoted = "& " + " ".join("'" + part.replace("'", "''") + "'" for part in command)
            else:
                quoted = shlex.join(command)
            beijing = timezone(timedelta(hours=8))
            next_run = datetime.now(beijing).replace(hour=9, minute=0, second=0, microsecond=0)
            if next_run <= datetime.now(beijing):
                next_run += timedelta(days=1)
            print(json.dumps({"command": quoted, "timezone": "Asia/Shanghai", "daily_time": "09:00",
                "next_beijing_run": next_run.isoformat(), "data_directory": str(ROOT)}, ensure_ascii=False, indent=2))
        return 0
    except (RuntimeError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    utf8_console()
    sys.exit(main())
