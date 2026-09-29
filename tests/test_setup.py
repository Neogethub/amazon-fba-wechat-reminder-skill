import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/fba-shipment-reminder/scripts"
sys.path.insert(0, str(SCRIPTS))
import amazon_spapi as api
import configure
import credentials
import local_state
import shipment_reminder as job
import wechat_notify as push

DUMMY = {"client_id": "amzn1.application-oa2-client.DUMMYONLY",
         "client_secret": "dummy-secret-not-a-real-key",
         "refresh_token": "dummy-refresh-not-a-real-token", "region": "NA",
         "sendkey": "SCT000000000000DUMMYONLY"}


class SetupTests(unittest.TestCase):
    def test_schedule_uses_same_instant_in_different_timezones_and_dst_seasons(self):
        # Covers the US spring/fall transition dates and both US Pacific offsets,
        # without relying on the host's time zone database (including Windows).
        for day in ((2026, 3, 7), (2026, 3, 8), (2026, 10, 31), (2026, 11, 1)):
            instant = datetime(*day, 0, 30, tzinfo=timezone.utc)
            for offset in (-8, -7, 0, 8, 14):
                with self.subTest(day=day, offset=offset):
                    local = instant.astimezone(timezone(timedelta(hours=offset)))
                    result = configure.schedule_info(local)
                    expected = instant.replace(hour=1, minute=0)
                    self.assertEqual(job.parse_time(result["next_run_utc"]), expected)
                    self.assertEqual(job.parse_time(result["next_beijing_run"]), expected)
                    self.assertEqual(result["scheduler_timezone"], "UTC")
                    self.assertEqual(result["scheduler_daily_time"], "01:00")

    def test_schedule_rolls_forward_at_nine_and_across_year_boundary(self):
        for source, expected in (
                ("2026-09-29T00:59:59+00:00", "2026-09-29T01:00:00+00:00"),
                ("2026-09-29T01:00:00+00:00", "2026-09-30T01:00:00+00:00"),
                ("2026-12-31T16:30:00+00:00", "2027-01-01T01:00:00+00:00")):
            with self.subTest(source=source):
                result = configure.schedule_info(datetime.fromisoformat(source))
                self.assertEqual(job.parse_time(result["next_run_utc"]), datetime.fromisoformat(expected))
                self.assertGreater(job.parse_time(result["next_beijing_run"]), datetime.fromisoformat(source))
        with self.assertRaises(ValueError):
            configure.schedule_info(datetime(2026, 9, 29, 9))

    def test_schedule_info_cli_is_calculation_only_and_does_not_access_credentials(self):
        with patch.object(sys, "argv", ["configure.py", "schedule-info"]), \
             patch.object(configure, "load_config") as creds, \
             patch.object(configure, "load_key") as key, \
             patch.object(configure, "send") as sender, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(configure.main(), 0)
        result = json.loads(output.getvalue())
        self.assertFalse(result["scheduler_verified"])
        self.assertEqual(result["next_run_source"], "calculated_target_not_saved_schedule")
        self.assertIn(str(SCRIPTS/"shipment_reminder.py"), result["command"])
        creds.assert_not_called()
        key.assert_not_called()
        sender.assert_not_called()

    def test_cli_emits_utf8_even_when_parent_pipes_use_ascii(self):
        env = dict(os.environ, PYTHONIOENCODING="ascii", SP_API_CLIENT_ID="",
                   SP_API_CLIENT_SECRET="", SP_API_REFRESH_TOKEN="")
        result = subprocess.run([sys.executable, str(SCRIPTS/"configure.py"), "status"],
                                env=env, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("请填写", result.stderr.decode("utf-8"))
        self.assertNotIn(b"Traceback", result.stderr)

    def test_env_credentials_without_os_storage_and_no_partial_fallback(self):
        values = {"SP_API_CLIENT_ID": DUMMY["client_id"], "SP_API_CLIENT_SECRET": DUMMY["client_secret"],
                  "SP_API_REFRESH_TOKEN": DUMMY["refresh_token"], "SP_API_REGION": "eu",
                  "SERVERCHAN_SENDKEY": DUMMY["sendkey"]}
        with patch.dict(os.environ, values, clear=True), patch.object(api, "read_credentials") as storage:
            self.assertEqual(api.load_config()["region"], "EU")
            self.assertEqual(push.load_key(), DUMMY["sendkey"])
            storage.assert_not_called()
        with patch.dict(os.environ, {"SP_API_CLIENT_ID": ""}, clear=True), patch.object(api, "read_credentials") as storage:
            with self.assertRaises(ValueError):
                api.load_config()
            storage.assert_not_called()

    def test_form_local_only_csrf_single_save_and_idle_preconnection(self):
        saved = []
        with configure.make_setup_server(saved.append) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            idle = socket.create_connection(server.server_address, timeout=2)
            opener = build_opener(ProxyHandler({}))
            try:
                with opener.open(server.page_url, timeout=3) as response:
                    page = response.read().decode("utf-8")
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                token = re.search('name="csrf" value="([^"]+)"', page).group(1)
                data = dict(DUMMY, csrf=token)
                def submit(values, headers):
                    return opener.open(Request(server.page_url, data=urlencode(values).encode(), headers=headers), timeout=3)
                for values, headers in ((data, {"Origin":"https://example.com"}),
                                        (data, {"Origin":"null"}), (dict(data, csrf="wrong"), {}),
                                        (data, {"Host":"example.com"})):
                    with self.assertRaises(HTTPError) as caught:
                        submit(values, headers)
                    self.assertEqual(caught.exception.code, 403)
                self.assertFalse(saved)
                with submit(data, {"Origin":"http://" + server.expected_host}) as response:
                    body = response.read().decode("utf-8")
                    self.assertEqual(response.status, 200)
                    for key in ("client_secret", "refresh_token", "sendkey"):
                        self.assertNotIn(DUMMY[key], body)
                self.assertEqual(saved, [DUMMY])
                with self.assertRaises(HTTPError) as caught:
                    submit(data, {})
                self.assertEqual(caught.exception.code, 409)
            finally:
                idle.close()
                server.shutdown()
                worker.join()

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI integration")
    def test_windows_credentials_round_trip_is_encrypted(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(credentials, "SEALED_FILE", Path(directory)/"key.dpapi"):
            credentials.save_credentials(DUMMY)
            self.assertEqual(credentials.read_credentials(), DUMMY)
            text = credentials.SEALED_FILE.read_text(encoding="utf-8")
            self.assertNotIn(DUMMY["client_secret"], text)
            self.assertNotIn(DUMMY["sendkey"], text)

    def test_process_lock_blocks_second_process_then_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"lock"
            code = "from pathlib import Path\nimport sys\nfrom local_state import process_lock\ntry:\n with process_lock(Path(sys.argv[1])): pass\nexcept BlockingIOError:\n sys.exit(2)\n"
            env = dict(os.environ, PYTHONPATH=str(SCRIPTS), PYTHONUTF8="1")
            with local_state.process_lock(path):
                result = subprocess.run([sys.executable, "-c", code, str(path)], env=env, capture_output=True)
                self.assertEqual(result.returncode, 2, result.stderr)
            result = subprocess.run([sys.executable, "-c", code, str(path)], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_auth_failures_do_not_echo_secrets(self):
        body = json.dumps({"error":"invalid_client", "error_description":DUMMY["client_secret"]}).encode()
        error = HTTPError("https://api.amazon.com/auth/o2/token", 400, "Bad Request", {}, io.BytesIO(body))
        with patch.object(api, "build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaises(RuntimeError) as caught:
                api.Client(DUMMY).authenticate()
            self.assertNotIn(DUMMY["client_secret"], str(caught.exception))

    def test_client_whitelist_blocks_other_api_and_external_hosts(self):
        client = api.Client(DUMMY)
        client.token = "DUMMY"
        for path in ("/orders/v0/orders", api.BASE_PATH + "/../orders", "https://example.com", "/fba/inbound/v0/shipments"):
            with self.assertRaises(ValueError):
                client.get(path)

    def test_preview_then_send_real_format_with_no_automatic_resend(self):
        now = datetime(2026, 9, 28, 3, tzinfo=timezone.utc)
        snapshot = {"complete":True, "checked_at":now.isoformat(), "coverage":"all_scoped_plans_read",
                    "scope":{"lookback_months":3, "date_field":"inboundPlan.createdAt",
                             "plan_statuses":["ACTIVE", "SHIPPED"], "start_inclusive":"2026-06-27T16:00:00Z"},
                    "plan_details_read":1, "listed_plan_count":1, "plan_count":1,
                    "shipments":[{"shipmentConfirmationId":"FBA-DEMO-ONLY", "warehouseId":"DEMO",
                                  "status":"SHIPPED", "deliveryWindow":{"editableUntil":"2026-09-29T03:00:00Z",
                                  "startDate":"2026-10-01T00:00:00Z", "endDate":"2026-10-07T23:59:00Z"}}]}
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch.object(job, "RUNTIME", folder), patch.object(job, "REPORT", folder/"report.md"), \
                 patch.object(job, "SNAPSHOT", folder/"snapshot.json"), patch.object(job, "utcnow", return_value=now), \
                 patch.object(job, "scan", return_value=snapshot), patch.object(job, "send") as sender, \
                 contextlib.redirect_stdout(io.StringIO()):
                job.run("preview")
                sender.assert_not_called()
                local_state.private_write(job.SNAPSHOT, json.dumps(snapshot))
                job.run("send-test")
                job.run("send-test")
                sender.assert_called_once()
                body = sender.call_args[0][1]
                for expected in ("FBA-DEMO-ONLY", "DEMO", "2026-09-29 11:00", "2026-10-01 08:00", "2026-10-08 07:59"):
                    self.assertIn(expected, body)


if __name__ == "__main__":
    unittest.main()
