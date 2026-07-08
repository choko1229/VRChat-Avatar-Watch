# 実装状況

## 実装済み

- FastAPI + Jinja2 + HTMX 構成
- `.env` は `WEB_PORT` のみ
- SQLite bootstrap と MySQL セットアップ保存
- 要件指定のDBテーブル
- 初期アバター、表記ゆれ、初期ツール
- Discord OAuth 導線、ユーザー保存、管理者判定
- 公開ページ: `/`, `/search`, `/items/{id}`, `/avatars/{slug}`, `/sales`, `/free`, `/tools`, `/me`
- 管理画面: 商品、アバター、ツール、ショップ、キーワード、クロール、ログ、ユーザー、設定
- 管理画面からの商品手動登録、商品編集、手動アバター補正、除外固定、理由メモ
- 管理画面からのツール編集、ショップ監視/除外設定、通知系Secret更新
- BOOTH公開HTML取得の低負荷クロール下地
- JSON-LD/OGメタ情報を使うBOOTH商品詳細パーサー
- 最小再取得間隔、強制再取得、HTML貼り付けパース検証
- BOOTHドメイン限定のクロール対象検証
- 保存しないクロールドライラン
- Pterodactyl向け起動スクリプトとポートfallback
- アバター判定、ツール判定、セール判定、無料判定、NSFW判定
- 価格履歴、ランキングメトリクス、通知・ウォッチ系DB下地
- HTMX検索部分更新
- NSFW画像ぼかしと表示ボタン

## 下地のみ

- お気に入り
- アバターウォッチ
- ショップウォッチ
- ユーザー通知設定
- Misskey投稿
- Discord Webhook通知
- ランキング算出
- サムネイル容量管理の自動削除
- 商品削除、ツール削除、ショップ削除

## 未検証

- 実BOOTHページのHTMLパース精度
- 実Discord OAuth callback
- 実MySQL接続
- Pterodactyl上での長時間運用
- Pterodactyl実機での起動、割当ポート、再起動後の設定維持
