# 手動確認手順

1. `.env` を作成し、`WEB_PORT=49175` を設定する。
2. `uv venv --python 3.12` を実行する。
3. `uv pip install -r requirements.txt` を実行する。
4. `uv run python main.py` を起動する。
5. `http://127.0.0.1:49175/api/health` を開く。
6. セットアップ未完了状態で `/` を開くと `/setup` が自動表示されることを確認する。
7. `/setup` の入力順が `ウェブ管理系情報`、`DiscordAuth`、`管理者について` になっていることを確認する。
8. `/setup` で不正なMySQL情報を入力し、画面に接続失敗エラーが表示されることを確認する。
9. DiscordAuthを空にすると保存できないことを確認する。
10. `/setup` でMySQLとDiscord OAuth情報を登録し、成功時だけ `/login` へ進むことを確認する。
11. `/login` からDiscordログインし、`/me` にユーザー情報が出ることを確認する。
12. 管理者で `/admin` に入り、各管理ページが表示されることを確認する。
13. `/admin/items` で商品を手動登録し、編集画面に遷移することを確認する。
14. 商品編集画面で対応アバターを手動判定として固定し、理由メモが表示されることを確認する。
15. 同じ商品で対応アバターを除外扱いに変更できることを確認する。
16. `/admin/tools` でツールキーワードを追加または編集できることを確認する。
17. `/admin/shops` で監視/除外チェックを保存できることを確認する。
18. `/admin/settings` でSecret項目が変更時のみ入力になっており、一覧では平文表示されないことを確認する。
19. `/admin/keywords` で `keyword` として `キプフェル` を追加する。
20. `/admin/crawl` のHTMLパース検証に公開HTMLを貼り付け、抽出件数、価格未取得、画像未取得、説明未取得が表示されることを確認する。
21. `/admin/settings` で最小再取得間隔を設定できることを確認する。
22. `/admin/keywords` で `url` として `https://example.com` を追加しようとすると拒否されることを確認する。
23. `/admin/crawl` の「保存せず確認」でドライラン結果が表示されることを確認する。
24. `/admin/crawl` で再取得を押し、短時間の再取得が `skipped` になることを確認する。
25. 強制チェックを入れて再取得した場合、最小再取得間隔を無視することを確認する。
26. `/search` で以下を確認する。
    - `avatar:キプフェル`
    - `free:true`
    - `sale:true`
    - `shop:ショップ名`
    - `tool:true`
    - `tag:衣装`
    - `-r18`
    - `-対応外`
27. スマホ幅で `/`, `/search`, `/items/{id}`, `/avatars/{slug}` の崩れがないことを確認する。

## セキュリティ確認

- Secret値が `/admin/settings` に平文表示されない。
- 未ログインで `/admin` に入れない。
- 管理者以外で `/api/admin/health` が拒否される。
- POSTフォームにCSRF tokenがある。
- 外部リンクは `rel="noopener noreferrer"` 付きで開く。
