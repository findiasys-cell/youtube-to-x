import json
import os
import sys
from pathlib import Path

import requests
from requests_oauthlib import OAuth1

STATE_FILE = Path("state.json")
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"


def require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


def load_state():
    if not STATE_FILE.exists():
        return {"initialized": False, "notified_ids": []}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    # 旧版state.jsonからの移行
    if "last_video_id" in data and "notified_ids" not in data:
        old = data.get("last_video_id")
        data = {
            "initialized": bool(old),
            "notified_ids": [old] if old else []
        }

    data.setdefault("initialized", False)
    data.setdefault("notified_ids", [])
    return data


def save_state(state):
    # state.json肥大化防止
    state["notified_ids"] = list(dict.fromkeys(state.get("notified_ids", [])))[-200:]
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
            "title": snippet.get("title") or playlist_meta.get(video_id, {}).get("title", ""),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "live_status": snippet.get("liveBroadcastContent", "none"),
            "publishedAt": snippet.get("publishedAt") or playlist_meta.get(video_id, {}).get("publishedAt", ""),
            "actualStartTime": item.get("liveStreamingDetails", {}).get("actualStartTime"),
        }

    # uploads playlistの順序を保持
    return [by_id[v] for v in ids if v in by_id]


def render_post(template_env: str, default_template: str, video, hashtags: str):
    template = os.getenv(template_env, "").strip() or default_template
    text = template.format(title=video["title"], url=video["url"])
    if hashtags:
        text = f"{text}\n\n{hashtags}"
    return text


def build_video_post(video, hashtags):
    return render_post(
        "POST_TEMPLATE",
        "🎮 新しい動画を公開しました！\n\n{title}\n\n▶ YouTube\n{url}",
        video,
        hashtags,
    )


def build_live_post(video, hashtags):
    return render_post(
        "LIVE_POST_TEMPLATE",
        "🔴 ライブ配信を開始しました！\n\n{title}\n\n▶ YouTube Live\n{url}",
        video,
        hashtags,
    )


def post_to_x(text: str):
    api_key = require("X_API_KEY")
    api_secret = require("X_API_SECRET")
    access_token = require("X_ACCESS_TOKEN")
    access_token_secret = require("X_ACCESS_TOKEN_SECRET")

    auth = OAuth1(api_key, api_secret, access_token, access_token_secret)
    r = requests.post(
        "https://api.x.com/2/tweets",
        auth=auth,
        json={"text": text},
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"X API error {r.status_code}: {r.text}")
    return r.json()


def send(text: str, mode: str):
    if mode == "dry-run":
        print("DRY RUN - would post:")
        print(text)
        return
    result = post_to_x(text)
    print("Posted to X:", json.dumps(result, ensure_ascii=False))


def main():
    channel_id = require("YOUTUBE_CHANNEL_ID")
    youtube_api_key = require("YOUTUBE_API_KEY")
    mode = os.getenv("MODE", "post").strip().lower()
    hashtags = os.getenv("HASHTAGS", "").strip()

    videos = fetch_recent_videos(channel_id, youtube_api_key)
    if not videos:
        print("No recent videos found.")
        return 0

    state = load_state()
    notified = set(state.get("notified_ids", []))

    # 初回は過去動画の誤投稿を防止。
    # ただし「upcoming」は通知済みにしないので、後でliveに変われば通知される。
    if not state.get("initialized"):
        for video in videos:
            if video["live_status"] != "upcoming":
                notified.add(video["id"])
        state["initialized"] = True
        state["notified_ids"] = list(notified)
        save_state(state)
        print("First run: state initialized. No X post was sent.")
        return 0

    # 古いものから順に処理し、短時間に複数公開された場合も順番に通知
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
            send(build_live_post(video, hashtags), mode)
            notified.add(video_id)
            continue

        # live終了後に通常動画として二重投稿されないよう、
        # live配信は実配信開始時にnotifiedへ入る。
        print(f"New video: {video['title']}")
        send(build_video_post(video, hashtags), mode)
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
