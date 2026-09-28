#!/usr/bin/env python3
"""Read all SP-API inbound pages and send the daily delivery-window reminder."""

import argparse
import calendar
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from local_state import process_lock, utf8_console

from amazon_spapi import ApiError, BASE_PATH, Client, id_path, load_config
from wechat_notify import ROOT, private_write, send


BJ = timezone(timedelta(hours=8), "Asia/Shanghai")
RUNTIME = ROOT / ".runtime"
SNAPSHOT = RUNTIME / "shipments_latest.json"
REPORT = RUNTIME / "reminder_latest.md"
POLICY = ROOT / "settings.json"
DEFAULT_POLICY = Path(__file__).resolve().parent.parent / "assets/reminder_config.json"


def load_policy():
    path = POLICY if POLICY.exists() else DEFAULT_POLICY
    policy = json.loads(path.read_text(encoding="utf-8"))
    if type(policy.get("lookback_months")) is not int or not 1 <= policy["lookback_months"] <= 24:
        raise ValueError("lookback_months 必须是 1 至 24 的整数。")
    if type(policy.get("include_expired")) is not bool:
        raise ValueError("include_expired 必须为 true 或 false。")
    return policy
# Arrived, completed or cancelled shipments no longer need delivery-window edits.
FINISHED = {"ABANDONED", "CANCELLED", "CLOSED", "DELETED", "DELIVERED",
            "CHECKED_IN", "RECEIVING"}


def utcnow():
    return datetime.now(timezone.utc)


def parse_time(value):
    if not isinstance(value, str) or not value:
        raise ValueError("时间缺失")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("时间缺少时区")
    return result.astimezone(timezone.utc)


def format_time(value):
    if not value:
        return "接口未提供"
    try:
        return parse_time(value).astimezone(BJ).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return "接口时间格式异常"


def retry_read(function, *args):
    for attempt in range(3):
        try:
            return function(*args)
        except ApiError as error:
            if not error.retryable or attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))


def lookback_start(now, months):
    if type(months) is not int or not 1 <= months <= 24:
        raise RuntimeError("检查月份范围必须是 1 至 24 的整数。")
    local = now.astimezone(BJ)
    year, month_index = divmod(local.year * 12 + local.month - 1 - months, 12)
    month = month_index + 1
    day = min(local.day, calendar.monthrange(year, month)[1])
    return local.replace(year=year, month=month, day=day, hour=0, minute=0,
                         second=0, microsecond=0).astimezone(timezone.utc)


