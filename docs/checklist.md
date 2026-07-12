# MVPチェックリスト

## 完了

- [x] `uv run pytest`
- [x] `uv run python -m compileall app scripts tests`
- [x] Jinjaテンプレート構文確認
- [x] `/api/health` が本番で200
- [x] `/` が本番で200
- [x] `/avatars` が本番で200
- [x] `/search` が本番で200
- [x] `/sales` が本番で200
- [x] `/free` が本番で200
- [x] `/tools` が本番で200
- [x] `/setup` が完了後に `/` へ戻る
- [x] `/admin` が未ログインで401
- [x] `/login` がDiscord OAuthへ遷移
- [x] 商品/アバター/ツール/ショップ/クロール対象の管理UI
- [x] 商品/アバター/ツール/ショップ/クロール対象の削除処理
- [x] VRC一括クロールの保存せず確認/保存クロール/リアルタイム状態表示
- [x] アバター情報再取得
- [x] アバター削除後の商品再判定
- [x] 商品説明の閲覧時取得
- [x] お気に入り/アバター監視/ショップ監視/通知設定
- [x] Discord Webhook/Misskey送信処理
- [x] ランキング集計
- [x] サムネイルキャッシュ整理
- [x] 定期クロールワーカー
- [x] Pterodactyl起動スクリプト

## MVP残件

- [ ] Pterodactyl上で最新コミット `6aa0871` が反映されていることを確認
- [ ] Pterodactyl/Linux上で `scripts/booth_ops_check.py --keyword キプフェル` を実行
- [ ] Pterodactyl/Linux上で `scripts/booth_ops_check.py --keyword キプフェル --save` を1回だけ実行
- [ ] 即時再クロールが `skipped` になることを確認
- [ ] 管理者ログイン後 `/admin/crawl` で対象削除を確認
- [ ] 管理者ログイン後 `/admin/avatars` で情報再取得/削除/再判定を確認
- [ ] Discord OAuth callbackで実ログイン確認
- [ ] Discord Webhookを設定して実送信確認
- [ ] Misskeyを使う場合はtoken設定後に実投稿確認
- [ ] Pterodactyl再起動後にDB接続、設定、スケジューラ継続を確認
