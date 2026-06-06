# Banto 要求仕様書

## 概要

Banto は任意のエージェント間を接続する軽量ハブ。
判断を持たず、生存状態の保持・イベントの中継・問い合わせの転送のみを担う。

Banto の主用途は、自分が管理する local / private な agent 群を手早く接続すること。業界標準の agent protocol を定義すること、外部 vendor / framework 間の相互運用を標準化すること、rich な task delegation / collaboration を扱うことは目的にしない。

Agent2Agent (A2A) のような標準プロトコルが必要になる場面では、Banto を A2A 互換に肥大化させるのではなく、各 agent が A2A endpoint を別途持つ、または Banto の外側に adapter を置く。Banto 本体は presence / heartbeat status cache / event relay / context forwarding に留める。

## 設計思想

### 判断しないことを選んでいる存在

- オーケストレーターではない。
- 生存状態を正確に保持して伝え、イベントを正確に配り、問い合わせを正確に転送するだけ。
- 判断の主体は常に各エージェント／人間。
- この原則を運用規律ではなく**構造**で守る。Banto は判断に必要な情報をそもそも受け取らない／持たない設計とする。

### local / private agent LAN の番頭

- Banto は、自分が管理する agent 群のための小さな配送窓口である。
- 不特定多数の外部 agent と相互運用するための標準 protocol ではない。
- 参加 agent は Banto 通信インターフェースを実装すればよい。A2A などの外部標準が必要な agent は、Banto とは別にその endpoint を持てる。
- Banto は agent 間の task lifecycle、capability discovery、streaming、artifact、交渉を扱わない。
- prompt inspection、Human-in-the-Loop、policy 判断が必要な場合は、Banto 本体ではなく専用 agent / policy gateway として外側に置く。

### 賢くなれない構造

- 「何が異常か」「何をイベントとするか」の判定はすべて発生源のエージェントが行い、Banto へイベントとして投げる。Banto に判定ロジックを持たせない。
- Banto は **自律 polling を行わない**。外向きの通信はすべて受信リクエストに誘発される relay（イベント配信・context 転送・MCP 転送）に限定し、Banto 起点の能動的な状態確認は行わない。
- Banto が持つ唯一の時間ベース処理は agent_down 判定のみ。これは `last_heartbeat_at + down_threshold_sec < now` という機械的な時間判定に限定し、値の意味は解釈しない。さらにこの判定は **heartbeat 受信を契機に駆動する受動評価**であり、Banto は自律スキャンのためのタイマーも持たない（後述「agent_down の検出方式」）。
- subscription のマッチングは type / target の**完全一致のみ**。範囲比較・正規表現・論理演算（OR/NOT）は持たせない。Banto をルールエンジンにしない。

### 疎結合・軽量

- 通信はシンプルな REST/JSON。
- Banto の保持状態は **agent registry・subscription table・heartbeat status cache の 3 つに限定**する。いずれも配送に必要な状態であり、ドメイン状態は持たない。
- registry・heartbeat cache は初期版ではメモリのみ。永続化しない。
- MCP は外部ツール接続にのみ使用し、Banto 内部通信には使用しない。

### 拡張性

- Banto 通信インターフェースを実装すれば任意のエージェントが参加可能。
- 実装すべきエンドポイントは 2 つのみ（`POST /context`・`POST /event`）。参加コストを最小化する。

## 不変条件

実装・拡張を通じて維持する条件。

