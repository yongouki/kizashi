# ekikyo-api

易経コイン占いサイト「兆 kizashi」のAI解釈バックエンド（FastAPI）。
フロントから本卦・之卦・問いを受け取り、Claude (Haiku 4.5) に解釈文を生成させて返す。

## 構成

| ファイル | 役割 |
|----------|------|
| `main.py` | FastAPIアプリ本体・エンドポイント（`/api/divine`, `/health`） |
| `hexagrams.py` | 64卦マスタ（`tools/gen_hexagrams.js` で `../hexdata.js` から自動生成） |
| `interpreter.py` | Claude呼び出し・プロンプト構築（プロンプトキャッシュ＋構造化出力） |
| `gatekeeper.py` | 門番（Cookieによる1日1回判定） |
| `tools/gen_hexagrams.js` | 64卦マスタの再生成スクリプト（Node、ビルド時のみ） |

## ローカル起動

```bash
cd ekikyo-api
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # .env を編集して ANTHROPIC_API_KEY を入れる
uvicorn main:app --reload
```

`GET http://127.0.0.1:8000/health` → `{"status":"ok"}` が返れば起動成功。

## 動作確認（curl）

本卦のみ（変爻なし）の例。Cookieをファイルに保存して1日1回判定も確認できる。

```bash
curl -i -X POST http://127.0.0.1:8000/api/divine \
  -H "Content-Type: application/json" \
  -c cookies.txt -b cookies.txt \
  -d '{
        "question": "この仕事の方向性はどうか",
        "hexagram": {"name": "水雷屯", "lower": "震", "upper": "坎"},
        "changing_lines": [1, 4],
        "future_hexagram": {"name": "水地比", "lower": "坤", "upper": "坎"}
      }'
```

- 同じ `cookies.txt` で2回目を叩くと `429`（`DAILY_LIMIT=1` のとき）。
- `DAILY_LIMIT=0` で起動すると無制限（門番無効）。
- 存在しない卦名を送ると `400`。

## 卦マスタの再生成

`../hexdata.js` を変更したら、フロントと整合させるため再生成する:

```bash
# リポジトリのルートから
node ekikyo-api/tools/gen_hexagrams.js .
```

## プロンプトキャッシュの確認

`interpreter.py` は固定部分（トーン指示＋64卦リファレンス）を `system` に入れ
`cache_control` でキャッシュする。`claude-haiku-4-5` のキャッシュ最小長は **4,096トークン**
（Sonnet 4.6 の 2,048 から倍増）。固定部分がこれを下回るとキャッシュは無言で無効化される
（エラーは出ず `cache_creation_input_tokens=0` のまま）ため、モデル変更時は count_tokens で
固定部分のトークン数を実測すること。サーバログに毎回 usage を出力するので、
2回目以降 `cache_read > 0` になっていればキャッシュが効いている。

## Renderへのデプロイ

`render.yaml` でWeb Serviceを作成し、ダッシュボードで以下を設定:

- `ANTHROPIC_API_KEY`（必須）
- `ALLOWED_ORIGINS`（フロントのオリジン。例 `https://yongouki.github.io`）
- `DAILY_LIMIT`（`1`）

`$PORT` はRenderが注入する。HTTPSなのでクロスサイトCookie（`SameSite=None; Secure`）も動く。

> 注意: クロスサイトCookieはSafari/Brave等で標準ブロックされるため、実用上の「1日1回」は
> フロント側の localStorage(`kz_ai_date`) が主に担う。詳細は `gatekeeper.py` のコメント参照。
