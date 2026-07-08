# VRChat Avatar Watch チェックリスト

## 構文・起動

- [ ] `python -m compileall app tests`
- [ ] `python main.py` で FastAPI が起動する
- [ ] `/api/health` が `{"ok": true}` を返す
- [ ] `.env.example` は `WEB_PORT` のみ

## DB

- [ ] `/setup` で MySQL 接続情報を保存できる
- [ ] 初回起動時に全テーブルを作成できる
- [ ] 初期アバターと初期ツールが投入される
- [ ] Secret は `settings.is_secret=true` で保存され、画面では平文表示しない

## 認証・管理

- [ ] `/login` から Discord OAuth へ遷移する
- [ ] callback 後に `users` が作成される
- [ ] 初回ログインユーザーまたは設定済みDiscord IDが管理者になる
- [ ] 非管理者は `/admin` に入れない

## クロール

- [ ] 同時アクセス数は 1
- [ ] デフォルト間隔は 6 時間
- [ ] 403 / 429 / 5xx で停止または待機する
- [ ] クロールログとエラーログが保存される
- [ ] 公開HTMLのみを対象にする