1. Banto は自律 polling を行わない。status は `POST /heartbeat` に同梱された値のみをキャッシュする。
2. Banto の保持状態は registry・subscription table・heartbeat status cache に限定する。
3. Banto は event の type と payload を解釈せず、配信先解決と転送のみを行う。
4. context は POST で扱い、Banto は query/response を解釈・要約・マージしない。単一宛先は `POST /agents/{id}/context`、複数 fan-out は `POST /context`（body の scope で指定）に分離する。
5. event 配信は best-effort + synchronous fan-out + partial result response とする。
6. `POST /events` は成功時 200 OK を返し、body に delivered / failed を含める。4xx/5xx は認証失敗・schema 不正・未登録発行元など、処理開始前の失敗に限定する。
7. Banto は永続 retry queue を持たない。再送判断は発行元エージェントの責務とする。
8. notify_to が明示されていればそれを優先し、空なら subscribe に基づいて配信先を解決する。
9. subscribe は構造化 schema とし、type と任意の target を持てる。条件は完全一致のみ。範囲比較・正規表現・OR/NOT は持たせない。subscription `{type:"x"}` は target を問わず type 一致で配信対象になる。`{type:"x", target:"y"}` は event の target が "y" の場合のみ配信対象になる。
10. 受信側は未知の event type を安全に無視できる責務を持つ。
11. agent_down は `source: "banto"`, `type: "banto.agent_down"` の Banto 生成イベントとする。判定は `last_heartbeat_at + down_threshold_sec < now` のみ。判定は heartbeat 受信を契機に駆動する受動評価とし、Banto は自律スキャンを行わない。全エージェントが同時に沈黙した場合は評価を駆動する契機が存在しないため検出されない（既知の制約として許容）。
12. registry と heartbeat cache は初期版ではメモリのみ。Banto 再起動後はエージェントの再登録と heartbeat で回復する。
13. event_id の重複排除は Banto では行わず、受信側エージェントの責務とする。
14. SSRF 対策は初期版から必須。endpoint は allowlist に合致する宛先のみ登録可能にする。
15. localhost / loopback はデフォルト拒否。開発時のみ `BANTO_ALLOW_LOCALHOST=true` のような起動フラグで明示 opt-in する。
16. event / context fan-out は個別 timeout と全体 timeout の両方を持つ。全体 timeout 到達時、未完了の配信先は failed に `global_timeout` として含める。
17. `POST /context` の scope は 1 件以上を許可する。1 件の場合も fan-out endpoint として一様に処理し、`POST /agents/{id}/context` への誘導や 400 応答はしない。
18. agent_down 検出は受動評価方式とする。全静止状態での非検出は既知の制約として許容する。
19. `POST /register` はデフォルトで registration token を必須とする。open registration は開発時のみ `BANTO_ALLOW_OPEN_REGISTER=true` で明示 opt-in する。

## アーキテクチャ

```
生存通知（プッシュ型・status 相乗り）：
  agent-a / agent-b → POST Banto /heartbeat（status を同梱）
  Banto は最新 status をキャッシュとして保持

状態の覗き見（プル型・キャッシュ参照）：
  agent-a / agent-b → GET Banto /agents/{id}/status
  Banto はキャッシュ済み status を返す（能動確認はしない）

イベント中継（プッシュ型・synchronous fan-out）：
  発生源エージェントが「異常だ／事象だ」と判定 → POST Banto /events
  Banto → POST 各エージェント /event（配信先を解決して同期 fan-out）
  Banto → 発行元へ delivered / failed を 200 OK で返す

情報問い合わせ（素通し転送）：
  単一宛先：agent-a / agent-b → POST Banto /agents/{id}/context
  複数宛先：agent-a / agent-b → POST Banto /context（body の scope で指定）
  Banto → 対象エージェントの /context へ転送 → 返値をそのまま返す（複数時は配列）

外部ツール接続：
  Banto → MCP → 外部サービス
```

## Banto 通信インターフェース

### エージェント側が実装するエンドポイント

| メソッド | パス | 説明 |
|--------|------|------|
| POST | /context | query を受け取り、自分の文脈で答える（可変コスト） |
| POST | /event | Banto からの配信イベントを受け取る。未知 type は安全に無視する |

### Banto 側が提供するエンドポイント

