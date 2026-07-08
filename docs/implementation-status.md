# 実装状況

## 完了

- FastAPI + Jinja2 + HTMX 構成
- `.env` 最小化と `/setup` DB保存
- Discord OAuth基盤、ユーザー/管理者DB
- BOOTH公開ページクロール、詳細補完、robots確認
- VRC一括クロール、保存せず確認、保存クロール、リアルタイム状態表示
- クロール対象削除
- アバター自動作成、アバター一覧/詳細、アバター管理の再取得/削除
- 削除後の商品再判定
- 商品/ツール/ショップ削除
- 商品説明の閲覧時取得
- お気に入り、アバター監視、ショップ監視、通知設定
- Discord Webhook/Misskeyの未送信通知配送処理
- ランキング集計
- サムネイルキャッシュ容量管理
- 定期クロールワーカー
- Pterodactyl起動スクリプト

## 実環境で要確認

- Discord OAuth callback
- Discord Webhook実送信
- Misskey実投稿
- 長時間クロール運用
- Pterodactyl再起動後のDB接続とスケジューラ継続
