#!/usr/bin/env python3
"""FBA 货件提醒的 Server酱推送入口；只使用 Python 标准库。"""

from datetime import datetime, timezone
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


from local_state import ROOT, private_write
from credentials import read_credentials
RECORD_FILE = ROOT / ".runtime" / "wechat_last_send.json"


def validate_key(value):
    value = value.strip()
    if not re.fullmatch(r"SCT[0-9A-Za-z]{10,}|sctp[0-9]+t[0-9A-Za-z]{10,}", value):
        raise ValueError("请粘贴完整的 Server酱 SendKey，不要粘贴网址。")
    return value


def load_key():
    if "SERVERCHAN_SENDKEY" in os.environ:
        key = os.environ["SERVERCHAN_SENDKEY"]
    else:
        key = read_credentials().get("sendkey", "")
    if not key:
        raise ValueError("尚未配置 SendKey，请运行 configure.py setup。")
    return validate_key(key)


def endpoint(key):
    key = validate_key(key)
    if key.startswith("sctp"):
        uid = re.match(r"sctp([0-9]+)t", key).group(1)
        return "https://%s.push.ft07.com/send/%s.send" % (uid, key)
    return "https://sctapi.ftqq.com/%s.send" % key


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send(title, body):
    if not title.strip() or "\n" in title or "\r" in title:
        raise ValueError("提醒标题必须为非空单行文本。")
    request = Request(
        endpoint(load_key()),
        data=urlencode({"title": title, "desp": body}).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
        method="POST",
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            result = json.loads(response.read(65536).decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError("推送接口返回 HTTP %s；请检查通道与额度。" % error.code) from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("推送网络请求失败，送达状态未知；未自动重试，请先查看微信。") from None
    except (ValueError, UnicodeError):
        raise RuntimeError("推送服务返回无法识别的结果，送达状态未知。") from None
    if not isinstance(result, dict) or type(result.get("code")) is not int or result["code"] != 0:
        raise RuntimeError("推送服务未确认接受消息，请在 Server酱控制台检查通道与额度。")
    record = {"provider": "serverchan", "accepted_at": datetime.now(timezone.utc).isoformat(),
              "provider_accepted": True, "phone_receipt_confirmed": False}
    private_write(RECORD_FILE, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print("Server酱已接受消息。请查看手机微信确认收到；接口成功不等于手机已送达。")