| メソッド | パス | 説明 |
|--------|------|------|
| POST | /register | エージェント登録（heartbeat 間隔・down 閾値・subscribe を含む） |
| POST | /heartbeat | 生存通知。status を同梱する |
| POST | /events | イベント発行。同期 fan-out し delivered/failed を返す |
| GET | /agents | 接続中エージェント一覧（生死・キャッシュ済み status） |
| GET | /agents/{id}/status | 特定エージェントのキャッシュ済み status を返す |
| POST | /agents/{id}/context | 単一宛先専用。指定エージェントの /context へ素通し転送。body に scope を持たない |
| POST | /context | 複数宛先 fan-out 専用。body の scope で対象を指定し、結果を配列で返す |

## status とコストの考え方

問い合わせには 2 つのコスト階層がある。

- **status（定数コスト）**: 生死・負荷・受付可否を文脈構築なしに即答できる値。`POST /heartbeat` に同梱して Banto へ渡し、Banto はキャッシュとして保持する。呼ぶ側はこのキャッシュを安く参照できる。
- **context（可変コスト）**: query に応じて文脈を集めて答えを構築する。高コスト。

この二段構えにより、呼ぶ側はバックプレッシャーを成立させられる。重い context 問い合わせの前に、安い status で受付可否を確認できる。status はハートビートのキャッシュのみで提供し、直接問い合わせ経路は設けない（能動 polling を避けるため）。鮮度が必要な用途ではハートビート間隔を詰めて対応する。

### status の同梱フォーマット（案）

```json
{
  "alive": true,
  "load": "idle | normal | busy",
  "accepting": true
}
```

Banto はこの値を解釈しない。受け取ってキャッシュし、問い合わせに応じて返すだけ。

## イベント設計

- 「何を異常／事象とするか」の定義権と判定責務は、すべて発生源のエージェントが持つ。Banto は `notify_to` と `subscribe` に従って配信先を解決し、配るのみ。重要度も内容も判定しない。
- 配信は **synchronous fan-out**。発行元のリクエスト内で各配信先へ配り、結果を集約して返す。
- 配信は **best-effort**。Banto は永続 retry queue を持たない。再送が必要なら、返却された failed を見て発行元が判断する。

### 配信先解決のルール

- `notify_to` が明示されていれば、それを配信先として優先する（subscribe を上書きしうる）。
- `notify_to` が空の場合のみ、subscription table を照合して配信先を解決する。
- `notify_to` に未登録 agent_id が含まれる場合、イベント全体は拒否せず、該当 agent を `failed` に `not_found` として含める。
- 照合規則：
  - subscription `{type:"x"}` は、event の target を問わず type 一致で配信対象になる（target はワイルドカード扱い）。
  - subscription `{type:"x", target:"y"}` は、event の target が "y" の場合のみ配信対象になる（完全一致）。
- この結果、受信側は購読していない type のイベントを受け取りうる。受信側は未知 type を安全に無視する責務を持つ。

### イベント発行フォーマット（案）

```json
{
  "event_id": "string",
  "source": "agent-a",
  "type": "string",
  "target": "string (optional)",
  "payload": {},
  "notify_to": ["agent-b"]
}
```

`type` も `payload` も Banto は解釈しない。`source` が名乗り、配信先を解決して配るのみ。`event_id` の重複排除は受信側の責務であり、Banto は素通しする。

### 配信結果レスポンス（200 OK）

```json
{
  "event_id": "...",
  "delivered": ["agent-b"],
  "failed": [
    {"agent": "agent-a", "reason": "not_found | timeout | connection_refused | transport_error | redirect_error | http_5xx | http_4xx | global_timeout"}
  ]
}
```

`connection_refused` は接続確立前の接続失敗、`transport_error` は接続確立後のプロトコル・読み書き系の転送失敗、`redirect_error` は redirect 応答を表す。`http_4xx` は、配信先には接続できたが受信側がリクエストを拒否したことを表す。`http_5xx` は受信側サーバーエラーとして区別する。

