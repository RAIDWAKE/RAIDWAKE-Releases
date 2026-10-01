import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from eft_news import parse_feed, process, message_for

URL = "https://steamcommunity.com/games/3932890/announcements/detail/123"
XML = f'''<rss><channel><title>Escape from Tarkov RSS Feed</title><item>
<title>Patch 1.2</title><link>{URL}</link><pubDate>Tue, 15 Sep 2026 13:08:44 +0000</pubDate>
<description>&lt;img src="https://clan.akamai.steamstatic.com/images/1/test.jpg" /&gt;</description>
</item></channel></rss>'''.encode()


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.items = parse_feed(XML)
        self.saved = []
        self.sent = []

    def save(self, state):
        self.saved.append(copy.deepcopy(state))

    def test_official_feed_and_card(self):
        card = message_for(self.items[0])
        self.assertEqual(card["allowed_mentions"], {"parse": []})
        self.assertEqual(card["embeds"][0]["url"], URL)
        self.assertIn("image", card["embeds"][0])
        self.assertEqual(len(card["embeds"]), 1)

    def test_no_initial_news_dump(self):
        state, count = process(self.items, None, self.save, self.sent.append)
        self.assertEqual(count, 0)
        self.assertFalse(self.sent)
        self.assertEqual(state["stories"][URL], "baseline")

    def test_new_story_once(self):
        state = {"version": 1, "stories": {}}
        state, count = process(self.items, state, self.save, self.sent.append)
        self.assertEqual(count, 1)
        self.assertEqual(self.saved[0]["stories"][URL], "pending")
        self.assertEqual(self.saved[1]["stories"][URL], "posted")
        process(self.items, state, self.save, self.sent.append)
        self.assertEqual(len(self.sent), 1)

    def test_unknown_delivery_not_retried(self):
        def fail(message):
            raise RuntimeError("Unknown delivery")
        with self.assertRaises(RuntimeError):
            process(self.items, {"version": 1, "stories": {}}, self.save, fail)
        with self.assertRaises(RuntimeError):
            process(self.items, self.saved[-1], self.save, self.sent.append)
        self.assertFalse(self.sent)

    def test_no_post_if_claim_cannot_be_saved(self):
        def fail(state):
            raise RuntimeError("State unavailable")
        with self.assertRaises(RuntimeError):
            process(self.items, {"version": 1, "stories": {}}, fail, self.sent.append)
        self.assertFalse(self.sent)

    def test_invalid_sources_and_empty_fail_closed(self):
        for raw in (XML.replace(b"3932890/announcements", b"1/announcements"),
                    XML.replace(b"Escape from Tarkov RSS Feed", b"Third party news"),
                    b"<rss><channel><title>Escape from Tarkov RSS Feed</title></channel></rss>",
                    b'<!DOCTYPE rss><rss/>'):
            with self.assertRaises(ValueError):
                parse_feed(raw)

    def test_untrusted_images_are_not_embedded(self):
        item = parse_feed(XML.replace(b"clan.akamai.steamstatic.com", b"example.invalid"))[0]
        self.assertNotIn("image", message_for(item)["embeds"][0])

    def test_burst_limit(self):
        items = [dict(self.items[0], id=URL + str(i)) for i in range(9)]
        state, count = process(items, {"version": 1, "stories": {}}, self.save, self.sent.append)
        self.assertEqual(count, 5)
        state, count = process(items, state, self.save, self.sent.append)
        self.assertEqual(count, 4)

    def test_long_titles_are_bounded(self):
        self.items[0]["title"] = "x" * 1000
        self.assertEqual(len(message_for(self.items[0])["embeds"][0]["title"]), 256)


if __name__ == "__main__":
    unittest.main()
