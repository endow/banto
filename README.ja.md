# Banto

[English](README.md)

Banto は、エージェントのハートビート状態、イベント中継、context 転送を扱う軽量な REST/JSON ハブです。

現在の設計は `docs/design.md` にあります。

## 何のためのものか

Banto は、自分が管理する local / private な agent 群を手早くつなぐための小さな hub です。業界標準の agent protocol を作ることや、外部 vendor / framework 間の相互運用を標準化することは目的にしていません。

想定している使い方は、身内の agent を数体から小規模に接続し、以下だけを薄く共有することです。

- 誰が登録されているか。
- 各 agent が push した heartbeat status。
- `notify_to` または `type` / `target` の完全一致 subscription による event relay。
- 解釈・要約・merge しない context forwarding。

Banto は、agent LAN の番頭のように配送窓口を担います。ただし、何を実行すべきか、どの agent が最適か、結果をどう統合するかは判断しません。判断は常に呼び出し元 agent、受信 agent、または人間の側に残します。

## A2A との関係

[Agent2Agent (A2A)](https://a2a-protocol.org/latest/) は、異なる agent framework や vendor の間で agent-to-agent interoperability、task delegation、collaboration を成立させるための open standard です。

Banto は A2A を置き換えるものではありません。A2A は外部 agent と相互運用したり、rich な task delegation / collaboration を扱ったりする場面に向いています。Banto は、自分が管理する local / private agent 群に対して、もっと薄い primitive だけで足りる場面のためにあります。

もし agent 同士が stateful task、streaming、artifact、能力発見、交渉、外部組織との相互運用を必要とするなら、Banto を拡張するより A2A を使う方が自然です。Banto はその領域に入らず、必要になった場合は各 agent が A2A endpoint を別途持つ、または adapter を別に書く前提にします。

Banto がやらないこと:

- 汎用 agent protocol の定義
- A2A 互換 task lifecycle の実装
- streaming / artifact / capability negotiation
- 賢い routing や task orchestration
- prompt inspection や Human-in-the-Loop policy の本体組み込み
- rule engine、retry queue、monitoring system 化

これらが必要になった場合は、A2A や専用の policy gateway / approval agent を Banto の外側または agent 側に置きます。

## 現在の状態

Banto は現在の設計スコープの初期実装を持っています。

実装済み:

- インメモリの agent registry
- heartbeat status cache
- `type` / 任意 `target` の完全一致による subscription table
- registration token を標準必須とする `POST /register`
- agent token 認可つき `POST /heartbeat`
- `delivered` / `failed` の部分結果を返す `POST /events` synchronous fan-out
- heartbeat 受信時に駆動する受動的な `banto.agent_down` 評価
- `GET /agents` と `GET /agents/{id}/status`
- `POST /agents/{id}/context` の単一転送
- `POST /context` の fan-out 転送
- agent status と on-demand context 転送結果を確認する `GET /dashboard`
- endpoint allowlist と localhost opt-in
- local smoke check と境界テスト

既知の制約:

- registry と heartbeat cache はメモリのみです。
- `agent_down` は受動評価です。全 agent が同時に沈黙した場合、検出は駆動されません。
- subscription の更新・削除 API はまだありません。
- event retry queue や永続化はありません。
- Banto は `event_id` の重複排除を行いません。冪等性は受信側の責務です。
- timeout 処理以外の rate limit や overload protection はありません。
- MCP 外部ツール転送は初期コードパスには未実装です。

## 起動

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
```

local agent endpoint を使う場合は明示的に opt-in します。

```powershell
$env:BANTO_ALLOW_LOCALHOST = "true"
$env:BANTO_REGISTER_TOKEN = "dev-register-token"
.venv\Scripts\uvicorn banto.app:app --reload
```

`POST /register` は標準で `BANTO_REGISTER_TOKEN` を要求します。ローカル実験だけ、open registration を明示的に有効化できます。

```powershell
$env:BANTO_ALLOW_OPEN_REGISTER = "true"
```

Docker で起動する場合:

```powershell
docker compose up --build -d
```

Docker 起動時は `http://127.0.0.1:18000` で待ち受け、`POST /register` には `Authorization: Bearer dev-register-token` が必要です。停止する場合:

```powershell
docker compose down
```

Docker コンテナからホスト側の mock agent へ転送する場合、agent endpoint は `http://host.docker.internal:9001` のように指定し、`compose.yaml` の `BANTO_ALLOWED_HOSTS` に `host.docker.internal` を追加してください。

## Dashboard

起動後、ブラウザで `http://127.0.0.1:8000/dashboard` を開くと、登録済み agent の state と heartbeat status cache を確認できます。

Agent 一覧はデフォルトで 5 秒ごとに自動更新されます。これはブラウザが Banto の cached status を読むだけで、Banto が agent へ能動確認するものではありません。

Dashboard の context 表示は、Banto が context を保存して覗くものではありません。画面操作時に既存の `POST /agents/{id}/context` または `POST /context` を呼び、agent から返った JSON をその場で表示します。

## Quickstart

以下の例では、Banto が `http://127.0.0.1:8000`、mock agent が `http://127.0.0.1:9001` で起動している前提です。

別 terminal で mock agent を起動します。

```powershell
python examples\mock_agent.py --agent-id agent-b --port 9001
```

agent を登録します。

```powershell
$registerHeaders = @{ Authorization = "Bearer dev-register-token" }
$agentB = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/register `
  -Headers $registerHeaders `
  -ContentType "application/json" `
  -Body '{
    "agent_id": "agent-b",
    "endpoint": "http://127.0.0.1:9001",
    "heartbeat_interval_sec": 5,
    "down_threshold_sec": 20,
    "subscribe": [{"type": "demo.notice"}]
  }'
