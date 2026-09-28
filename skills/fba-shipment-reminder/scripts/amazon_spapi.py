#!/usr/bin/env python3
"""Read-only Amazon SP-API client with redacted errors."""

from datetime import datetime, timezone
import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from credentials import read_credentials
from wechat_notify import NoRedirect


BASE_PATH = "/inbound/fba/2024-03-20/inboundPlans"
HOSTS = {"NA": "sellingpartnerapi-na.amazon.com",
         "EU": "sellingpartnerapi-eu.amazon.com",
         "FE": "sellingpartnerapi-fe.amazon.com"}
LABELS = {"NA": "北美（美国 / 加拿大 / 墨西哥 / 巴西）",
          "EU": "欧洲 / 英国 / 中东 / 印度",
          "FE": "远东（日本 / 澳大利亚 / 新加坡）"}


class ApiError(RuntimeError):
    def __init__(self, message, retryable=False, status=None, service_messages=()):
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        # Keep these in memory for known business-error classification, never log raw bodies.
        self.service_messages = service_messages


def validate_config(values):
    config = {key: values.get(key, "").strip()
              for key in ("client_id", "client_secret", "refresh_token", "region")}
    if config["region"] not in HOSTS:
        raise ValueError("请选择店铺所在区域。")
    for key, label in (("client_id", "Client ID"), ("client_secret", "Client Secret"),
                       ("refresh_token", "Refresh Token")):
        value = config[key]
        if not 10 <= len(value) <= 8192 or any(c.isspace() for c in value):
            raise ValueError("请填写完整的 %s，且不要包含空格或换行。" % label)
    if not config["client_id"].startswith("amzn1.application-oa2-client."):
        raise ValueError("Client ID 应来自 LWA credentials，不是 App ID。")
    return config


def load_config():
    env_names = {"client_id": "SP_API_CLIENT_ID", "client_secret": "SP_API_CLIENT_SECRET",
                 "refresh_token": "SP_API_REFRESH_TOKEN"}
    if any(name in os.environ for name in env_names.values()):
        values = {key: os.environ.get(name, "") for key, name in env_names.items()}
        values["region"] = os.environ.get("SP_API_REGION", "NA").strip().upper()
        return validate_config(values)
    return validate_config(read_credentials())


def request_json(request, phase):
    try:
        with build_opener(NoRedirect()).open(request, timeout=25) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise RuntimeError("亚马逊响应超过本次测试的大小限制。")
        result = json.loads(data.decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except HTTPError as error:
        # Only inspect a known OAuth error code; never echo response bodies.
        oauth_error = None
        service_messages = ()
        if phase == "LWA":
            try:
                body = json.loads(error.read(32768))
                oauth_error = body.get("error") if isinstance(body, dict) else None
            except (ValueError, OSError):
                pass
        else:
            try:
                body = json.loads(error.read(32768))
                service_messages = tuple(item.get("message", "") for item in body.get("errors", [])
                                         if isinstance(item, dict) and isinstance(item.get("message"), str))
            except (ValueError, AttributeError, TypeError, OSError):
                pass
        if oauth_error == "invalid_client":
            message = "Client ID 或 Client Secret 不匹配，请核对同一应用的 LWA credentials。"
        elif oauth_error == "invalid_grant":
            message = "Refresh Token 无效、已撤销或不属于此应用，请核对授权。"
        elif error.code in (401, 403):
            message = "请求未获授权，请核对区域、店铺授权和 Amazon Fulfillment 权限。"
        elif error.code == 429:
            message = "接口限流，请稍后再测试。"
        else:
            message = "请求失败，请检查亚马逊接口或应用配置。"
        raise ApiError("%s HTTP %d：%s" % (phase, error.code, message),
                       error.code == 429 or error.code >= 500, error.code, service_messages) from None
    except (URLError, TimeoutError, OSError):
        raise ApiError("%s 网络请求失败，请检查连接后重试。" % phase, True) from None
    except (ValueError, UnicodeError):
        raise RuntimeError("%s 返回了无法识别的数据。" % phase) from None


class Client:
    def __init__(self, config):
        self.config = config
        self.token = None
        self.last_get = 0.0

    def authenticate(self):
        payload = {key: self.config[key]
                   for key in ("client_id", "client_secret", "refresh_token")}
        payload["grant_type"] = "refresh_token"
        result = request_json(Request("https://api.amazon.com/auth/o2/token",
            data=urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST"), "LWA")
        token = result.get("access_token")
        if not isinstance(token, str) or not token or "\r" in token or "\n" in token:
            raise RuntimeError("亚马逊未返回有效的访问令牌。")
        self.token = token

    def get(self, path, query=None):
        if not self.token:
            raise RuntimeError("请先完成 LWA 授权验证。")
        if path != BASE_PATH and not re.fullmatch(
                re.escape(BASE_PATH) + r"/[A-Za-z0-9-]{38}(?:/shipments/[A-Za-z0-9-]{38})?", path):
            raise ValueError("本程序仅允许读取入库计划和货件。")
        time.sleep(max(0, 0.6 - (time.monotonic() - self.last_get)))
        self.last_get = time.monotonic()
        url = "https://" + HOSTS[self.config["region"]] + path
        if query:
            url += "?" + urlencode(query)
        return request_json(Request(url, headers={
            "x-amz-access-token": self.token,
            "x-amz-date": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "User-Agent": "FBAShipmentReminder/0.2 (Language=Python/3)",
            "Accept": "application/json"}, method="GET"), "SP-API")


def id_path(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]{38}", value):
        raise RuntimeError("亚马逊返回的计划或货件标识格式异常。")
    return value
