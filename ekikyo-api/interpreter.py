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
# 4パート（本卦300-400字＋動爻150-250字＋之卦150-250字＋捉え方150-250字＝最大~1150字）＋
# JSON枠を、日本語トークンで途中切断させない余裕を持たせる。出力課金は生成分のみなので、
# 上限を上げても通常コストは変わらない（長さは system 指示で抑える）。
MAX_TOKENS = 3072
TEMPERATURE = 0.7

# 構造化出力スキーマ。4キーをすべて必須にして有効なJSONをモデル側で保証させる。
# これにより _parse_json のコードフェンス剥がし／ブレース抽出が不要になり、
# キー欠落（shika だけ落ちる等）も構造的に防げる。
# yao_interpretation / shika_interpretation は変爻が無いとき空文字 "" を入れる
# （キー自体は必須）。yao は爻辞データが未整備の卦でも "" にする。
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "honka_interpretation": {"type": "string"},
        "yao_interpretation": {"type": "string"},
        "shika_interpretation": {"type": "string"},
        "advice": {"type": "string"},
    },
    "required": ["honka_interpretation", "yao_interpretation", "shika_interpretation", "advice"],
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

与えられた情報（問い・本卦・変爻とその爻辞・之卦）と、後段の六十四卦リファレンスを
踏まえて、次の4つを日本語で書いてください。

1. honka_interpretation … 本卦が示す「いまの景色」。問いがあるなら、その問いの状況に
   重ねて描く。300〜400字程度。
2. yao_interpretation … 動いている爻（変爻）の爻辞が指す「いま動いているところ・転機」。
   ユーザーには既に爻辞の原文と一般的な意味が示されているので、ここではそれを言い換えて
   繰り返すのではなく、その爻が「この問い・この状況」にとって何を意味するかに絞って読む。
   複数の変爻があるときは、全体を貫く一つの流れとしてまとめる。150〜250字程度。
   変爻が無い場合、または爻辞が与えられていない場合は、必ず空文字 "" にすること。
3. shika_interpretation … 之卦（変化先）が示す「これから向かう方向性」。問いがあるなら、
   問いに照らした変化として描く。150〜250字程度。変爻が無い場合は必ず空文字 "" にすること。
4. advice … 問いに対する「捉え方の提案」。150〜250字程度。問いが無い場合は本卦のみに基づく。

本卦→動爻→之卦→捉え方、という流れが自然につながるように書いてください。各項目は上記の
字数を目安に、過不足なく。出力フォーマットは構造化出力スキーマで honka_interpretation /
yao_interpretation / shika_interpretation / advice の4キーに固定されています。
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


def _moving_yao(honka_name, changing_lines):
    """変爻に対応する爻辞 [{name,text,meaning}] を返す。爻辞データが未整備の卦では [] を返す。
    全6爻が動くときは古典の考変占に従い、用九/用六があれば（乾・坤）それを出し、無ければ
    個々の爻辞ではなく之卦で読むため [] を返す（呼び出し側で yao を "" に倒す）。"""
    h = HEXAGRAMS.get(honka_name) or {}
    yao_lines = h.get("lines")
    if not yao_lines:
        return []
    positions = sorted({n for n in (changing_lines or []) if isinstance(n, int) and 1 <= n <= 6})
    if len(positions) == 6:
        return [h["yong"]] if h.get("yong") else []
    return [yao_lines[p - 1] for p in positions if 1 <= p <= len(yao_lines)]


def _build_user_block(question, honka_name, honka_lower, honka_upper, changing_lines, shika_name, moving):
    """キャッシュ対象外（messages 側）の可変ブロック。問い・本卦・動爻の爻辞・之卦を並べる。
    爻辞の原文/意味はサーバ側マスタ（HEXAGRAMS）由来なので、クライアントは信用しない。"""
    parts = []
    q = (question or "").strip()
    parts.append(f"問い：{q if q else '（特に問いは立てていない）'}")
    parts.append(f"本卦：{honka_name}（下卦={honka_lower}／上卦={honka_upper}）")
    # 之卦は shika_name があるときだけ書く（main側で「変爻⇔之卦」を保証済みだが、
    # ここでも shika_name を基準にして文字列 'None' の混入を防ぐ）。
    if shika_name:
        positions = sorted({n for n in (changing_lines or []) if isinstance(n, int) and 1 <= n <= 6})
        pos = "、".join(str(n) for n in positions)
        parts.append(f"変爻の位置（下から1〜6で数える）：{pos}")
        if moving:
            parts.append("動爻の爻辞（原文と一般的な意味。これを問いに引きつけて読む）：")
            for m in moving:
                parts.append(f"・{m['name']}　{m['text']}（{m['meaning']}）")
        elif len(positions) == 6:
            parts.append(
                "全6爻が動いている。個々の爻辞ではなく之卦で全体を読む作法のため、"
                "yao_interpretation は \"\" にし、之卦の解釈に重きを置くこと。"
            )
        else:
            parts.append("※この卦の爻辞は未整備。yao_interpretation は \"\" で返すこと。")
        parts.append(f"之卦（変爻を反映した変化先）：{shika_name}")
    else:
        parts.append("変爻：なし（之卦は無い。yao_interpretation と shika_interpretation は \"\" で返すこと）")
    return "\n".join(parts)


def generate(question, honka_name, honka_lower, honka_upper, changing_lines, shika_name):
    """Claudeに解釈を生成させ {honka_interpretation, yao_interpretation, shika_interpretation,
    advice, yao_names} を返す。yao_names は動爻の名（例 ["九五"]）。変爻なし・未整備卦では []。"""
    # 変爻⇔之卦 は本来 main 側で保証されるが、ここでも shika_name を起点にして
    # 「之卦が無いのに動爻だけ出る」矛盾を構造的に防ぐ（呼び出し元が増えても壊れない）。
    moving = _moving_yao(honka_name, changing_lines) if shika_name else []
    user_block = _build_user_block(
        question, honka_name, honka_lower, honka_upper, changing_lines, shika_name, moving
    )

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
        # 構造化出力で有効なJSON（4キー）を保証させる。messages 側に置くので
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
    parsed = _parse_json(text)
    parsed["yao_names"] = [m["name"] for m in moving]
    return parsed


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
        "yao_interpretation": data.get("yao_interpretation", ""),
        "shika_interpretation": data.get("shika_interpretation", ""),
        "advice": data.get("advice", ""),
    }
