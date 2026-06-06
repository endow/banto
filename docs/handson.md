# 作業進捗

## 現在のタスク
review フェーズ移行と初期実装の利用準備

## 完了済み
- Git 初期化
- Banto FastAPI アプリの初期実装
- registry / heartbeat cache / subscription table のインメモリ管理
- event 同期 fan-out と partial result response
- context 単一転送 / fan-out
- SSRF allowlist の登録時検証
- 受動 agent_down 評価
- pytest による中核仕様の検証
- 初回コミット
- モックエージェントと smoke check の追加
- `python examples/smoke_check.py` による Banto + mock agent 2 台の疎通確認
- register 認証をデフォルト token 必須、開発時のみ open registration opt-in に変更
- 認可拒否と再登録契約の境界テストを追加
- event / context fan-out の失敗境界テストを追加
- README quickstart の追加
- handson 手動 API フローの整理
- 実装レビュー用プロンプトの整備
- `banto/app.py` を route 定義に寄せ、models/config/security/state に分割
- README に設定一覧と外部 agent 契約を追加
- `docs/review_prompt.md` に沿った self-review を実施
- redirect / 非2xx の成功扱いを修正し、境界テストを追加
- 開発契約を review フェーズへ移行
- README に current status / known limitations を追加
- context 2xx 非JSONの 500 化を修正
- event redirect と transport error の reason を分離
- 公開時に意味が通らない固有名・参考文を削除し、汎用 agent 名へ置換
- Banto の位置づけを local / private agent hub として README / design / review prompt に明記

## 進行中

## ブロッカー

## 変更ファイル
- README.md
- README.ja.md
- docs/design.md
- docs/handson.md
- docs/review_prompt.md
- examples/smoke_check.py
- tests/test_app.py

## 次のステップ
- タグ作成前の最終確認
- 必要に応じて `docs/review_prompt.md` に沿った外部レビューを実施

## ローカル smoke check

依存関係を入れてから実行する。

```powershell
python -m pip install -e ".[dev]"
python examples/smoke_check.py
```

このスクリプトは以下を行う。

- Banto を起動
- mock agent-a / agent-b を起動
- ポート未指定時は空きポートを自動選択
- `BANTO_ALLOW_LOCALHOST=true` を Banto プロセスにだけ設定
- `BANTO_ALLOW_OPEN_REGISTER=true` を Banto プロセスにだけ設定
- agent-a / agent-b を register
- heartbeat を送信
- agent-a から `demo.notice` event を発行し、agent-b へ relay されることを確認
- `POST /context` で agent-a / agent-b へ fan-out し、配列レスポンスを確認

## 手動 API フロー

前提:

- Banto: `http://127.0.0.1:8000`
- mock agent-b: `http://127.0.0.1:9001`
- `BANTO_ALLOW_LOCALHOST=true`
- `BANTO_REGISTER_TOKEN=dev-register-token`

### 1. 起動

Terminal 1:

```powershell
$env:BANTO_ALLOW_LOCALHOST = "true"
$env:BANTO_REGISTER_TOKEN = "dev-register-token"
uvicorn banto.app:app --reload
```

Terminal 2:

```powershell
python examples\mock_agent.py --agent-id agent-b --port 9001
```

### 2. register

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

期待:

```json
{
  "agent_id": "agent-b",
  "token": "..."
}
```

### 3. heartbeat

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

期待:

```json
{
  "agent_id": "agent-b",
  "received_at": "...",
  "agent_down": []
}
```

### 4. status

```powershell
Invoke-RestMethod http://127.0.0.1:8000/agents/agent-b/status
```

期待:

```json
{
  "agent_id": "agent-b",
  "state": "alive",
  "status": {"alive": true, "load": "idle", "accepting": true}
}
```

### 5. context

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/agents/agent-b/context `
  -ContentType "application/json" `
  -Body '{"query": "ping", "format": "raw"}'
```

期待:

```json
{
  "agent_id": "agent-b",
  "query": "ping",
  "format": "raw"
}
```

### 6. event

同一 agent が自分宛に発行する最小例:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/events `
  -Headers $agentHeaders `
  -ContentType "application/json" `
  -Body '{
    "event_id": "demo-1",
    "source": "agent-b",
    "type": "demo.notice",
    "payload": {"message": "hello"},
    "notify_to": ["agent-b"]
  }'
```

期待:

```json
{
  "event_id": "demo-1",
  "delivered": ["agent-b"],
  "failed": []
}
```
