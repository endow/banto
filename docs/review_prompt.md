# レビュープロンプト

Banto の実装レビューでは、まず `docs/design.md` の Banto 要求仕様書を正として扱う。

レビューは「Banto が賢くなっていないか」「配送に必要な状態だけを持っているか」「安全境界が緩んでいないか」を中心に行う。

## レビュー方針

- 設計書の不変条件 1〜19 との整合を最優先で確認する。
- Banto は自分が管理する local / private agent 群のための薄い hub であり、汎用 agent protocol や A2A 代替ではないものとして確認する。
- Banto が event の `type` / `payload` / context query / response の意味を解釈していないか確認する。
- Banto がオーケストレーター、ルールエンジン、監視主体になっていないか確認する。
- 仕様からの逸脱は、実装都合ではなく仕様変更候補として扱う。
- 指摘は、バグ、セキュリティ、仕様逸脱、テスト不足、保守性の順で整理する。

## 必須確認項目

### 判断しない構造

- event `type` / `payload` を条件分岐や意味判断に使っていないか。
- context query / response を要約、マージ、分類、解釈していないか。
- subscription matching が `type` / `target` の完全一致を超えていないか。
- 範囲比較、正規表現、OR/NOT、優先度判断などのルールエンジン化が入っていないか。
- stateful task lifecycle、capability discovery、streaming、artifact、交渉など、A2A が扱う領域を Banto 本体に入れていないか。
- prompt inspection、Human-in-the-Loop、policy 判断を Banto 本体の責務にしていないか。

### 状態保持

- Banto の保持状態が `agent registry`, `subscription table`, `heartbeat status cache` を実質的に超えていないか。
- event retry queue、配信済み event_id 履歴、context cache、ドメイン状態を追加していないか。
- registry / heartbeat cache が初期版で永続化されていないか。

### polling / agent_down

- Banto が agent `/status` を叩く経路を持っていないか。
- agent_down 検出のための自律 scan timer が入っていないか。
- agent_down 判定が `last_heartbeat_at + down_threshold_sec < now` を超えていないか。
- `last_heartbeat_at == null` の agent を down 扱いしていないか。
- down の重複通知が不必要に連続しないか。

### REST API

- `POST /register` が registration token 必須をデフォルトにしているか。
- open registration は `BANTO_ALLOW_OPEN_REGISTER=true` の明示 opt-in のみか。
- `POST /heartbeat` は agent token と `agent_id` の一致を確認しているか。
- `POST /events` は agent token と `source` の一致を確認しているか。
- `POST /agents/{id}/context` は単一宛先専用で、body に `scope` を要求していないか。
- `POST /context` は `scope` 1 件以上を許可し、常に配列で返しているか。

### Event fan-out

- event 配信は synchronous fan-out か。
- 成功時は `200 OK` で `delivered` / `failed` を返しているか。
- 部分失敗を HTTP 4xx/5xx で返していないか。
- retry queue や自動再送を持っていないか。
- `notify_to` が明示されている場合はそれを優先しているか。
- `notify_to` が空の場合のみ subscription table で配信先を解決しているか。
- 配信失敗 reason が仕様範囲内か。
  - `timeout`
  - `connection_refused`
  - `transport_error`
  - `redirect_error`
  - `http_5xx`
  - `http_4xx`
  - `global_timeout`

### Context fan-out

- Banto が response をマージしていないか。
- 結果を agent ごとの配列として返しているか。
- `not_found`, `timeout`, `http_error`, `invalid_response`, `global_timeout` が個別結果として返るか。
- 単一 context の timeout / connection error が FastAPI の未処理 500 になっていないか。

### SSRF / endpoint validation

- register endpoint が allowlist に合致する宛先だけを許可しているか。
- hostname と IP literal の両方で allowlist が効いているか。
- public IP literal が allowlist なしで通らないか。
- loopback / localhost はデフォルト拒否か。
- localhost は `BANTO_ALLOW_LOCALHOST=true` の明示 opt-in のみか。
- redirect を自動追跡して allowlist 外へ出ていないか。

### Timeout

- event fan-out と context fan-out が個別 timeout と全体 timeout を持っているか。
- 全体 timeout 到達時に未完了の配信先 / 問い合わせ先が `global_timeout` として返るか。
- 一つの遅い agent が全体を無制限に待たせないか。

## テスト観点

最低限、次を確認するテストがあること。

- register token 必須、open registration opt-in。
- heartbeat / events の token 不一致拒否。
- endpoint allowlist と localhost opt-in。
- public IP literal の拒否。
- event notify_to fan-out と subscription fan-out。
- event partial result。
- event failure reason 全種。
- context 単一転送。
- context fan-out scope 1 件許可。
- context fan-out の `not_found`, `timeout`, `http_error`, `invalid_response`, `global_timeout`。
- passive agent_down。
- unknown agent は agent_down 対象外。
- 再登録時の token / heartbeat state 維持と routing 情報更新。

## レビュー出力形式

レビュー結果は以下の順で書く。

1. 全体評価
2. バグ
3. セキュリティ懸念
4. 仕様逸脱
5. テスト不足
6. 保守性の懸念
7. 問題なしとして確認できた点

各指摘には、該当ファイル、該当箇所、期待挙動、実際の挙動、修正案を含める。
