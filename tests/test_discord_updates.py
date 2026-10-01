import copy
import io
import json
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from discord_updates import REPOSITORY, deliver, message_for, webhook_endpoint


class UpdatesTests(unittest.TestCase):
    def setUp(self):
        self.event = {
            "repository": {"full_name": REPOSITORY, "private": False},
            "action": "published",
            "release": {"id": 42, "draft": False, "published_at": "2026-10-01T12:00:00Z",
                        "tag_name": "v0.3.0-alpha.1", "name": "RAIDWAKE 0.3.0 Alpha 1",
                        "prerelease": True, "body": "Fixes and changes."},
        }

    def test_alpha_and_stable(self):
        for prerelease in (True, False):
            self.event["release"]["prerelease"] = prerelease
            message = message_for(self.event, "release")
            self.assertEqual(message["allowed_mentions"], {"parse": []})
            self.assertEqual("Alpha / prerelease" if prerelease else "Release", message["embeds"][0]["footer"]["text"])
            self.assertEqual(len(message["embeds"]), 1)

    def test_private_missing_flag_and_wrong_repository(self):
        for repository in ({"full_name": REPOSITORY, "private": True}, {"full_name": REPOSITORY},
                           {"full_name": "RAIDWAKE/RAIDWAKE", "private": False}):
            event = copy.deepcopy(self.event)
            event["repository"] = repository
            self.assertIsNone(message_for(event, "release"))

    def test_only_published(self):
        for action in ("created", "edited", "deleted", "prereleased", "unpublished"):
            self.event["action"] = action
            self.assertIsNone(message_for(self.event, "release"))

    def test_draft_and_no_publish_date(self):
        self.event["release"]["draft"] = True
        self.assertIsNone(message_for(self.event, "release"))
        self.event["release"]["draft"] = False
        self.event["release"]["published_at"] = None
        self.assertIsNone(message_for(self.event, "release"))

    def test_rerun_does_not_repeat_release(self):
        self.assertIsNone(message_for(self.event, "release", "2"))

    def test_unrelated_event(self):
        self.assertIsNone(message_for(self.event, "push"))

    def test_connection_check_is_not_release(self):
        message = message_for(self.event, "workflow_dispatch")
        self.assertNotIn("embeds", message)
        self.assertIn("not a game update", message["content"])

    def test_bounded_notes_and_no_mass_mentions(self):
        self.event["release"]["body"] = "@everyone " * 1000
        message = message_for(self.event, "release")
        self.assertLessEqual(len(message["embeds"][0]["description"]), 3500)
        self.assertEqual(message["allowed_mentions"]["parse"], [])

    def test_link_cannot_point_elsewhere(self):
        self.event["release"]["html_url"] = "https://example.invalid"
        self.event["release"]["tag_name"] = "alpha/#?&"
        content = message_for(self.event, "release")["embeds"][0]["description"]
        self.assertIn(f"https://github.com/{REPOSITORY}/releases/tag/alpha%2F%23%3F%26", content)
        self.assertNotIn("example.invalid", content)

    def test_long_names_and_tags_remain_bounded(self):
        self.event["release"].update(name="x" * 5000, tag_name="/" * 5000, body="n" * 5000)
        message = message_for(self.event, "release")
        self.assertLessEqual(len(message["embeds"][0]["description"]), 3500)
        self.assertLessEqual(len(message["embeds"][0]["title"]), 200)
        self.assertNotIn("content", message)

    def test_webhook_validation(self):
        valid = "https://discord.com/api/webhooks/123/test-token"
        self.assertEqual(webhook_endpoint(valid), valid + "?wait=true")
        for value in ("", valid + "?wait=false", valid.replace("discord.com", "discord.com.example.invalid"),
                      valid.replace("https:", "http:"), valid + "/github"):
            with self.assertRaises(ValueError):
                webhook_endpoint(value)

    def test_confirmed_delivery(self):
        class Response(io.BytesIO):
            status = 200
        class Transport:
            def open(inner, request, timeout):
                self.assertEqual(timeout, 30)
                self.assertEqual(request.method, "POST")
                self.assertIn("wait=true", request.full_url)
                self.assertEqual(json.loads(request.data)["allowed_mentions"], {"parse": []})
                return Response(b'{"id":"456"}')
        deliver("https://discord.com/api/webhooks/123/test-token", message_for(self.event, "release"), Transport())

    def test_delivery_failure_does_not_leak_secret_or_retry(self):
        secret = "https://discord.com/api/webhooks/123/test-token"
        for failure in (HTTPError(secret, 429, secret, {}, None), URLError(secret)):
            class Transport:
                calls = 0
                def open(inner, request, timeout):
                    inner.calls += 1
                    raise failure
            transport = Transport()
            with self.assertRaises(RuntimeError) as captured:
                deliver(secret, message_for(self.event, "release"), transport)
            self.assertNotIn("test-token", str(captured.exception))
            self.assertEqual(transport.calls, 1)


if __name__ == "__main__":
    unittest.main()