def scan(client=None, plan_statuses=("ACTIVE", "SHIPPED")):
    client = client or Client(load_config())
    retry_read(client.authenticate)
    started = utcnow()
    months = load_policy()["lookback_months"]
    cutoff = lookback_start(started, months)
    plans = {}
    pages = 0
    boundary_statuses = []
    for status in plan_statuses:
        tokens, cursor = set(), None
        previous_created = None
        while True:
            query = {"pageSize": 30, "status": status,
                     "sortBy": "CREATION_TIME", "sortOrder": "DESC"}
            if cursor:
                query["paginationToken"] = cursor
            page = retry_read(client.get, BASE_PATH, query)
            rows = page.get("inboundPlans")
            if not isinstance(rows, list):
                raise RuntimeError("入库计划列表格式异常；无法确认完整检查。")
            reached_boundary = False
            for row in rows:
                try:
                    created = parse_time(row.get("createdAt"))
                except (TypeError, ValueError):
                    raise RuntimeError("入库计划缺少有效创建时间；无法确认近三个月范围。")
                if previous_created is not None and created > previous_created:
                    raise RuntimeError("入库计划未按创建时间倒序返回；无法可靠停止历史分页。")
                previous_created = created
                if created < cutoff:
                    reached_boundary = True
                    continue
                plans[id_path(row.get("inboundPlanId"))] = row
            pages += 1
            if reached_boundary:
                boundary_statuses.append(status)
                break
            cursor = (page.get("pagination") or {}).get("nextToken")
            if not cursor:
                break
            if not isinstance(cursor, str) or cursor in tokens or pages >= 1000:
                raise RuntimeError("分页未正常结束；不会发送无异常结论。")
            tokens.add(cursor)
    print("已读取近 %d 个月范围的 %d 页，共 %d 个入库计划（自 %s 北京时间）。"
          % (months, pages, len(plans), format_time(cutoff.isoformat())), flush=True)
    shipments, summaries_seen, excluded_awd = {}, set(), []
    finished_count = 0
    checked_plans = 0
    for index, plan_id in enumerate(plans, 1):
        checked_plans += 1
        try:
            detail = retry_read(client.get, BASE_PATH + "/" + plan_id)
        except ApiError as error:
            if error.status == 400 and any(
                    "Operation GetInboundPlan is not supported for Amazon Warehousing and Distribution inbound plans."
                    in message for message in error.service_messages):
                excluded_awd.append(plan_id)
                continue
            raise
        # The official schema omits this optional field for plans without shipments.
        summaries = detail.get("shipments", [])
        if not isinstance(summaries, list):
            raise RuntimeError("入库计划的货件列表格式异常。")
        for summary in summaries:
            ship_id = id_path(summary.get("shipmentId"))
            if ship_id in summaries_seen:
                continue
            summaries_seen.add(ship_id)
            if summary.get("status") in FINISHED:
                finished_count += 1
                continue
            shipment = retry_read(client.get, BASE_PATH + "/" + plan_id + "/shipments/" + ship_id)
            if shipment.get("shipmentId") != ship_id:
                raise RuntimeError("亚马逊返回了不匹配的货件标识。")
            window = shipment.get("selectedDeliveryWindow") or {}
            item = {"shipmentId": ship_id,
                    "shipmentConfirmationId": shipment.get("shipmentConfirmationId"),
                    "inboundPlanCreatedAt": plans[plan_id]["createdAt"],
                    "warehouseId": (shipment.get("destination") or {}).get("warehouseId"),
                    "status": shipment.get("status"),
                    "marketplaceIds": detail.get("marketplaceIds", []),
                    "deliveryWindow": {key: window.get(key)
                        for key in ("startDate", "endDate", "editableUntil")}}
            if item["status"] in FINISHED:
                finished_count += 1
            else:
                shipments[ship_id] = item
        if index % 10 == 0 or index == len(plans):
            print("已读取 %d/%d 个计划、%d 个货件。" % (index, len(plans), len(shipments)), flush=True)
        if (utcnow() - started).total_seconds() > 2700:
            raise RuntimeError("本次范围检查超过 45 分钟；未确认完成，请检查接口。")
    result = {"scan_started_at": started.isoformat(), "checked_at": utcnow().isoformat(),
              "complete": True, "region": client.config["region"],
              "scope": {"date_field": "inboundPlan.createdAt", "lookback_months": months,
                        "start_inclusive": cutoff.isoformat(), "end": started.isoformat(),
                        "plan_statuses": list(plan_statuses)},
              "coverage": "all_scoped_plans_read", "boundary_statuses": boundary_statuses,
              "plan_pages": pages, "plan_count": checked_plans - len(excluded_awd),
              "plan_details_read": checked_plans,
              "listed_plan_count": len(plans), "excluded_awd_plans": excluded_awd,
              "finished_shipments_excluded": finished_count,
              "shipments": list(shipments.values())}
    private_write(SNAPSHOT, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def classify(shipments, now, include_expired=False):
    upcoming, overdue, missing = [], [], []
    for shipment in shipments:
        if shipment.get("status") in FINISHED:
            continue
        raw = (shipment.get("deliveryWindow") or {}).get("editableUntil")
        try:
            deadline = parse_time(raw)
        except (ValueError, TypeError):
            if shipment.get("status") not in FINISHED:
                missing.append(shipment)
            continue
        remaining = (deadline - now).total_seconds()
        if 0 <= remaining <= 48 * 3600:
            upcoming.append(shipment)
        elif include_expired and remaining < 0 and shipment.get("status") not in FINISHED:
            overdue.append(shipment)
    def order(item):
        return parse_time(item["deliveryWindow"]["editableUntil"])
    return sorted(upcoming, key=order), sorted(overdue, key=order), missing


def clean(value):
    return str(value or "接口未提供").replace("\n", " ").replace("\r", " ").replace("|", "／")


def shipment_block(item):
    window = item.get("deliveryWindow") or {}
    return ("**货件编号：%s**\n\n仓库：%s  \n最晚可编辑时间：%s  \n当前送达窗口：%s 至 %s\n"
            % (clean(item.get("shipmentConfirmationId")), clean(item.get("warehouseId")),
               format_time(window.get("editableUntil")), format_time(window.get("startDate")),
               format_time(window.get("endDate"))))


def build_messages(snapshot, include_expired=False, now=None, test=False):
    if snapshot.get("complete") is not True:
        raise RuntimeError("扫描未完成，不能生成每日检查结论。")
    now = now or parse_time(snapshot["checked_at"])
    upcoming, overdue, missing = classify(snapshot["shipments"], now, include_expired)
    prefix = "FBA手动实测" if test else "FBA送达窗口提醒"
    title = "%s｜临期%d票，已截止%d票" % (prefix, len(upcoming), len(overdue))
    header = ("检查时间：%s（北京时间，UTC+8）  \n共检查 %d 个入库计划、%d 个未完成货件。"
              "  \n以下时间均为北京时间。\n\n"
              % (now.astimezone(BJ).strftime("%Y-%m-%d %H:%M"), snapshot["plan_count"],
                 len(snapshot["shipments"])))
    scope = snapshot.get("scope")
    if scope:
        header += "检查范围：近 %d 个月创建的入库计划（自 %s 起，含起点）。\n\n" % (
            scope["lookback_months"], format_time(scope["start_inclusive"]))
    if snapshot.get("excluded_awd_plans"):
        header += "另有 %d 个 AWD 入库计划，不属于本次 FBA 送达窗口检查范围。\n\n" % len(snapshot["excluded_awd_plans"])
    blocks = ["### 48小时内停止编辑：%d 票\n" % len(upcoming)]
    blocks += [shipment_block(item) for item in upcoming]
    if not upcoming:
        blocks.append("在已返回截止时间的货件中，今日无未来 0–48 小时内停止编辑的货件。\n"
                      if missing else "今日无未来 0–48 小时内停止编辑的货件。\n")
    if include_expired:
        blocks += ["### 已过编辑截止时间的未完成货件：%d 票\n" % len(overdue)]
        blocks += [shipment_block(item) for item in overdue]
    if missing:
        blocks += ["### 暂时无法判断：%d 票\n\n以下未完成货件未返回有效的最晚可编辑时间，需在后台核对。\n" % len(missing)]
        blocks += [shipment_block(item) for item in missing]
    if test:
        blocks += ["这是本次手动触发的真实数据测试。\n"]
    # Split at shipment boundaries so a large account is never silently truncated.
    chunks, current = [], header
    for block in blocks:
        if len((current + "\n" + block).encode("utf-8")) > 12000 and current != header:
            chunks.append(current)
            current = header
        current += "\n" + block
    chunks.append(current)
    messages = [(title + ("（%d/%d）" % (i, len(chunks)) if len(chunks) > 1 else ""), body)
                for i, body in enumerate(chunks, 1)]
    return messages, {"upcoming": len(upcoming), "overdue": len(overdue), "missing_deadline": len(missing)}


def deliver_once(messages, key, sender=None):
    sender = sender or send
    folder = RUNTIME / "deliveries"
    path = folder / (key + ".json")
    if path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("state") == "accepted":
            print("该批消息已被推送服务接受，跳过重复发送。", flush=True)
            return
        raise RuntimeError("该批消息已有未确认的发送记录；为避免重复，不自动重发，请检查 Server酱日志。")
    record = {"state": "sending", "started_at": utcnow().isoformat(),
              "message_count": len(messages), "accepted_parts": 0}
    private_write(path, json.dumps(record, ensure_ascii=False, indent=2))
    try:
        for i, (title, body) in enumerate(messages, 1):
            sender(title, body)
            record["accepted_parts"] = i
            private_write(path, json.dumps(record, ensure_ascii=False, indent=2))
            if i < len(messages):
                time.sleep(1.1)
        record["state"] = "accepted"
        record["finished_at"] = utcnow().isoformat()
        private_write(path, json.dumps(record, ensure_ascii=False, indent=2))
    except Exception:
        record["state"] = "delivery_unconfirmed"
        private_write(path, json.dumps(record, ensure_ascii=False, indent=2))
        raise


def run(mode):
    policy = load_policy()
    now = utcnow().astimezone(BJ)
    if mode == "scheduled" and now.hour < 9:
        print("尚未到北京时间 09:00，本次不发送。")
        return 0
    daily_key = now.strftime("%Y-%m-%d")
    if mode == "scheduled":
        existing = RUNTIME / "deliveries" / (daily_key + ".json")
        if existing.exists():
            state = json.loads(existing.read_text(encoding="utf-8")).get("state")
            if state == "accepted":
                print("今天已经完成推送，跳过重复运行。")
                return 0
            raise RuntimeError("今天已有未确认的发送记录，请核对推送日志；未自动重发。")
    try:
        if mode == "send-test":
            snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
            scope = snapshot.get("scope") or {}
            if (snapshot.get("coverage") != "all_scoped_plans_read"
                    or scope.get("lookback_months") != policy["lookback_months"]
                    or scope.get("date_field") != "inboundPlan.createdAt"
                    or scope.get("plan_statuses") != ["ACTIVE", "SHIPPED"]
                    or snapshot.get("plan_details_read") != snapshot.get("listed_plan_count")):
                raise RuntimeError("旧快照未按当前月份范围完整检查，请先运行 preview。")
            age = (utcnow() - parse_time(snapshot["checked_at"])).total_seconds()
            if age < 0 or age > 900:
                raise RuntimeError("测试数据超过 15 分钟，请先重新执行 preview。")
        else:
            snapshot = scan()
        messages, counts = build_messages(snapshot, policy["include_expired"], test=mode == "send-test")
        private_write(REPORT, "\n\n---\n\n".join("# " + title + "\n\n" + body for title, body in messages))
        print(json.dumps({"complete": True, "plans": snapshot["plan_count"],
            "shipments": len(snapshot["shipments"]), "counts": counts,
            "message_parts": len(messages), "report_file": str(REPORT)}, ensure_ascii=False), flush=True)
    except Exception as error:
        if mode == "scheduled":
            # No raw exception text is sent: upstream data or credentials may be involved.
            body = "今天的货件检查未能完整完成，不能判断是否存在临近截止的货件。请打开 Codex 的 FBA货件提醒对话排查。"
            deliver_once([("FBA货件检查失败", body)], daily_key + "-failure")
        raise
    if mode != "preview":
        key = ("test-" + hashlib.sha256(snapshot["checked_at"].encode()).hexdigest()[:16]
               if mode == "send-test" else daily_key)
        deliver_once(messages, key)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preview", "send-test", "scheduled"))
    mode = parser.parse_args().mode
    private_write(RUNTIME / "reminder_runtime_marker", "FBA shipment reminder\n")
    try:
        with process_lock(RUNTIME / "reminder.lock"):
            return run(mode)
    except BlockingIOError:
        print("已有货件检查正在运行，本次未执行。", file=sys.stderr)
        return 2
    except (RuntimeError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (KeyError, TypeError, AttributeError):
        print("配置或接口数据格式异常；本次任务未完成。", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    utf8_console()
    sys.exit(main())
