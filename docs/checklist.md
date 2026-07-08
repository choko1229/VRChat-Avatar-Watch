# 運用チェックリスト

## ローカル

- [ ] `uv run pytest`
- [ ] `uv run python -m compileall app scripts tests`
- [ ] `uv run python main.py`
- [ ] `/api/health` が200
- [ ] `/avatars` が表示される

## Pterodactyl

- [ ] `sh scripts/pterodactyl-start.sh` で起動する
- [ ] 割当ポートと `WEB_PORT` が一致する
- [ ] `UV_CACHE_DIR=.local/uv-cache` で起動できる
- [ ] 再起動後も設定とDB接続が維持される

## BOOTHクロール

- [ ] `scripts/booth_ops_check.py --keyword キプフェル` がpreview成功またはdeferredを返す
- [ ] `--save` で1回保存できる
- [ ] 即時再実行が `skipped` になる
- [ ] `items`, `price_histories`, `crawl_logs` が増える
- [ ] エラー時に `error_logs` が残る

## 管理画面

- [ ] `/admin/crawl` で対象削除ができる
- [ ] `/admin/avatars` で情報再取得ができる
- [ ] アバター削除後に商品が再判定される
- [ ] 商品/ツール/ショップを削除できる

## 通知

- [ ] `/me` で通知設定を保存できる
- [ ] Discord Webhook設定後に通知が送信される
- [ ] Misskey設定後に投稿される
