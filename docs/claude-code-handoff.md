# Claude Code引き継ぎ: VRChat Avatar Watch MVP残件

## 目的

VRChat Avatar Watch のMVPを本番運用可能な状態に仕上げる。コード実装は一通り完了しているため、残作業は主にPterodactyl/Linux本番環境での受け入れ確認、管理画面の実操作確認、外部通知の実送信確認。

## 現在の前提

- リポジトリ: `choko1229/VRChat-Avatar-Watch`
- 対象ブランチ: `main`
- ローカル最新確認済みコミット: `64eccce Refresh MVP checklist commit reference`
- 本番URL: `https://vrc-aw.choko1229.net/`
- ローカル作業ツリーはクリーンな状態で引き継ぎ

## 要件定義に対する実装済み項目

- BOOTH公開ページのみを低頻度で取得するクロール基盤
- VRC一括クロール
- 保存せず確認
- 保存クロール
- リアルタイムクロール状況表示
- クロール対象削除
- アバター自動作成
- アバター一覧/詳細
- ヘッダーからアバター一覧への導線
- アバター管理の情報再取得
- アバター削除
- アバター削除後の商品再判定
- 商品詳細の説明文を閲覧時に取得
- 商品/ツール/ショップ削除
- お気に入り、アバター監視、ショップ監視
- ユーザー通知設定
- Discord Webhook/Misskey送信処理
- ランキング集計
- サムネイルキャッシュ整理
- 定期クロールワーカー
- Pterodactyl起動スクリプト
- セットアップ自動表示とセットアップ順序整理
- README/docsの運用手順整理

## 直近で確認済み

- `uv run pytest` -> 50 passed
- `uv run python -m compileall app scripts tests` -> OK
- Jinjaテンプレート構文確認 -> OK
- 本番公開ページ:
  - `/api/health` -> 200
  - `/` -> 200
  - `/avatars` -> 200
  - `/search` -> 200
  - `/sales` -> 200
  - `/free` -> 200
  - `/tools` -> 200
- `/setup` -> 303で `/` へ戻る
- `/admin` -> 未ログインで401
- `/login` -> Discord OAuthへリダイレクト

## 不足/未確認チェックリスト

### Pterodactyl/Linux実環境

- [ ] Pterodactyl上で最新コミット `64eccce` 以降が反映されている
- [ ] `sh scripts/pterodactyl-start.sh` で起動できる
- [ ] Pterodactyl割当ポートと `WEB_PORT` が一致している
- [ ] `UV_CACHE_DIR=.local/uv-cache` で起動できる
- [ ] 再起動後もDB接続と設定が維持される
- [ ] 再起動後に定期クロールワーカーが継続する

### BOOTH実クロール

- [ ] Pterodactyl/Linux上でpreview確認を実行
  ```bash
  UV_CACHE_DIR=.local/uv-cache uv run python scripts/booth_ops_check.py --keyword キプフェル
  ```
- [ ] Pterodactyl/Linux上で保存クロールを1回だけ実行
  ```bash
  UV_CACHE_DIR=.local/uv-cache uv run python scripts/booth_ops_check.py --keyword キプフェル --save
  ```
- [ ] `items`, `price_histories`, `crawl_logs` が増える
- [ ] 即時再クロールが `skipped` になる
- [ ] 403 / 429 / 5xx / robots拒否時に `error_logs` に理由が残る

### 管理画面実操作

- [ ] 管理者でログインできる
- [ ] `/admin/crawl` で保存せず確認が動く
- [ ] `/admin/crawl` で保存クロールが動く
- [ ] `/admin/crawl` でクロール対象削除が動く
- [ ] `/admin/avatars` で情報再取得が動く
- [ ] `/admin/avatars` でアバター削除が動く
- [ ] アバター削除後、紐付いていた商品が残存アバター定義で再判定される
- [ ] 商品/ツール/ショップ削除が本番DBで動く

### 認証/通知

- [ ] Discord OAuth callbackで実ログインできる
- [ ] 初回ログインユーザーまたは設定済みDiscord IDが管理者になる
- [ ] `/me` で通知設定を保存できる
- [ ] Discord Webhook設定後に通知が実送信される
- [ ] Misskeyを使う場合、token設定後に実投稿される

## Claude Codeへの作業指示

以下をそのままClaude Codeに渡す。

```text
VRChat Avatar Watch のMVP残件を本番環境で潰してください。

前提:
- リポジトリ: choko1229/VRChat-Avatar-Watch
- ブランチ: main
- 本番URL: https://vrc-aw.choko1229.net/
- 最新コミット目安: 64eccce 以降
- コード実装は概ね完了済み。残りはPterodactyl/Linux本番での受け入れ確認と、そこで出た不具合修正です。

最初に確認すること:
1. Pterodactyl上で `git log -1 --oneline`
2. `sh scripts/pterodactyl-start.sh` または `UV_CACHE_DIR=.local/uv-cache uv run python main.py` で起動
3. `UV_CACHE_DIR=.local/uv-cache uv run python scripts/production_smoke_check.py https://vrc-aw.choko1229.net`
4. `UV_CACHE_DIR=.local/uv-cache uv run python scripts/booth_ops_check.py --keyword キプフェル`
5. 問題なければ `UV_CACHE_DIR=.local/uv-cache uv run python scripts/booth_ops_check.py --keyword キプフェル --save`

確認するMVP残件:
- Pterodactyl上で最新mainが反映されている
- BOOTH previewが動く
- 保存クロールが1回動く
- 即時再実行が skipped になる
- items, price_histories, crawl_logs が増える
- error_logs にエラー理由が残る
- 管理者ログイン後 /admin/crawl で保存せず確認/保存クロール/対象削除が動く
- 管理者ログイン後 /admin/avatars で情報再取得/削除/削除後再判定が動く
- Discord OAuth callbackで実ログインできる
- Discord Webhook/Misskey実送信が動く
- Pterodactyl再起動後にDB接続、設定、スケジューラが維持される

作業ルール:
- 完了済みの実装を大きく作り直さない
- 本番DBを触る操作は、削除や保存クロール前に対象を確認する
- BOOTHアクセスは公開ページのみ、低頻度、まずpreview優先
- 失敗ログ、HTTPステータス、DB件数を必ず記録する
- 修正したら `uv run pytest` と `uv run python -m compileall app scripts tests` を通す
- 修正後はコミット/プッシュする
```

## 注意

Windowsローカルでは `uv/httpx` が `OPENSSL_Applink` で止まることがある。BOOTH実クロールはPterodactyl/Linuxで確認すること。
