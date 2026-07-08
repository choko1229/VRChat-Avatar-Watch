# BOOTH 実ページドライラン記録

実施日: 2026-07-08

## 対象

- `https://booth.pm/robots.txt`
- `https://booth.pm/ja/search/キプフェル?tags%5B%5D=VRChat`
- 商品詳細:
  - `https://booth.pm/ja/items/5813187`
  - `https://booth.pm/ja/items/5615136`
  - `https://booth.pm/ja/items/6567257`

## 結果

- `robots.txt` は取得可能。`/ja/search/...` と `/ja/items/...` は禁止対象に該当しない。
- 検索結果HTMLから60件を抽出。
- 検索結果で価格、画像、ショップ名、VRChatバッジを取得できることを確認。
- 検索結果には説明文がないため、説明文は商品詳細ページで補完する前提。
- 商品詳細3件で、タイトル、説明文、価格、画像、ショップ名、VRChatバッジを取得できることを確認。
- 取得済み実HTMLを使った一時SQLite保存検証で、60件の `Item` と価格履歴を保存できることを確認。

## ローカル環境メモ

このWindows環境では `uv run python` のHTTPアクセスが `OPENSSL_Uplink(...): no OPENSSL_Applink` で停止したため、ページ取得は `curl.exe --ssl-no-revoke` で実施した。

PterodactylまたはLinux環境では、次にアプリ内の `BoothCrawler.preview_target()` と `crawl_target()` を実HTTPで確認する。