リクエスト自体の受理に失敗した場合（認証失敗・schema 不正・未登録発行元）のみ 4xx/5xx を返す。配信の部分失敗は 200 OK の body で表現する。

### Banto 生成イベント

- Banto が生成するイベントは `source: "banto"`、`type` は `banto.*` プレフィックスで名前空間を分ける。
- 初期版で許可する Banto 生成イベントは `banto.agent_down` のみ。
- agent_down の判定は `last_heartbeat_at + down_threshold_sec < now` のみ。
- **再起動直後の扱い**: `last_heartbeat_at` が未記録（null）のエージェントは down ではなく unknown として扱い、agent_down 判定の対象外とする。これにより再起動後に未受信エージェントを誤って down 通知することを防ぐ。
- agent_down イベントは、down したエージェントを `target` として持ち、その target を購読しているエージェントへ配信する。誰が気にするかは Banto が判断せず、subscribe で表現させる。

### agent_down の検出方式（受動評価）

- 初期版では **受動評価方式**を採る。Banto は agent_down 検出のための自律スキャン用タイマーを持たない。
- 評価は **heartbeat 受信を契機に駆動**する。あるエージェントから heartbeat を受け取ったタイミングで、Banto は登録済みエージェントのタイムアウト（`last_heartbeat_at + down_threshold_sec < now`）を評価し、超過したものを agent_down として配信する。
- **既知の制約**: この方式では、評価を駆動するのは外部から届く heartbeat である。したがって**全エージェントが同時に沈黙した場合、評価を駆動する契機が存在せず、agent_down は検出されない**。これは「いつか必ず検出される遅延」ではなく「契機がなければ観測されない非検出」である。初期版ではこの死角を許容する。
- 実用上、全エージェントが同時沈黙する状況はシステム全体が停止している状態であり、agent_down を受け取る相手も動いていないため、非検出が実害になりにくい。
- 将来「Banto 自身の生存監視」や「外部からのシステム全体ヘルスチェック」を導入する場合、それが唯一の能動評価の駆動源になりうる。受動評価の死角を埋めたくなったときの拡張ポイントとして認識しておく。

## context 設計

Banto は query もレスポンスも解釈・要約・マージしない。用途に応じて 2 つのエンドポイントを使い分ける。

### 単一宛先：`POST /agents/{id}/context`

- 1 エージェントへの問い合わせ専用。body に scope を持たない。
- Banto は対象エージェントの `/context` へ素通し転送し、返値をそのまま返す。
- 個別 timeout を適用する。

問い合わせフォーマット（案）：

```json
{
  "query": "string",
  "format": "summary | raw"
}
```

### 複数宛先 fan-out：`POST /context`

- 複数エージェントへの同時問い合わせ用。body の `scope` で対象を指定する。
- `scope` は 1 件以上を許可する。1 件の場合も fan-out endpoint として一様に処理し、結果は常に配列で返す。`POST /agents/{id}/context` への誘導や 400 応答はしない。呼ぶ側に scope の件数による経路分岐を強いないため。
- Banto は並列に fan-out し、結果を**マージせず配列で返す**。統合はリクエスト元の責務。
- 個別 timeout と全体 timeout の両方を適用する。間に合わなかったエージェントは結果配列に状態つきで含める。

問い合わせフォーマット（案）：

```json
{
  "query": "string",
  "scope": ["agent_id_1", "agent_id_2"],
  "format": "summary | raw"
}
```

fan-out レスポンス（案）：

```json
{
  "results": [
    {"agent": "agent_id_1", "status": "ok", "response": { }},
    {"agent": "agent_id_2", "status": "timeout"}
  ]
}
```

## 登録フォーマット（案）

```json
{
  "agent_id": "string",
  "endpoint": "https://...",
  "heartbeat_interval_sec": 0,
  "down_threshold_sec": 0,
  "subscribe": [
    {"type": "banto.agent_down", "target": "agent-b"},
    {"type": "external.sync_failed"}
  ]
}
```

