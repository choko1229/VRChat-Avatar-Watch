# VRChat Avatar Watch

BOOTH上の公開VRChat関連商品を低頻度で取得し、アバター対応商品、ツール、衣装、ギミック、セール、無料配布を整理する FastAPI + Jinja2 + HTMX アプリです。

## 主な機能

- 公開画面: 新着、検索、アバター一覧/詳細、商品詳細、セール、無料、ツール、プロフィール
- BOOTHクロール: 公開ページのみ取得、robots確認、低頻度、最小再取得間隔、詳細ページ補完
- 自動分類: アバター、ツール、セール、無料、NSFW、価格履歴
- 管理画面: 商品/アバター/ツール/ショップ/クロール対象/ログ/ユーザー/設定
- アバター管理: 情報再取得、削除、削除後の商品再判定
- クロール管理: 保存せず確認、保存クロール、リアルタイム状態、クロール対象削除
- 通知/ウォッチ: お気に入り、アバター監視、ショップ監視、ユーザー通知設定、Discord Webhook/Misskey送信
- 運用: Pterodactyl起動、定期クロール、ランキング集計、サムネイルキャッシュ整理

## 起動

`.env` は原則 `WEB_PORT` のみです。

```env
WEB_PORT=49175
```

ローカル:

```powershell
uv venv --python 3.12
uv pip install -r requirements.txt
uv run python main.py
```

Pterodactyl:

```bash
sh scripts/pterodactyl-start.sh
```

直接起動する場合:

```bash
UV_CACHE_DIR=.local/uv-cache uv run python main.py
```

`WEB_PORT` が未設定の場合は `SERVER_PORT` または `PORT` を参照します。

## 初期セットアップ

セットアップ未完了時は `/setup` が自動表示されます。入力順は次の通りです。

1. ウェブ管理系情報
2. DiscordAuth
3. 管理者について

MySQL接続とテーブル作成に成功した場合のみセットアップ完了になります。Discord Client Secret などのSecret値はDBの `settings` に保存され、管理画面ではマスク表示されます。

## 実環境確認

```bash
UV_CACHE_DIR=.local/uv-cache uv run python scripts/production_smoke_check.py https://vrc-aw.choko1229.net
UV_CACHE_DIR=.local/uv-cache uv run python scripts/booth_ops_check.py --keyword キプフェル
UV_CACHE_DIR=.local/uv-cache uv run python scripts/booth_ops_check.py --keyword キプフェル --save
```

確認対象:

- `/api/health` が200を返す
- ヘッダーから `/avatars` に移動できる
- `/admin/crawl` で対象の保存せず確認、保存クロール、削除が動く
- `/admin/avatars` で情報再取得、削除、削除後再判定が動く
- 403 / 429 / 5xx / robots拒否時に `error_logs` に理由が残る
- 短時間再クロールが `skipped` になる

## クロール方針

- BOOTH公開ページのみ取得します。
- ログイン後情報、購入、ダウンロードは行いません。
- 同時HTTPアクセスは1です。
- 取得ページ数と詳細補完件数は管理画面で調整できます。
- クロール中にサーバー再起動した場合、残った `queued` / `running` ログは起動時に `interrupted` へ更新されます。
