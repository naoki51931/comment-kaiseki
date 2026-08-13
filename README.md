# 棋譜コメント研究所

現在の実装・稼働構成・確認結果・残課題は [実装状況20260714.md](./実装状況20260714.md) にまとめています。

本人の棋譜を解析し、重要局面への3問コメントを収集・審査するアプリです。Docker ComposeでMVPの一連フローを実行できます。

## 実装済み

- メール確認付き登録、Argon2id、短命JWT、ローテーション更新トークン
- 管理者MFAと管理者初期作成CLI
- KIF・KI2・CSA・USIテキストのファイル投稿・クリップボード貼り付け、自動形式判定、USI正規化、SHA-256重複検知
- 許諾済みプロ棋譜のフィンガープリントDBとの照合による、プロ公式戦棋譜の投稿拒否
- 棋譜登録時の公開・非公開設定（安全のため既定値は非公開）
- 棋譜投稿規約への明示同意と、プロ公式戦棋譜の一律投稿禁止
- 所有者による棋譜・解析結果・下書き・保存ファイルの一括削除（報酬記録済みは削除禁止）
- 重要局面のUSI指し手を局面に基づくKIF日本語表記で表示
- 棋譜選択後の盤面再生、持ち駒、手数移動、評価値・読み筋分岐・重要局面コメントの連動表示
- PostgreSQL、SQLAlchemy、Alembic
- Redis/Celery解析ジョブ、再試行、失敗状態
- USIエンジンアダプターとやねうら王プロセス呼び出し
- ユーザー視点の評価値・勝率・SFEN・読み筋保存
- 重要局面のスコアリング、近接候補統合、3〜5件抽出
- 3問下書き、一括提出、提出スナップショット
- 提出前の評価値・採用理由非公開、提出後の表示
- 管理者審査、状態遷移、品質タグ、監査ログ
- 300円報酬台帳、二重付与防止、日次・月次上限、保留・確定・取消
- 口座暗号化、HMACフィンガープリント、振込申請・CSV・支払記録
- ローカル非公開保存、S3 private保存、ClamAV検査の切替実装
- CI定義、DBバックアップ・復元スクリプト、本番用静的Nginxイメージ
- バックエンド単体・API・認証・ワークフロー・解析・購読・SMTP・形式自動判定・棋譜削除・日本語指し手変換・棋譜再生テスト（45件）

## 起動

```bash
sudo docker compose up -d --build
```

- アプリ: `http://サーバーIP/`
- API: `http://サーバーIP:8000/docs`
- 開発用メール受信箱: `http://サーバーIP:8025/`

開発環境では確認メールがMailpitへ届きます。リンクを開くまでログインできません。

## Gmail SMTP設定

本番でGmail SMTPを利用する場合は、Googleアカウントで2段階認証とアプリパスワードを有効にし、Git管理外の `.env` に設定します。通常のGoogleパスワードは使用しません。

```env
EMAIL_DELIVERY_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_FROM=sender.com
SMTP_USERNAME=sender.com
SMTP_PASSWORD=新しく発行したアプリパスワード
SMTP_STARTTLS=true
SMTP_SSL=false
PUBLIC_BASE_URL=https://実際の公開ドメイン
```

`SMTP_PASSWORD` をGit、README、ログ、テストへ保存しないでください。チャットなどへ貼ったアプリパスワードは失効させて再発行します。

## 管理者作成

必ず独自の長いパスワードを使用してください。

```bash
sudo docker compose exec backend   python -m app.cli create-admin --email admin@example.com --password '安全なパスワード'
```

表示されるMFAシークレットまたはURIを認証アプリへ登録します。シークレットは再表示されません。

## プロ棋譜の投稿拒否DB

日本将棋連盟・棋戦主催者等から利用許諾を得た棋譜ファイルだけを専用ディレクトリへ配置して登録します。DBには棋譜本文を保存せず、開始局面と指し手列から作るSHA-256フィンガープリント、出典、対局メタデータだけを保存します。

```bash
sudo docker compose exec backend alembic upgrade head
sudo docker compose exec backend python -m app.cli import-professional-games /data/licensed-pro-kifu \
  --source-name '許諾元の名称' --source-reference '契約・提供資料の管理番号'
```

同一局面・同一指し手列の投稿は、対局者名やファイル名を変更してもHTTP 422で拒否されます。網羅性は投入した許諾済み棋譜の範囲に依存するため、提供元からの追加分を定期的に再実行してください。

## 解析エンジン

既定値は外部バイナリ不要の開発用評価器です。やねうら王を利用する場合はバイナリをコンテナへマウントし、次を設定します。

```env
ENGINE_KIND=yaneuraou
YANEURAOU_PATH=/opt/yaneuraou/YaneuraOu
ENGINE_NODES=10000
```

## 現在の未完了項目

MVPのバックエンド処理は一通り実装済みです。残っている主な項目は次のとおりです。

