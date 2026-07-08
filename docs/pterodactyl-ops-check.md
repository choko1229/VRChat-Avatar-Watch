# Pterodactyl 運用確認

## Startup command

推奨:

```bash
sh scripts/pterodactyl-start.sh
```

直接指定する場合:

```bash
UV_CACHE_DIR=.local/uv-cache uv run python main.py
```

`.env` は引き続き `WEB_PORT` のみです。Pterodactyl 側が `SERVER_PORT` または `PORT` を渡す環境では、`WEB_PORT` 未設定時にそれらを自動で使います。

## 確認項目

- [ ] Pterodactyl の Startup に `sh scripts/pterodactyl-start.sh` を設定する。
- [ ] Pterodactyl の割当ポートが `WEB_PORT`、または `SERVER_PORT` / `PORT` と一致している。
- [ ] 初回起動ログに `Uvicorn running on http://0.0.0.0:<port>` が出る。
- [ ] `UV_CACHE_DIR=.local/uv-cache` で default user cache の権限エラーが出ない。
- [ ] `/api/health` が `{"ok": true}` を返す。
- [ ] `/setup` で MySQL 接続情報を保存できる。
- [ ] Pterodactyl の restart 後も `data/runtime_config.json` が残り、DB接続設定が維持される。
- [ ] 管理画面の `保存せず確認` でクロールドライランが動く。
- [ ] クロール後に `crawl_logs` と `error_logs` が確認できる。

## 長時間起動確認

最低30分、可能なら6時間以上起動したままにして以下を確認します。

- [ ] `/api/health` が継続して応答する。
- [ ] 管理画面を開いたときにDB接続エラーが出ない。
- [ ] クロール実行後にログが保存される。
- [ ] 403 / 429 / 5xx または robots.txt 拒否時に失敗理由がログに残る。

## ローカルで代替確認済み

- `WEB_PORT=49175` で `uv run python main.py` 起動。
- `UV_CACHE_DIR=.local/uv-cache` 指定で起動。
- `/api/health` 応答。
- サーバー再起動後もローカル `data/` 設定が維持される構成。

Pterodactyl実機の割当ポート、MySQL、Discord OAuth、長時間起動は実環境で再確認してください。
