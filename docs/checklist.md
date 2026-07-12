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

## 2026-07-13 Claude Codeによる本番確認で判明した不具合と修正

本番 `https://vrc-aw.choko1229.net/` をブラウザで確認したところ、既に定期クロールワーカーが稼働しアイテム/アバターが多数登録済みだった。一方 `/admin/crawl` のログに以下の実エラーが記録されていた:

- `IntegrityError (1062, "Duplicate entry '... ' for key 'uq_item_avatar'")` — アバター自動判定のバルクINSERTで同一 `(item_id, avatar_id)` を重複投入
- `IntegrityError (1062, "Duplicate entry '...' for key 'ix_items_booth_item_id'")` — 同一BOOTH商品を重複INSERT
- `OperationalError` デッドロック / ロック待機タイムアウト

原因: `/admin/crawl` の「実行」ボタンは毎回 `threading.Thread` で新しいDBセッションのクロールを起動しており、定期ワーカー(`crawl_active_targets_once`)や他の手動クロールと**同時に**itemsテーブルへ書き込むと競合していた。さらに例外処理が `self.db.rollback()` を呼ばずにセッションを使い続けていたため、本来のエラー理由が握りつぶされ `crawl_logs.message` に "Session's transaction has been rolled back..." という二次エラーだけが残り、スケジューラのバッチ内で後続ターゲットのクロールも巻き添えで失敗しうる状態だった。

修正 ([app/crawler/booth.py](../app/crawler/booth.py)):
- プロセス全体で共有する `threading.Lock` で `crawl_target` の書き込み区間を直列化し、同時書き込みによる重複キー/デッドロックを解消
- 例外処理の先頭で `self.db.rollback()` を呼び、セッションを健全な状態に戻してからエラーログを記録するよう修正

`uv run pytest`(50 passed)と `uv run python -m compileall app scripts tests` を確認後、コミット `46b08ba` として `main` にプッシュ済み(自動デプロイ設定によりPterodactylへ反映される想定)。

## MVP残件

- [x] Discord OAuth callbackで実ログイン確認 — ブラウザで `choko1229` として実ログインし `/admin` にアクセスできることを確認(Discord ID `541956588374589440` が管理者)
- [x] Pterodactyl上でPTクロール定期ワーカーが稼働していることを確認 — `/admin` ダッシュボードに直近の `success` クロールログが複数あり、商品4947件・アバター285件が蓄積済み
- [x] 管理者ログイン後 `/admin/crawl` の画面・ログを確認 — 保存クロールが実際に動作していることをログで確認。ただし上記の重複キー/デッドロックの実エラーを発見し修正した
- [ ] 上記修正がPterodactylに反映されたことを確認(`git log -1` が `46b08ba` 以降になっているか)
- [ ] 修正後、しばらく運用して `crawl_logs` に重複キー/デッドロックエラーが再発しないことを確認
- [ ] Pterodactyl/Linux上で `scripts/booth_ops_check.py --keyword キプフェル` を実行(SSH/コンソールアクセスが必要)
- [ ] Pterodactyl/Linux上で `scripts/booth_ops_check.py --keyword キプフェル --save` を1回だけ実行
- [ ] 即時再クロールが `skipped` になることを確認
- [ ] 管理者ログイン後 `/admin/crawl` で保存せず確認/対象削除の実操作を確認(ボタン操作はブラウザ自動操作ツールの不安定さで未確定 — 目視確認推奨)
- [ ] 管理者ログイン後 `/admin/avatars` で情報再取得/削除/再判定を確認(同上)
- [ ] Discord Webhookを設定して実送信確認
- [ ] Misskeyを使う場合はtoken設定後に実投稿確認
- [ ] Pterodactyl再起動後にDB接続、設定、スケジューラ継続を確認