```

登録時に返った agent token で heartbeat を送信します。

```powershell
$agentHeaders = @{ Authorization = "Bearer $($agentB.token)" }
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/heartbeat `
  -Headers $agentHeaders `
  -ContentType "application/json" `
  -Body '{
    "agent_id": "agent-b",
    "status": {"alive": true, "load": "idle", "accepting": true}
  }'
```

cached status を取得します。

```powershell
Invoke-RestMethod http://127.0.0.1:8000/agents/agent-b/status
```

context query を転送します。

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/agents/agent-b/context `
  -ContentType "application/json" `
  -Body '{"query": "ping", "format": "raw"}'
```

local smoke check を実行します。

```powershell
python examples\smoke_check.py
```

## 設定

| 変数 | デフォルト | 説明 |
|---|---:|---|
| `BANTO_REGISTER_TOKEN` | 未設定 | `POST /register` に必要な bearer token。open registration を明示的に有効化しない限り必須です。 |
| `BANTO_ALLOW_OPEN_REGISTER` | `false` | `true` の場合のみ、認証なしの `POST /register` を許可します。ローカル実験専用です。 |
| `BANTO_ALLOWED_HOSTS` | 未設定 | endpoint hostname の comma-separated allowlist。例: `agent-a.example.com,agent-b.example.com` |
| `BANTO_ALLOW_LOCALHOST` | `false` | `true` の場合のみ `localhost` / loopback endpoint を許可します。ローカル開発専用です。 |
| `BANTO_REQUEST_TIMEOUT_SEC` | `3` | event delivery / context forwarding の宛先ごとの timeout。 |
| `BANTO_FANOUT_TIMEOUT_SEC` | `10` | fan-out 全体 timeout。未完了の宛先は `global_timeout` として返ります。 |

endpoint registration は allowlist ベースです。hostname は `BANTO_ALLOWED_HOSTS` に含まれている必要があります。ただし `BANTO_ALLOW_LOCALHOST=true` の場合のみ、local loopback endpoint を許可します。IP literal endpoint は、loopback かつ localhost opt-in が有効な場合を除き拒否されます。

## Agent Contract

Banto に参加する agent は 2 つの endpoint を実装します。

### `POST /context`

agent は context query を受け取り、自分の context で応答します。Banto は request body を解釈せずに転送します。

Request:

```json
{
  "query": "string",
  "format": "summary | raw"
}
```

Response は agent 定義の JSON です。Banto は `POST /agents/{id}/context` ではそのまま返し、`POST /context` では agent ごとの結果として包んで返します。

### `POST /event`

agent は Banto から配信された event を受け取ります。未知の event type は受信側が安全に無視してください。

Request:

```json
{
  "event_id": "string",
  "source": "agent_id",
  "type": "string",
  "target": "optional target",
  "payload": {}
}
```

Response body は Banto では解釈しません。2xx response は delivered として扱います。redirect は追跡せず `redirect_error` として扱います。4xx / 5xx response は event source へ `http_4xx` / `http_5xx` として返します。`notify_to` に未登録の `agent_id` が含まれる場合、イベント全体は処理され、その宛先は `failed` に `not_found` として返ります。

## Banto API Summary

| Method | Path | Notes |
|---|---|---|
| `POST` | `/register` | agent を登録し agent token を返します。open registration が無効な場合は registration token が必要です。 |
| `POST` | `/heartbeat` | cached status を更新します。`agent_id` と一致する agent token が必要です。 |
| `POST` | `/events` | event を発行します。`source` と一致する agent token が必要です。`delivered` / `failed` を返します。 |
| `GET` | `/agents` | 登録済み agent と cached status を返します。 |
| `GET` | `/agents/{id}/status` | 1 agent の cached status を返します。 |
| `GET` | `/dashboard` | agent status と on-demand context 転送結果を表示する薄い UI です。 |
| `POST` | `/agents/{id}/context` | 1 agent へ context query を転送します。 |
| `POST` | `/context` | `scope` へ context query を fan-out し、agent ごとの結果配列を返します。 |
