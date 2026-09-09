# YouTube → X 自動通知（config.json設定版）

設定変更を `config.json` にまとめた版です。

## 普段変更するファイル

`config.json` だけを編集します。

```json
{
  "check_interval_minutes": 10,
  "normal_post_template": "🎮 新しい動画を公開しました！\n\n{title}\n\n▶ YouTube\n{url}",
  "live_post_template": "🔴 ライブ配信を開始しました！\n\n{title}\n\n▶ YouTube Live\n{url}",
  "hashtags": "#信長の野望 #ゲーム実況"
}
```

### check_interval_minutes
`5 / 10 / 15 / 20 / 30 / 60` のいずれか。

GitHub Actions自体は5分ごとに起動し、config.json の設定に該当する回だけYouTubeを確認します。
手動の「Run workflow」は間隔に関係なく必ず確認します。

### normal_post_template
通常動画のX投稿文。`{title}` と `{url}` は残してください。

### live_post_template
ライブ開始時のX投稿文。`{title}` と `{url}` は残してください。

### hashtags
投稿末尾につけるハッシュタグ。不要なら空文字 `""` にします。

## APIキーなど
機密情報は config.json に入れません。引き続き GitHub Repository secrets で管理します。

- YOUTUBE_API_KEY
- YOUTUBE_CHANNEL_ID
- X_API_KEY
- X_API_SECRET
- X_ACCESS_TOKEN
- X_ACCESS_TOKEN_SECRET

## GitHub上で設定変更する方法

Code → `config.json` → 鉛筆アイコン → 値を変更 → Commit changes

通常の設定変更では `main.py`、`state.json`、`.github/workflows/youtube-to-x.yml` を触る必要はありません。

## 既存リポジトリへの更新

このZIPの中身を既存の `youtube-to-x` リポジトリへ上書きしてください。
特に以下を更新・追加します。

- `main.py`（更新）
- `.github/workflows/youtube-to-x.yml`（更新）
- `config.json`（新規）
- `README.md`（更新）

`state.json` は現在運用中のものを残すのが安全です。既存の通知済み履歴を消さないため、運用中リポジトリの `state.json` は上書きしないでください。
