import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

STATE_FILE = Path("state.json")
CONFIG_FILE = Path("config.json")
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
NTFY_BASE = "https://ntfy.sh"


def require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


def load_config():
    defaults = {
        "check_interval_minutes": 10,
        "normal_post_template": "🎮 新しい動画を公開しました！\n\n{title}\n\n▶ YouTube\n{url}",
        "live_post_template": "🔴 ライブ配信を開始しました！\n\n{title}\n\n▶ YouTube Live\n{url}",
        "hashtags": "",
        "normal_notification_title": "YouTube新着動画",
        "live_notification_title": "YouTubeライブ開始",
    }
    if not CONFIG_FILE.exists():
        return defaults

    data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    defaults.update(data)

    interval = int(defaults["check_interval_minutes"])
    if interval not in (5, 10, 15, 20, 30, 60):
        raise RuntimeError(
            "check_interval_minutes must be one of: 5, 10, 15, 20, 30, 60"
        )
    defaults["check_interval_minutes"] = interval
    return defaults


def scheduled_time_to_check(interval_minutes: int) -> bool:
    if os.getenv("GITHUB_EVENT_NAME", "") == "workflow_dispatch":
        return True

    now = datetime.now(timezone.utc)
    minute_of_hour = now.minute
    if interval_minutes == 60:
        return minute_of_hour < 5
    return minute_of_hour % interval_minutes < 5


def load_state():
    if not STATE_FILE.exists():
        return {"initialized": False, "notified_ids": []}

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    if "last_video_id" in data and "notified_ids" not in data:
        old = data.get("last_video_id")
        data = {
            "initialized": bool(old),
            "notified_ids": [old] if old else [],
        }

    data.setdefault("initialized", False)
    data.setdefault("notified_ids", [])
    return data


def save_state(state):
    state["notified_ids"] = list(
        dict.fromkeys(state.get("notified_ids", []))
    )[-200:]
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def youtube_get(path: str, api_key: str, **params):
    params["key"] = api_key
    r = requests.get(f"{YOUTUBE_API}/{path}", params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"YouTube API error {r.status_code}: {r.text}")
    return r.json()


def uploads_playlist_id(channel_id: str, api_key: str) -> str:
    data = youtube_get(
        "channels",
        api_key,
        part="contentDetails",
        id=channel_id,
        maxResults=1,
    )
    items = data.get("items", [])
    if not items:
        raise RuntimeError("YouTube channel not found.")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def fetch_recent_videos(channel_id: str, api_key: str):
    playlist_id = uploads_playlist_id(channel_id, api_key)

    playlist = youtube_get(
        "playlistItems",
        api_key,
        part="snippet,contentDetails",
        playlistId=playlist_id,
        maxResults=10,
    )

    ids = []
    playlist_meta = {}
    for item in playlist.get("items", []):
        video_id = item.get("contentDetails", {}).get("videoId")
        if not video_id:
            continue
        ids.append(video_id)
        snippet = item.get("snippet", {})
        playlist_meta[video_id] = {
            "title": snippet.get("title", ""),
            "publishedAt": snippet.get("publishedAt", ""),
        }

    if not ids:
        return []

    videos = youtube_get(
        "videos",
        api_key,
        part="snippet,liveStreamingDetails",
        id=",".join(ids),
        maxResults=10,
    )

    by_id = {}
    for item in videos.get("items", []):
        snippet = item.get("snippet", {})
        video_id = item["id"]
        by_id[video_id] = {
            "id": video_id,
            "title": snippet.get("title")
            or playlist_meta.get(video_id, {}).get("title", ""),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "live_status": snippet.get("liveBroadcastContent", "none"),
            "publishedAt": snippet.get("publishedAt")
            or playlist_meta.get(video_id, {}).get("publishedAt", ""),
            "actualStartTime": item.get(
                "liveStreamingDetails", {}
            ).get("actualStartTime"),
        }

    return [by_id[v] for v in ids if v in by_id]