- `heartbeat_interval_sec`: エージェントがハートビートを打つ間隔。
- `down_threshold_sec`: この秒数ハートビートが途絶えたら agent_down とみなす。Banto は機械的な時間判定にのみ使う。
- `subscribe`: 受信したいイベント条件。type は必須、target は任意。完全一致照合のみ。
- `endpoint`: 配信・転送先 URL。allowlist 合致が必須（下記）。

## セキュリティ

### SSRF 対策（初期版必須）

- Banto は register で受けた任意 endpoint へ配信・転送するため、SSRF の踏み台になりうる。これを構造的に防ぐ。
- endpoint は allowlist（特定ホスト / CIDR、またはスキーム + ポート制限）に合致する宛先のみ登録可能とする。
- メタデータエンドポイント（169.254.169.254 等）、loopback、内部レンジへの配信はデフォルト拒否。
- 開発時のみ `BANTO_ALLOW_LOCALHOST=true` のような起動フラグで loopback を明示 opt-in する。本番設定ではこのフラグは立てない。フラグなしで内部レンジへ通る経路は作らない。
- これは「何を配るか」のドメイン判断ではなく「どこへなら配ってよいか」の安全境界設定であり、判断しない原則とは独立する。

### 認証（初期版）

- `POST /register` はデフォルトで `BANTO_REGISTER_TOKEN` による bearer 認証を必須とする。
- 開発時のみ `BANTO_ALLOW_OPEN_REGISTER=true` のような起動フラグで open registration を明示 opt-in できる。本番設定ではこのフラグは立てない。
- register 成功時に agent ごとの共有トークン（bearer）を発行する。
- `POST /heartbeat` と `POST /events` の発行元を agent token で縛る。
- mTLS は初期版では過剰、無認証は SSRF と絡んで危険なため採らない。

### timeout

- event / context fan-out はいずれも個別 timeout と全体 timeout を持つ。
- 個別 timeout: 一つの遅い配信先が他を巻き込まないため。各配信先に独立適用。
- 全体 timeout: fan-out 全体の上限。発行元のリクエストが青天井で待たされるのを防ぐ。
- 全体 timeout 到達時、未完了の配信先は failed に `global_timeout` として含めて打ち切り、部分結果を返す。

## 将来の拡張方向

- 新規エージェント追加時は Banto 通信インターフェース（`/context`・`/event`）を実装するだけで参加可能。
- 外部ツールは MCP サーバーとして Banto に接続。
- IoT や物理デバイスも Banto 通信インターフェース互換で接続。
- 外部 agent との標準的な task collaboration が必要になった場合は、Banto 本体を拡張せず、各 agent の A2A endpoint または Banto 外部の adapter で扱う。
- policy / approval / prompt inspection が必要になった場合は、Banto を賢くするのではなく、専用 agent または gateway を接続する。

## 今後の検討事項

以下は実装後・運用フェーズで詰める事項。

- agent_down 検出後の配信タイミング：受動評価で検出した直後に即時配信するか、heartbeat 処理のレスポンスとは別に配信するか（実装詳細）。
- registry・heartbeat cache の永続化（初期版はメモリのみだが、運用次第で再検討）。永続化は Banto の保持状態を増やす方向への圧力になる点に注意。
- subscription の更新・削除 API（登録後の変更をどう扱うか）。
- イベント発行のレート制限・バックプレッシャー（発行元が大量発行した場合の Banto の挙動）。
- allowlist の設定・更新方法（静的設定か、動的更新を許すか）。
- 受動評価の死角を埋める能動評価の駆動源（Banto 自身の生存監視・外部ヘルスチェック等。導入は将来検討）。

## 参考

- MCP は外部ツール接続にのみ使用し、Banto 内部通信には使用しない。
- A2A は外部 agent との相互運用・task delegation・collaboration が必要な場合の候補であり、Banto 本体の責務ではない。
