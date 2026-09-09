# YouTube → X 自動通知（10分間隔・ライブ配信対応）

YouTubeチャンネルを10分ごとに確認し、通常動画の公開またはライブ配信の開始を検出したときにXへ1回だけ投稿します。

## 今回の更新内容

- 確認間隔：15分 → **10分**
- 通常動画：公開時にXへ投稿
- ライブ配信：**予約時ではなく、実際に配信が始まった時にXへ投稿**
- upcoming（配信予約中）は投稿しない
- 同じ動画・ライブは再投稿しない
- ライブ終了後に通常動画として二重投稿しない
- 初回実行では過去動画を誤投稿しない

## YouTube APIについて

ライブ状態を正確に判定するため、YouTube Data API v3を使用します。

GitHub Secretsへ以下を追加してください。

- `YOUTUBE_CHANNEL_ID`
- `YOUTUBE_API_KEY`
- `X_API_KEY`
- `X_API_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`

YouTube APIキーはGoogle Cloud ConsoleでYouTube Data API v3を有効にして発行します。

この版は1回の確認につき主に以下を使用します。

- channels.list：1ユニット
- playlistItems.list：1ユニット
- videos.list：1ユニット

10分ごとなら概算432ユニット/日程度です。YouTube Data APIの標準クォータは通常10,000ユニット/日です。

## Xの投稿文

通常動画の既定文：

```text
🎮 新しい動画を公開しました！

{title}

▶ YouTube
{url}
```

ライブ配信の既定文：

```text
🔴 ライブ配信を開始しました！

{title}

▶ YouTube Live
{url}
```

GitHubの
`Settings → Secrets and variables → Actions → Variables`
から変更できます。

### `POST_TEMPLATE`

通常動画用。

### `LIVE_POST_TEMPLATE`

ライブ配信用。

### `HASHTAGS`

共通ハッシュタグ。例：

```text
#信長の野望 #信長の野望新生PK
```

## 初回実行

`Actions → YouTube to X → Run workflow`

初回はX投稿を行わず、現在の動画を基準として記録します。

ただし予約中のライブ（upcoming）は通知済みにしません。
そのため後で配信が始まると、次回の10分チェック時にライブ通知されます。

## Xへ投稿せずテスト

`.github/workflows/youtube-to-x.yml` の

```yaml
MODE: post
```

を

```yaml
MODE: dry-run
```

に変更してください。

## 注意

GitHub Actionsのscheduled workflowは10分間隔で設定しますが、GitHub側の混雑などで実際の開始が遅れることがあります。

X API側の投稿料金・仕様は変更される可能性があります。