- 管理者が振込申請を一覧確認し、支払済み記録を登録する画面
- 保存期間に基づく棋譜削除、退会時削除、孤立ファイル清掃
- Reactコンポーネントテスト、ブラウザE2E、実Redis・実やねうら王の結合テスト
- 本番向けログ集約、監視、アラート、HTTPSおよび外部サービス接続

## AI解説の月額課金

コメント提出後の評価値は無料で閲覧できます。AIコメントと読み筋は、Stripeの「AI解説プラン」を契約中のユーザーだけが閲覧できます。初回30日間（1か月）は無料で、その後は月額1,000円です（税込設定はStripe側で確認）。リダイレクトではなく、署名検証済みWebhookで有効な購読状態を受信した後に解放します。

```env
STRIPE_SECRET_KEY=sk_live_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
AI_ACCESS_MONTHLY_PRICE_YEN=1000
AI_ACCESS_TRIAL_DAYS=30
PUBLIC_BASE_URL=https://example.com
```

Stripe WorkbenchでWebhook URLを `https://example.com/api/ai-access/webhook` に設定し、次のイベントを購読します。

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`

Stripe Customer Portalを有効化すると、契約者が画面から契約内容の確認と解約を行えます。

検証環境では `AI_ACCESS_TEST_USER_EMAIL` に指定した1ユーザーだけ、ユーザー名横の「1,000円課金 ON/OFF」ボタンで手動課金状態を切り替えられます。この切替ではStripeへ実請求しません。本番では設定を空にしてください。ヘッダーの操作ボタンは明るい背景でも読める濃色文字とし、課金切替ボタンは薄い金色の背景で区別します。

対象の検証ユーザーだけ、棋譜再生画面の評価値横に「評価値を表示/隠す」ボタンが表示され、提出前でも手動確認できます。「1,000円課金 ON」の場合は読み筋・分岐も表示され、切替直後に再生データを再取得します。他ユーザーの提出・課金による公開条件は変更しません。

## 本番外部サービス

`.env.example`を基に秘密情報を設定し、Gitへ登録しないでください。

- `PUBLIC_BASE_URL`: メールリンクに使うHTTPS URL
- SMTP: 本番メールサービスへ変更
- `STORAGE_BACKEND=s3`、`S3_BUCKET`: 非公開S3保存
- `MALWARE_SCAN_ENABLED=true`: ClamAV検査
- `JWT_SECRET`、`ENCRYPTION_KEY`、`BANK_FINGERPRINT_KEY`: それぞれ別のランダム値
- ドメインとTLS証明書: インフラ側で設定

## テスト

```bash
sudo docker compose run --rm --no-deps backend pytest -q
sudo docker compose run --rm --no-deps frontend sh -c 'npm install && npm run build'
sudo docker compose run --rm backend alembic check
```

## バックアップ

```bash
./scripts/backup.sh
./scripts/restore.sh backups/kifu_comment-YYYYMMDDTHHMMSSZ.dump
```

現在の優先順位は [作業方針0715.md](./作業方針0715.md)、これまでの実装履歴は [作業方針0714.md](./作業方針0714.md) を参照してください。


## Weaviate横断検索

ログインユーザー自身の棋譜、重要局面、提出済み回答、AIコメントを日本語で横断検索できます。Weaviateが利用できない場合はDB検索へ自動で切り替わります。詳細は [実装状況20260714.md](./実装状況20260714.md) を参照してください。

## セキュリティ更新（2026-07-14）

- FastAPI 0.139.0、Starlette 1.3.1、python-multipart 0.0.32へ更新。
- PyJWT 2.13.0、cryptography 49.0.0、pytest 9.0.3へ更新。
- React 19.2.7、Vite 8.1.4などの `latest` 指定を廃止し、バージョンを固定。
- JWT・暗号化・口座フィンガープリント鍵をランダム値へ変更し、既存MFAを再暗号化。
- Vite開発サーバーとUvicorn `--reload` を廃止し、Nginx静的配信と複数Uvicorn workerへ変更。
- FastAPI、Mailpit、Redis、PostgreSQLのホスト向けポート公開を停止。
- Nginxへ基本セキュリティヘッダーを追加。
- `npm audit` と `pip-audit` は既知脆弱性0件。

現在もHTTP公開のため、パスワードとトークンの通信暗号化にはHTTPS導入が必要です。JWT鍵変更により、変更前に発行したアクセストークンは無効です。

## 棋譜メタデータとやねうら王分岐（2026-07-14）

- KIF・KI2・CSA・TXTの棋戦名、先手名、後手名を投稿時に読み取り、最近の棋譜と棋譜再生画面に表示します。既存の保存済み棋譜も再読込済みです。
- USIアダプターはやねうら王の `MultiPV=5` に対応し、各局面で最大5候補、各候補最大5手、投稿者視点の評価値を保存します。
- 評価値本体は無料表示、5分岐の読み筋はAI月額プラン（初回1か月無料、その後月額1,000円）で表示します。
- 現在のDocker稼働設定は `ENGINE_KIND=yaneuraou` で、やねうら王 NNUE 9.60git 64AVX2と水匠5評価関数を使用しています。
