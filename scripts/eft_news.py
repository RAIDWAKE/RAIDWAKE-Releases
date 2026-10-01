"""Forward new official EFT Steam announcements, with durable duplicate tracking."""
import base64
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler

from discord_updates import NoRedirect, deliver, REPOSITORY

FEED = "https://steamcommunity.com/games/3932890/rss/"
SOURCE = "https://steamcommunity.com/app/3932890/announcements/"
BRANCH = "eft-news-state"
STATE_PATH = "eft-news-state.json"
OPENER = build_opener(ProxyHandler({}), NoRedirect())


class ArticleImages(HTMLParser):
    def __init__(self):
        super().__init__()
        self.image = None

    def handle_starttag(self, tag, attrs):
        src = dict(attrs).get("src", "")
        if tag == "img" and not self.image and re.fullmatch(
                r"https://clan\.(?:akamai|fastly)\.steamstatic\.com/images/[A-Za-z0-9/_.-]+", src):
            self.image = src


def parse_feed(raw):
    if len(raw) > 2_000_000 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Invalid feed document.")
    channel = ET.fromstring(raw).find("channel")
    if channel is None or channel.findtext("title") != "Escape from Tarkov RSS Feed":
        raise ValueError("Unexpected feed source.")
    items = []
    seen = set()
    for node in channel.findall("item"):
        url = node.findtext("link", "")
        if not re.fullmatch(r"https://steamcommunity\.com/games/3932890/announcements/detail/[0-9]+", url):
            raise ValueError("Unexpected announcement link.")
        title = " ".join(node.findtext("title", "").split())
        if not title:
            raise ValueError("Announcement title missing.")
        date = parsedate_to_datetime(node.findtext("pubDate", ""))
        if date.tzinfo is None:
            raise ValueError("Announcement date has no timezone.")
        parser = ArticleImages()
        parser.feed(node.findtext("description", ""))
        if url not in seen:
            items.append({"id": url, "title": title, "date": date.astimezone(timezone.utc).isoformat(), "image": parser.image})
            seen.add(url)
    if not items:
        raise ValueError("Empty feed; preserving existing tracking state.")
    return sorted(items, key=lambda item: (item["date"], item["id"]))


def message_for(item):
    embed = {"title": item["title"][:256], "url": item["id"], "color": 0x8B9272,
             "description": f"[Read the official announcement]({item['id']})",
             "timestamp": item["date"],
             "footer": {"text": "Escape from Tarkov • Official Steam news"}}
    if item.get("image"):
        embed["image"] = {"url": item["image"]}
    return {"username": "RAIDWAKE • EFT News", "allowed_mentions": {"parse": []}, "embeds": [embed]}


def process(items, state, save, send):
    # Existing stories are a baseline, not a backlog to dump into the channel.
    if state is None:
        state = {"version": 1, "stories": {i["id"]: "baseline" for i in items}}
        save(state)
        return state, 0
    if state.get("version") != 1 or not isinstance(state.get("stories"), dict):
        raise ValueError("Invalid tracking state; manual repair required.")
    if "pending" in state["stories"].values():
        raise RuntimeError("A previous delivery is unconfirmed. Check Discord and resolve its pending state before resuming; no automatic duplicate sent.")
    posted = 0
    for item in items:
        if item["id"] in state["stories"]:
            continue
        if posted == 5:
            break  # Drain a burst over successive checks without flooding the channel.
        state["stories"][item["id"]] = "pending"
        save(state)  # Claim durably BEFORE posting; uncertain outcomes require inspection.
        send(message_for(item))
        state["stories"][item["id"]] = "posted"
        save(state)
        posted += 1
    return state, posted


class GitHubState:
    def __init__(self, token):
        self.token = token
        self.sha = None

    def request(self, method, path, data=None, allow_missing=False):
        request = Request(f"https://api.github.com/repos/{REPOSITORY}/" + path,
            data=None if data is None else json.dumps(data).encode(), method=method,
            headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "RAIDWAKE-EFT-News/1.0"})
        try:
            with OPENER.open(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code == 404 and allow_missing:
                return None
            raise RuntimeError(f"Tracking state request failed (HTTP {error.code}). No credential details logged.") from None
        except (URLError, OSError, ValueError):
            raise RuntimeError("Tracking state could not be confirmed; stopping before further posts.") from None

    def load(self):
        branch = self.request("GET", "git/ref/heads/" + BRANCH, allow_missing=True)
        if branch is None:
            main = self.request("GET", "git/ref/heads/main")
            self.request("POST", "git/refs", {"ref": "refs/heads/" + BRANCH, "sha": main["object"]["sha"]})
        result = self.request("GET", f"contents/{STATE_PATH}?ref={BRANCH}", allow_missing=True)
        if result is None:
            return None
        self.sha = result["sha"]
        return json.loads(base64.b64decode(result["content"]))

    def save(self, value):
        data = {"message": "Record official EFT feed delivery state", "branch": BRANCH,
                "content": base64.b64encode(json.dumps(value, indent=2).encode()).decode()}
        if self.sha:
            data["sha"] = self.sha
        result = self.request("PUT", f"contents/{STATE_PATH}", data)
        self.sha = result["content"]["sha"]


def main():
    try:
        if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
            raise ValueError("Wrong repository.")
        token = os.environ["GITHUB_TOKEN"]
        webhook = os.environ["DISCORD_EFT_WEBHOOK"]
        if not token or not webhook:
            raise ValueError("Missing credentials.")
        with OPENER.open(Request(FEED, headers={"User-Agent": "RAIDWAKE-EFT-News/1.0"}), timeout=30) as response:
            items = parse_feed(response.read(2_000_001))
        store = GitHubState(token)
        state, count = process(items, store.load(), store.save, lambda message: deliver(webhook, message))
        if os.environ.get("CONNECTION_CHECK") == "true" and not state.get("connection_check"):
            state["connection_check"] = "pending"
            store.save(state)
            deliver(webhook, {"username": "RAIDWAKE • EFT News", "allowed_mentions": {"parse": []}, "embeds": [{
                "title": "EFT news feed connected", "color": 0x8B9272,
                "description": f"New [official Tarkov announcements]({SOURCE}) will appear here.\n\nBSG news only—RAIDWAKE releases stay in the release-updates channel.",
                "footer": {"text": "Connection check • Not a game update"}}]})
            state["connection_check"] = "posted"
            store.save(state)
        print(f"Official feed checked: {len(items)} stories available, {count} new announcements posted.")
        return 0
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (KeyError, OSError, ValueError, ET.ParseError, TypeError):
        print("Official feed or configuration is unavailable/invalid. No guessed announcements or unsafe retries.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