def render_post(template: str, video, hashtags: str):
    text = template.format(title=video["title"], url=video["url"])
    if hashtags:
        text = f"{text}\n\n{hashtags}"
    return text


def build_video_post(video, config):
    return render_post(
        config["normal_post_template"],
        video,
        config.get("hashtags", "").strip(),
    )


def build_live_post(video, config):
    return render_post(
        config["live_post_template"],
        video,
        config.get("hashtags", "").strip(),
    )


def build_x_intent_url(text: str) -> str:
    return "https://x.com/intent/tweet?" + urlencode({"text": text})


def send_iphone_notification(title: str, message: str, x_text: str):
    topic = require("NTFY_TOPIC")
    click_url = build_x_intent_url(x_text)

    payload = {
        "topic": topic,
        "title": title,
        "message": message,
        "priority": 4,
        "tags": ["bell"],
        "click": click_url,
        "actions": [
            {
                "action": "view",
                "label": "Xに投稿",
                "url": click_url,
                "clear": True,
            },
            {
                "action": "view",
                "label": "YouTubeを開く",
                "url": message.splitlines()[-1],
                "clear": False,
            },
        ],
    }

    r = requests.post(NTFY_BASE, json=payload, timeout=30)
    if not r.ok:
        raise RuntimeError(f"ntfy error {r.status_code}: {r.text}")

    print("iPhone notification sent.")


def notify_video(video, config, is_live: bool):
    if is_live:
        x_text = build_live_post(video, config)
        title = config["live_notification_title"]
        message = f"🔴 {video['title']}\nタップするとX投稿画面が開きます。\n{video['url']}"
    else:
        x_text = build_video_post(video, config)
        title = config["normal_notification_title"]
        message = f"🎮 {video['title']}\nタップするとX投稿画面が開きます。\n{video['url']}"

    send_iphone_notification(title, message, x_text)


def send_test_notification(config):
    test_url = "https://www.youtube.com/"
    test_video = {
        "title": "通知テスト",
        "url": test_url,
    }
    x_text = build_video_post(test_video, config)
    message = (
        "✅ iPhone通知テストです。\n"
        "『Xに投稿』を押すと投稿画面が開きます。\n"
        f"{test_url}"
    )
    send_iphone_notification("YouTube通知テスト", message, x_text)
    print("Test notification completed.")


def main():
    config = load_config()
    require("NTFY_TOPIC")

    if os.getenv("TEST_NOTIFICATION", "false").strip().lower() == "true":
        send_test_notification(config)
        return 0

    channel_id = require("YOUTUBE_CHANNEL_ID")
    youtube_api_key = require("YOUTUBE_API_KEY")

    if not scheduled_time_to_check(config["check_interval_minutes"]):
        print(
            f"Skip: configured interval is "
            f"{config['check_interval_minutes']} minutes."
        )
        return 0

    videos = fetch_recent_videos(channel_id, youtube_api_key)
    if not videos:
        print("No recent videos found.")
        return 0

    state = load_state()
    notified = set(state.get("notified_ids", []))

    if not state.get("initialized"):
        for video in videos:
            if video["live_status"] != "upcoming":
                notified.add(video["id"])
        state["initialized"] = True
        state["notified_ids"] = list(notified)
        save_state(state)
        print("First run: state initialized. No notification was sent.")
        return 0

    for video in reversed(videos):
        video_id = video["id"]
        status = video["live_status"]

        if video_id in notified:
            continue

        if status == "upcoming":
            print(f"Upcoming live detected, waiting for start: {video['title']}")
            continue

        if status == "live":
            print(f"Live started: {video['title']}")
            notify_video(video, config, is_live=True)
            notified.add(video_id)
            continue

        print(f"New video: {video['title']}")
        notify_video(video, config, is_live=False)
        notified.add(video_id)

    state["notified_ids"] = list(notified)
    save_state(state)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
