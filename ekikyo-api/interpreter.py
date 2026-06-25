# -*- coding: utf-8 -*-
"""AI解釈生成 — Claude (Haiku 4.5) 呼び出しとプロンプト構築。

コスト最適化の核はプロンプトキャッシュ。固定部分（トーン指示＋64卦リファレンス）を
`system` 配列の1ブロックにまとめ、cache_control を付けてキャッシュする。
ユーザーごとに変わる部分（問い・卦）は messages 側に置きキャッシュ対象外にする。

注意: claude-haiku-4-5 のキャッシュ最小プレフィックスは 4,096 トークン
（Sonnet 4.6 の 2,048 から倍増）。固定部分（SYSTEM_INSTRUCTION＋64卦リファレンス）が
この閾値を超えていないとキャッシュが静かに無効化されるため、モデル変更時は
count_tokens で固定部分のトークン数を実測し、4,096 を超えているか確認すること。
超えない場合はリファレンスを増やすか、キャッシュ前提を見直す。
"""
import json
import logging

from anthropic import Anthropic

from hexagrams import HEXAGRAMS

log = logging.getLogger("ekikyo")

MODEL = "claude-haiku-4-5"
# 3パート（本卦300-400字＋之卦150-250字＋捉え方150-250字＝最大~900字）＋JSON枠を
# 日本語トークンで途中切断させない余裕を持たせる。出力課金は生成分のみなので、
# 上限を上げても通常コストは変わらない（長さは system 指示で抑える）。
MAX_TOKENS = 2048
TEMPERATURE = 0.7

# 構造化出力スキーマ。3キーをすべて必須にして有効なJSONをモデル側で保証させる。
# これにより _parse_json のコードフェンス剥がし／ブレース抽出が不要になり、
# キー欠落（shika だけ落ちる等）も構造的に防げる。
# shika_interpretation は変爻が無いとき空文字 "" を入れる（キー自体は必須）。
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "honka_interpretation": {"type": "string"},
        "shika_interpretation": {"type": "string"},
        "advice": {"type": "string"},
    },
    "required": ["honka_interpretation", "shika_interpretation", "advice"],
    "additionalProperties": False,
}

# クライアントは遅延生成（起動時にAPIキー必須にしない／テストしやすくするため）。
_client = None


def _client_get() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic()  # ANTHROPIC_API_KEY を環境変数から読む
    return _client


SYSTEM_INSTRUCTION = """\
あなたは、易経（易）の「考え方」に基づいて、いまの状況を静かに読み解く案内役です。

スタンス:
- 未来を「当てる占い」ではなく、現状の「捉え方を提案する」立場をとります。
- 断定を避け、「〜という見方もできる」「〜と捉えると」という余白を残します。
- 陰陽五行の専門用語を多用せず、易を知らない人にも開かれた言葉で語ります。
- 文体は丁寧だが説教くさくない。背筋が伸びるが、威圧しない。
- 本卦・之卦の景色は、卦そのものが持つ意味の格を保って描きます。ただし問いが
  立てられているときは、その問いの状況に引きつけて景色を描いてください
  （問いを無視した一般論で終わらせない）。問いが無いときは卦そのものを淡々と描きます。

与えられた情報（問い・本卦・変爻・之卦）と、後段の六十四卦リファレンスを踏まえて、
次の3つを日本語で書いてください。

1. honka_interpretation … 本卦が示す「いまの景色」。問いがあるなら、その問いの状況に
   重ねて描く。300〜400字程度。
2. shika_interpretation … 之卦（変化先）が示す「これから向かう方向性」。問いがあるなら、
   問いに照らした変化として描く。150〜250字程度。変爻が無い場合は必ず空文字 "" にすること。
3. advice … 問いに対する「捉え方の提案」。150〜250字程度。問いが無い場合は本卦のみに基づく。

各項目は上記の字数を目安に、過不足なく書いてください。出力フォーマットは構造化出力
スキーマで honka_interpretation / shika_interpretation / advice の3キーに固定されています。
"""


def _build_reference() -> str:
    rows = []
    for name, h in HEXAGRAMS.items():
        kw = "・".join(h.get("keywords", []))
        rows.append(
            f"【{name}】（{h['reading']}）上卦={h['upper']}／下卦={h['lower']}　"
            f"{h['summary']}　キーワード：{kw}"
        )
    return "■ 六十四卦リファレンス（卦名・読み・上下の八卦・意味）\n" + "\n".join(rows)


# 固定プレフィックス（毎回同一）。これ全体を1ブロックでキャッシュする。
_CACHED_SYSTEM = SYSTEM_INSTRUCTION + "\n\n" + _build_reference()


def generate(question, honka_name, honka_lower, honka_upper, changing_lines, shika_name):
    """Claudeに解釈を生成させ {honka_interpretation, shika_interpretation, advice} を返す。"""
    lines = []
    q = (question or "").strip()
    lines.append(f"問い：{q if q else '（特に問いは立てていない）'}")
    lines.append(f"本卦：{honka_name}（下卦={honka_lower}／上卦={honka_upper}）")
    # 之卦は shika_name があるときだけ書く（main側で「変爻⇔之卦」を保証済みだが、
    # ここでも shika_name を基準にして文字列 'None' の混入を防ぐ）。
    if shika_name:
        pos = "、".join(str(n) for n in changing_lines)
        lines.append(f"変爻の位置（下から1〜6で数える）：{pos}")
        lines.append(f"之卦（変爻を反映した変化先）：{shika_name}")
    else:
        lines.append("変爻：なし（之卦は無い。shika_interpretation は \"\" で返すこと）")
    user_block = "\n".join(lines)

    resp = _client_get().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=[
            {
                "type": "text",
                "text": _CACHED_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_block}],
        # 構造化出力で有効なJSON（3キー）を保証させる。messages 側に置くので
        # system のキャッシュ・プレフィックスには影響しない。
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )

    u = resp.usage
    # キャッシュが効いているか確認するためのログ（2回目以降 cache_read > 0 を期待）。
    log.info(
        "claude usage: input=%s cache_creation=%s cache_read=%s output=%s",
        getattr(u, "input_tokens", None),
        getattr(u, "cache_creation_input_tokens", None),
        getattr(u, "cache_read_input_tokens", None),
        getattr(u, "output_tokens", None),
    )
    if getattr(resp, "stop_reason", None) == "max_tokens":
        log.warning("claude response hit max_tokens; output may be truncated (consider raising MAX_TOKENS)")

    text = "".join(
        b.text for b in resp.content if getattr(b, "type", None) == "text"
    )
    return _parse_json(text)


def _parse_json(text: str) -> dict:
    """構造化出力により有効なJSONが返る前提でパースする。失敗しうるのは max_tokens での
    途中切断など異常時のみ。その場合はモデルの生出力をログに残してから例外を投げ、
    呼び出し側で500に変換させる（何が返って落ちたかを後から追えるようにするため）。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.error("failed to parse model JSON output (truncated?); raw=%r", text)
        raise
    return {
        "honka_interpretation": data.get("honka_interpretation", ""),
        "shika_interpretation": data.get("shika_interpretation", ""),
        "advice": data.get("advice", ""),
    }
