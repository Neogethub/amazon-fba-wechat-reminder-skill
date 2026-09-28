import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/fba-shipment-reminder/scripts"))
from datetime import datetime, timedelta, timezone
import io
import contextlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import shipment_reminder as job
from amazon_spapi import ApiError, BASE_PATH


NOW = datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)
PLAN = "wf1234abcd-1234-abcd-5678-1234abcd5678"
SHIP = "sh1234abcd-1234-abcd-5678-1234abcd5678"


def item(hours=None, status="SHIPPED", number="FBA-TEST"):
    return {"shipmentId": SHIP, "shipmentConfirmationId": number,
            "warehouseId": "IWA6", "status": status,
            "deliveryWindow": {"editableUntil": (NOW + timedelta(hours=hours)).isoformat() if hours is not None else None,
                               "startDate": "2026-10-01T00:00Z", "endDate": "2026-10-07T23:59Z"}}


class ReminderTests(unittest.TestCase):
    def setUp(self):
        clock = patch.object(job, "utcnow", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def test_old_unreconciled_snapshot_cannot_be_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"old.json"
            path.write_text(json.dumps({"complete": True, "checked_at": job.utcnow().isoformat()}))
            with patch.object(job, "SNAPSHOT", path), patch.object(job, "deliver_once") as sender:
                with self.assertRaisesRegex(RuntimeError, "月份范围"):
                    job.run("send-test")
                sender.assert_not_called()

    def test_month_boundary_in_beijing_and_month_end_clamping(self):
        self.assertEqual(job.lookback_start(NOW, 3).isoformat(), "2026-06-27T16:00:00+00:00")
        august31 = datetime(2026, 8, 31, 1, tzinfo=timezone.utc)
        self.assertEqual(job.lookback_start(august31, 6).isoformat(), "2026-02-27T16:00:00+00:00")
        with self.assertRaises(RuntimeError):
            job.lookback_start(NOW, 0)

    def test_only_recent_plans_read_and_pagination_stops_at_month_boundary(self):
        client = Mock(config={"region": "NA"})
        p2, old = PLAN.replace("wf1", "wf2", 1), PLAN.replace("wf1", "wf3", 1)
        detail_paths, statuses = [], []
        cutoff = job.lookback_start(NOW, 3)
        def get(path, query=None):
            if path == BASE_PATH:
                self.assertEqual((query["sortBy"], query["sortOrder"]), ("CREATION_TIME", "DESC"))
                self.assertNotIn("paginationToken", query)
                statuses.append(query["status"])
                recent = PLAN if query["status"] == "ACTIVE" else p2
                return {"inboundPlans": [
                    {"inboundPlanId": recent, "createdAt": cutoff.isoformat(), "status": query["status"]},
                    {"inboundPlanId": old, "createdAt": (cutoff-timedelta(microseconds=1)).isoformat()}],
                    "pagination": {"nextToken": "older-page-must-not-be-read"}}
            self.assertNotEqual(path, "/fba/inbound/v0/shipments")
            if "/shipments/" in path:
                return {"shipmentId": SHIP, "shipmentConfirmationId": "FBA-TEST", "status": "SHIPPED"}
            detail_paths.append(path)
            return {"shipments": [{"shipmentId": SHIP, "status": "SHIPPED"}]} if path.endswith(PLAN) else {}
        client.get.side_effect = get
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(job, "SNAPSHOT", Path(directory)/"sample.json"), \
             contextlib.redirect_stdout(io.StringIO()):
            result = job.scan(client)
        self.assertEqual(detail_paths, [BASE_PATH + "/" + PLAN, BASE_PATH + "/" + p2])
        self.assertEqual(statuses, ["ACTIVE", "SHIPPED"])
        self.assertEqual(result["listed_plan_count"], 2)
        self.assertEqual(result["coverage"], "all_scoped_plans_read")
        self.assertEqual(result["boundary_statuses"], ["ACTIVE", "SHIPPED"])
        self.assertEqual(result["shipments"][0]["inboundPlanCreatedAt"], cutoff.isoformat())
        messages, _ = job.build_messages(result, True)
        self.assertIn("近 3 个月", messages[0][1])
        self.assertIn("2026-06-28 00:00", messages[0][1])

    def test_missing_or_out_of_order_creation_dates_fail(self):
        client = Mock(config={"region": "NA"})
        client.get.return_value = {"inboundPlans": [{"inboundPlanId": PLAN}]}
        with self.assertRaisesRegex(RuntimeError, "创建时间"):
            job.scan(client)
        client.get.side_effect = [
            {"inboundPlans": [{"inboundPlanId": PLAN, "createdAt": (NOW-timedelta(days=1)).isoformat()}],
             "pagination": {"nextToken": "p2"}},
            {"inboundPlans": [{"inboundPlanId": PLAN, "createdAt": NOW.isoformat()}]}]
        with self.assertRaisesRegex(RuntimeError, "倒序"):
            job.scan(client)

    def test_draft_plan_without_optional_shipments_is_valid(self):
        client = Mock(config={"region": "NA"})
        client.get.side_effect = [{"inboundPlans": [{"inboundPlanId": PLAN, "createdAt": NOW.isoformat()}]}, {}]
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(job, "SNAPSHOT", Path(directory)/"sample.json"), \
             contextlib.redirect_stdout(io.StringIO()):
            result = job.scan(client, plan_statuses=("ACTIVE",))
        self.assertTrue(result["complete"])
        self.assertEqual(result["shipments"], [])

    def test_only_known_awd_error_can_be_excluded(self):
        client = Mock(config={"region": "NA"})
        known = ApiError("known", status=400, service_messages=(
            "ERROR: Operation GetInboundPlan is not supported for Amazon Warehousing and Distribution inbound plans.",))
        client.get.side_effect = [{"inboundPlans": [{"inboundPlanId": PLAN, "createdAt": NOW.isoformat()}]}, known]
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(job, "SNAPSHOT", Path(directory)/"sample.json"), \
             contextlib.redirect_stdout(io.StringIO()):
            result = job.scan(client, plan_statuses=("ACTIVE",))
        self.assertEqual(result["excluded_awd_plans"], [PLAN])
        self.assertEqual(result["plan_count"], 0)
        client.get.side_effect = [{"inboundPlans": [{"inboundPlanId": PLAN, "createdAt": NOW.isoformat()}]}, ApiError("other", status=400)]
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ApiError):
            job.scan(client, plan_statuses=("ACTIVE",))

    def test_exact_48_hour_and_zero_boundaries(self):
        rows = [item(48, number="exact48"), item(48.001, number="outside"),
                item(0, number="zero"), item(-0.001, number="expired")]
        upcoming, overdue, missing = job.classify(rows, NOW, True)
        self.assertEqual([row["shipmentConfirmationId"] for row in upcoming], ["zero", "exact48"])
        self.assertEqual([row["shipmentConfirmationId"] for row in overdue], ["expired"])
        self.assertEqual(missing, [])

    def test_overdue_only_unfinished_and_missing_is_not_clear(self):
        rows = [item(-20), item(-20, status="CLOSED"), item(None), item(None, status="RECEIVING"),
                item(24, status="DELIVERED")]
        upcoming, overdue, missing = job.classify(rows, NOW, True)
        self.assertEqual((len(upcoming), len(overdue), len(missing)), (0, 1, 1))
        snapshot = {"complete": True, "checked_at": NOW.isoformat(), "plan_count": 1, "shipments": rows}
        messages, counts = job.build_messages(snapshot, True)
        self.assertIn("暂时无法判断：1 票", messages[0][1])
        self.assertIn("在已返回截止时间的货件中", messages[0][1])

    def test_beijing_display_and_naive_timestamp_rejected(self):
        self.assertEqual(job.format_time("2026-09-28T01:00Z"), "2026-09-28 09:00")
        self.assertEqual(job.format_time("2026-10-31T23:59Z"), "2026-11-01 07:59")
        with self.assertRaises(ValueError):
            job.parse_time("2026-09-28T09:00")

    def test_empty_page_with_next_token_still_scans_and_deduplicates(self):
        client = Mock(config={"region": "NA"})
        row = item(24)
        client.get.side_effect = [
            {"inboundPlans": [{"inboundPlanId": PLAN, "createdAt": NOW.isoformat()}], "pagination": {"nextToken": "p2"}},
            {"inboundPlans": [], "pagination": {"nextToken": "p3"}},
            {"inboundPlans": [{"inboundPlanId": PLAN, "createdAt": NOW.isoformat()}]},
            {"shipments": [{"shipmentId": SHIP}, {"shipmentId": SHIP}], "marketplaceIds": ["US"]},
            {"shipmentId": SHIP, "shipmentConfirmationId": "FBA-TEST", "status": "SHIPPED",
             "destination": {"warehouseId": "IWA6"}, "selectedDeliveryWindow": row["deliveryWindow"],
             "contactInformation": {"secret": "should not be saved"}}]
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(job, "SNAPSHOT", Path(directory)/"sample.json"), \
             contextlib.redirect_stdout(io.StringIO()):
            result = job.scan(client, plan_statuses=("ACTIVE",))
        self.assertEqual((result["plan_pages"], result["plan_count"], len(result["shipments"])), (3, 1, 1))
        self.assertNotIn("should not be saved", json.dumps(result))

    def test_repeated_cursor_fails_instead_of_partial_success(self):
        client = Mock(config={"region": "NA"})
        client.get.return_value = {"inboundPlans": [], "pagination": {"nextToken": "same"}}
        with self.assertRaises(RuntimeError):
            job.scan(client, plan_statuses=("ACTIVE",))

    def test_unknown_delivery_is_not_retried_and_accepted_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(job, "RUNTIME", Path(directory)):
            sender = Mock(side_effect=RuntimeError("network failed"))
            with self.assertRaises(RuntimeError):
                job.deliver_once([("test", "body")], "daily", sender)
            with self.assertRaises(RuntimeError):
                job.deliver_once([("test", "body")], "daily", sender)
            self.assertEqual(sender.call_count, 1)
            ok = Mock()
            with contextlib.redirect_stdout(io.StringIO()):
                job.deliver_once([("test", "body")], "other-day", ok)
                job.deliver_once([("test", "body")], "other-day", ok)
            self.assertEqual(ok.call_count, 1)

    def test_large_report_keeps_every_shipment(self):
        rows = [item(24, number="FBA-UNIQUE-%04d" % i) for i in range(200)]
        messages, counts = job.build_messages({"complete": True, "checked_at": NOW.isoformat(),
                                               "plan_count": 1, "shipments": rows}, True)
        self.assertGreater(len(messages), 1)
        all_text = "\n".join(body for _, body in messages)
        for row in rows:
            self.assertEqual(all_text.count(row["shipmentConfirmationId"]), 1)
        self.assertEqual(counts["upcoming"], 200)


if __name__ == "__main__":
    unittest.main()
