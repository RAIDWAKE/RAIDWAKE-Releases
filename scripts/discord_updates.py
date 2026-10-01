"""Announce public RAIDWAKE releases. Manual runs send a connection check only."""

import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

REPOSITORY = "RAIDWAKE/RAIDWAKE-Releases"
RELEASES = f"https://github.com/{REPOSITORY}/releases"


def message_for(event, event_name, attempt="1"):
    repository = event.get("repository", {})
    if repository.get("full_name") != REPOSITORY or repository.get("private") is not False:
        return None
    if event_name == "workflow_dispatch":
        return {
            "username": "RAIDWAKE Updates",
            "allowed_mentions": {"parse": []},
            "content": "Update feed connected. Published RAIDWAKE releases will appear here. "
                       "This is a connection check, not a game update.",
        }
    release = event.get("release", {})
    if (event_name != "release" or event.get("action") != "published"
            or release.get("draft") is not False or not release.get("published_at")
            or attempt != "1"):
        return None
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError("Published release has no tag.")
    notes = release.get("body") or "Release details are available on GitHub."
    if not isinstance(notes, str):
        raise ValueError("Release notes must be text.")
    if len(notes) > 3500:
        notes = notes[:3450].rstrip() + "\n\nContinue reading on GitHub."
    return {
        "username": "RAIDWAKE Updates",
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": (release.get("name") or f"RAIDWAKE {tag}")[:240],
            "url": f"{RELEASES}/tag/{quote(tag, safe='')}",
            "description": notes,
            "color": 0xC79843,
            "footer": {"text": "RAIDWAKE · Alpha / prerelease" if release.get("prerelease")
                       else "RAIDWAKE · Release"},
        }],
    }


def webhook_endpoint(value):
    # Webhook URLs are credentials. Reject lookalike hosts, redirects and query overrides.
    if not re.fullmatch(r"https://discord\.com/api(?:/v10)?/webhooks/[0-9]+/[A-Za-z0-9_-]+", value):
        raise ValueError("Configure a valid Discord channel webhook in DISCORD_UPDATES_WEBHOOK.")
    return value + "?wait=true"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def deliver(webhook, message, opener=None):
    request = Request(webhook_endpoint(webhook), data=json.dumps(message).encode("utf-8"),
                      headers={"Content-Type": "application/json", "User-Agent": "RAIDWAKE-Updates/1.0"},
                      method="POST")
    opener = opener or build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            received = json.loads(response.read(65536))
            if response.status != 200 or not received.get("id"):
                raise ValueError("Discord did not confirm a saved message.")
    except HTTPError as error:
        # Never print exceptions containing the secret-bearing request URL or body.
        raise RuntimeError(f"Discord rejected the notification (HTTP {error.code}). Check the channel before retrying.") from None
    except (URLError, OSError, ValueError):
        # Do not blindly retry a POST whose delivery outcome might be unknown.
        raise RuntimeError("Discord delivery was not confirmed. Check the channel before retrying.") from None


def main():
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        message = message_for(event, os.environ.get("GITHUB_EVENT_NAME"), os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
        if message is None:
            print("No announcement: unpublished, private, unrelated or repeated event.")
            return 0
        deliver(os.environ.get("DISCORD_UPDATES_WEBHOOK", ""), message)
        print("Discord confirmed the notification.")
        return 0
    except (KeyError, ValueError, OSError, RuntimeError) as error:
        # Parsing/IO errors can contain event paths; only expose our own safe messages.
        if isinstance(error, RuntimeError):
            print(str(error), file=sys.stderr)
        else:
            print("Notification configuration is incomplete or invalid. Check the event and webhook secret.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
