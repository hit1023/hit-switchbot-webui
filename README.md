# hit-switchbot-webui

SwitchBot公式の [Open API v1.1](https://github.com/OpenWonderLabs/SwitchBotAPI) をラップした、自宅のSwitchBotデバイス（鍵・Hub経由の赤外線家電など）を外出先からブラウザ操作するための自作WebUI/APIツールです。

SwitchBotのtoken/secretはサーバー側(バックエンド)でのみ保持し、ブラウザには一切渡しません。全APIはJWT認証必須です。

---

## 機能一覧

| 機能 | 概要 |
|---|---|
| デバイス一覧取得 | アカウントに登録済みの物理デバイス・赤外線リモコンデバイスを一覧表示 |
| 鍵の施錠/解錠 | Smart Lock系デバイスへlock/unlockコマンドを送信、現在の施錠状態も確認 |
| エアコン操作 | Hub経由の赤外線リモコンへON/OFF・温度・モード・風速を指定してsetAllコマンドを送信 |
| 認証 | JWTによるログイン認証。ログイン失敗が続くとロックアウト(5回失敗で5分間ロック) |
| 実行ログ | 送信したコマンド(施錠/解錠・エアコン操作)の日時・実行者・結果をSQLite(`/data/history.db`)に記録しWebUIに表示 |
| 鍵の状態変化ログ(Webhook) | SwitchBot Webhookを使い、アプリ/指紋認証/キーパッド等、経路を問わず鍵が実際に施錠/解錠された変化をリアルタイムに検知してログへ記録(誰が/どの方法で操作したかまでは取得不可、状態が変わった事実のみ) |

対応デバイスタイプはSwitchBot Open APIが返す`deviceType`/`remoteType`をもとに自動分類しています（`Lock`を含むものは鍵カード、`Air Conditioner`または名前に「エアコン」を含む赤外線デバイスはエアコンカード、それ以外は情報表示のみのカードとして表示）。他のデバイス種別を操作したい場合は [`app/main.py`](app/main.py) にエンドポイントを、[`webui/index.html`](webui/index.html) に対応するカードを追加してください。

---

## システム構成

```
ブラウザ (JWTログイン)
   │ HTTPS
   ▼
リバースプロキシ (任意: nginx / Caddy / Traefik / nginx-proxy-manager等)
   │ forward → コンテナのAPP_PORT
   ▼
hit-switchbot-webui コンテナ
 ┌──────────────────────────────┐
 │ FastAPI + Uvicorn            │
 │  - POST /api/login            │
 │  - GET  /api/devices          │
 │  - GET  /api/devices/{id}/status   │
 │  - POST /api/devices/{id}/commands │
 │  - 静的ファイル配信 (webui/)   │
 └──────────────┬────────────────┘
                │ HTTPS (HMAC-SHA256署名, token/secretはサーバー内のみ)
                ▼
        SwitchBot Cloud API
                │
                ▼
     SwitchBot Hub (Mini/2/Plusなど)
                │
      ┌─────────┴─────────┐
   Smart Lock系          赤外線家電(エアコン等)
```

---

## 必要なもの

- Docker Engine + Docker Compose
- SwitchBotアプリで発行したtoken/secret
  1. SwitchBotアプリを開く
  2. 「プロフィール」タブ →「設定」
  3. 「アプリバージョン」の表示部分を連続タップ（10回程度）すると「開発者向けオプション」が出現
  4. 「開発者向けオプション」を開くと token と secret が表示されるのでコピー
- （外部公開する場合）ドメインとTLS証明書、リバースプロキシ

---

## セットアップ

### 1. 環境変数の準備

```bash
git clone git@github.com:hit1023/hit-switchbot-webui.git
cd hit-switchbot-webui
cp app.env.example app.env
```

`app.env`を編集し、以下を設定します。

| 変数名 | 説明 |
|---|---|
| `SWITCHBOT_TOKEN` | SwitchBotアプリで発行したtoken |
| `SWITCHBOT_SECRET` | SwitchBotアプリで発行したsecret |
| `APP_SECRET_KEY` | JWT署名用の秘密鍵。下記コマンドで生成 |
| `ADMIN_USERNAME` | ログインユーザー名（デフォルト: `admin`） |
| `ADMIN_PASSWORD_HASH` | ログインパスワードのbcryptハッシュ。平文は保存しない |
| `JWT_EXPIRE_HOURS` | JWTトークンの有効期限(時間)。外部公開時は短めを推奨（デフォルト: `24`） |
| `APP_PORT` | WebUI/APIの待受ポート（デフォルト: `8092`） |
| `PUBLIC_BASE_URL` | このアプリの外部公開URL（例: `https://switchbot.example.com`）。鍵のWebhookログ機能を使う場合のみ必須 |
| `WEBHOOK_PATH_TOKEN` | Webhook受信URLに含めるランダムトークン。下記コマンドで生成 |

`APP_SECRET_KEY`の生成:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

`ADMIN_PASSWORD_HASH`の生成（`passlib[bcrypt]`が必要な場合は`pip install passlib[bcrypt]`）:

```bash
python3 -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('好きなパスワード'))"
```

`WEBHOOK_PATH_TOKEN`の生成:

```bash
python3 -c "import secrets; print(secrets.token_hex(16))"
```

### 2. 起動

```bash
docker compose up -d --build
```

起動後、`http://<ホスト>:8092`にアクセスするとログイン画面が表示されます。ポートを変更したい場合は`app.env`の`APP_PORT`と`docker-compose.yml`の`ports`を両方書き換えてください。

### 3. 動作確認（API単体）

```bash
# ログインしてJWTを取得
curl -X POST http://localhost:8092/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<設定したパスワード>"}'

# デバイス一覧を取得
curl http://localhost:8092/api/devices \
  -H "Authorization: Bearer <取得したJWT>"
```

### 4. 外部公開する場合

このコンテナ自体はTLS終端を行わないため、外部公開する場合はリバースプロキシ（nginx-proxy-manager、Caddy、Traefikなど）で以下のようにHTTPS化してから公開してください。

```
https://<任意のドメイン> → http://<コンテナのホスト>:8092
```

鍵の施錠/解錠という物理セキュリティに直結する機能を公開するため、**必ずHTTPS化した上で公開**し、`ADMIN_PASSWORD_HASH`には十分に強いパスワードを設定してください。

---

## ローカル開発（Dockerを使わない場合）

```bash
cd app
pip install -r requirements.txt
export SWITCHBOT_TOKEN=... SWITCHBOT_SECRET=... APP_SECRET_KEY=... ADMIN_PASSWORD_HASH=...
uvicorn main:app --reload --port 8092
```

`webui/index.html`は`app/main.py`が`/webui`ディレクトリをマウントして配信する前提のため、Docker外で動かす場合はパスの調整が必要です（Dockerでの起動を推奨）。

---

## プロジェクト構成

```
hit-switchbot-webui/
├── app/
│   ├── main.py             # FastAPIルーティング
│   ├── auth.py              # JWT発行・ログインロックアウト
│   ├── switchbot_client.py  # SwitchBot Open API v1.1クライアント(HMAC署名)
│   ├── requirements.txt
│   └── Dockerfile
├── webui/
│   └── index.html           # ログイン画面 + デバイス操作UI(単一ページ)
├── docker-compose.yml
├── app.env.example
└── README.md
```

---

## 注意事項

- 鍵の施錠/解錠を外部公開するツールのため、`app.env`の値（特に`SWITCHBOT_TOKEN`/`SWITCHBOT_SECRET`, `ADMIN_PASSWORD_HASH`）は厳重に管理し、リポジトリにコミットしないでください（`.gitignore`で除外済み）。
- SwitchBot Cloud APIには1日あたりのコール数上限があるため、WebUIは自動ポーリングを行わず手動更新ボタンのみで動作します。
- 赤外線経由のデバイス（エアコン等）はSwitchBot側から実際の電源状態を取得できないため、WebUI上では「最後に送信した設定」のみを表示します。
- ログイン試行は5回失敗すると5分間ロックアウトされます（プロセス内メモリで管理のため、コンテナ再起動でリセットされます）。
- `PUBLIC_BASE_URL`/`WEBHOOK_PATH_TOKEN`を設定すると、起動時にSwitchBot側へWebhook URL(`{PUBLIC_BASE_URL}/api/webhook/switchbot/{WEBHOOK_PATH_TOKEN}`)を自動登録します。このURLはJWT認証を通さない受信専用エンドポイントで、パスに含めたランダムトークンのみが正当性の担保です（SwitchBot Webhookには署名検証の仕組みがないため）。トークンが漏れると誰でもログに偽のイベントを書き込めてしまう点に注意してください（デバイス自体を操作されるわけではありません）。

---

## ライセンス

特に指定なし（個人利用目的のプロジェクトです）。
