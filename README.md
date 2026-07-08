# VRChat Avatar Watch

BOOTH上の公開されているVRChat関連商品を低負荷で取得し、アバター別、セール、無料配布、ツール枠で探せる FastAPI + Jinja2 + HTMX 製のWebアプリです。

## 機能

- 商品一覧、商品詳細、検索、アバター別ページ
- セール中商品、無料配布商品、VRChat関連ツールの別枠表示
- Discord OAuthログインと管理者判定
- 初回セットアップ画面 `/setup`
- 管理画面 `/admin`
- BOOTH公開HTMLの低負荷クロール下地
- 価格履歴、NSFWぼかし表示、検索演算子
- 管理画面からの商品手動登録、商品編集、アバター対応補正
- お気に入り、ウォッチ、通知、ランキングのDB下地

## セットアップ

`.env` はポート番号のみです。

```env
WEB_PORT=49175
```

依存関係:

```powershell
uv venv --python 3.12
uv pip install -r requirements.txt
uv run python main.py
```

WindowsやPterodactylで `uv` の既定キャッシュにアクセスできない場合は、ワークスペース内キャッシュを使います。

```powershell
$env:UV_CACHE_DIR=".local\uv-cache"
uv run python main.py
```

起動後、`http://127.0.0.1:49175/setup` を開いてMySQLとDiscord OAuthを設定してください。

## Pterodactyl 起動

Startup command:

```bash
sh scripts/pterodactyl-start.sh
```

直接起動する場合:

```bash
UV_CACHE_DIR=.local/uv-cache uv run python main.py
```

Pterodactyl側の割り当てポートを `.env` の `WEB_PORT` に合わせます。`WEB_PORT` が未設定の場合は `SERVER_PORT` または `PORT` も自動で参照します。MySQL接続情報やDiscord Secretは `.env` に入れず、`/setup` で設定します。

運用確認項目は `docs/pterodactyl-ops-check.md` を参照してください。

## MySQL設定例

- host: `127.0.0.1`
- port: `3306`
- database: `vrchat_avatar_watch`
- user: `vrchat_avatar_watch`
- password: 任意

アプリは `/setup` 保存後に `data/runtime_config.json` を作成し、MySQLへ接続します。Secret値はDBの `settings` テーブルに保存されますが、管理画面では `configured` / `未設定` として表示します。

## Discord OAuth

Discord Developer PortalでOAuth2 Redirect URIに以下を登録します。

```txt
https://your-domain.example/auth/discord/callback
```

初回ログインユーザーは管理者として登録されます。`/setup` で管理者Discord IDを指定した場合、そのIDも管理者として登録されます。

## クロール方針

- BOOTHの公開情報のみ取得します。
- 購入、ダウンロード、ログイン後情報取得は実装しません。
- 同時アクセス数の初期値は1です。
- デフォルト取得間隔は6時間です。
- 403、429、5xxではクロールを止めるか待機します。
- 短時間の同一対象再取得を避けるため、最小再取得間隔を管理画面で設定できます。
- 管理画面のHTMLパース検証で、BOOTH公開HTMLを貼り付けて抽出結果を確認できます。
- `shop` / `url` 型のクロール対象は BOOTH ドメインのみ許可します。
- 保存前に「保存せず確認」ドライランで取得・抽出結果を確認できます。
- `robots.txt` を実行時に確認できない場合はクロールを失敗扱いにします。

BOOTHの公式規約とガイドラインは実装前に確認済みです。運用前にも最新内容を確認してください。

## 検索演算子

```txt
avatar:キプフェル
free:true
sale:true
shop:ショップ名
tool:true
tag:衣装
-r18
-対応外
```

## 管理画面

`/admin` から以下を確認できます。

- 商品管理
- アバター管理
- ツール管理
- ショップ管理
- キーワード・クロール対象管理
- 商品手動登録と編集
- 対応アバターの追加、除外、手動固定、理由メモ
- ツールキーワード編集
- ショップ監視/除外設定
- 手動クロール、再取得
- クロールログ、エラーログ
- ユーザー管理
- 設定管理

## MVP後回し

- 実通知送信
- Misskey投稿
- お気に入りUI
- アバターウォッチUI
- ショップウォッチUI
- ランキング算出
- サムネイルキャッシュ容量の自動清掃

DBと画面下地は用意済みです。

## トラブルシュート

- `/login` が失敗する: `/setup` のDiscord Client ID、Secret、Redirect URIを確認してください。
- `/admin` が403: ログインユーザーのDiscord IDが `admin_users` に登録されているか確認してください。
- MySQL接続に失敗する: host、port、database、user、password、権限を確認してください。
- BOOTHクロールが失敗する: 403、429、5xx、robots確認失敗時は意図的に停止します。時間を置いてから再実行してください。

## 手動確認

詳細は `docs/manual-test.md` と `docs/checklist.md` を参照してください。
