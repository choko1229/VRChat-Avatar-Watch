# Pterodactyl運用確認

## 起動コマンド

```bash
sh scripts/pterodactyl-start.sh
```

または:

```bash
UV_CACHE_DIR=.local/uv-cache uv run python main.py
```

## 確認コマンド

```bash
UV_CACHE_DIR=.local/uv-cache uv run python scripts/production_smoke_check.py https://vrc-aw.choko1229.net
UV_CACHE_DIR=.local/uv-cache uv run python scripts/booth_ops_check.py --keyword キプフェル
```

保存クロールを1回だけ実行する場合:

```bash
UV_CACHE_DIR=.local/uv-cache uv run python scripts/booth_ops_check.py --keyword キプフェル --save
```

## 見るべきログ

- `Application startup complete`
- `Uvicorn running on http://0.0.0.0:<port>`
- `/admin/crawl/status` が200
- `crawl_logs.status` が `success`, `skipped`, `deferred`, `error`, `interrupted` のいずれか
- BOOTH側の `403`, `429`, `5xx`, robots拒否は `error_logs` に残る
