# -*- coding: utf-8 -*-
"""AI解釈生成 — Claude (Sonnet 4.6) 呼び出しとプロンプト構築。

コスト最適化の核はプロンプトキャッシュ。固定部分（トーン指示＋64卦リファレンス）を
`system` 配列の1ブロックにまとめ、cache_control を付けてキャッシュする。
ユーザーごとに変わる部分（問い・卦）は messages 側に置きキャッシュ対象外にする。

注意: claude-sonnet-4-6 のキャッシュ最小プレフィックスは 2,048 トークン。
固定部分に64卦リファレンスを含めることでこの閾値を確実に超えさせている。
"""
import json
import logging
import re

from anthropic import Anthropic

from hexagrams import HEXAGRAMS

log = logging.getLogger("ekikyo")

MODEL = "claude-sonnet-4-6"
# 3パート（本卦300-400字＋之卦150-250字＋捉え方150-250字＝最大~900字）＋JSON枠を
# 日本語トークンで途中切断させない余裕を持たせる。出力課金は生成分のみなので、
# 上限を上げても通常コストは変わらない（長さは system 指示で抑える）。
MAX_TOKENS = 2048
TEMPERATURE = 0.7

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

与えられた情報（問い・本卦・変爻・之卦）と、後段の六十四卦リファレンスを踏まえて、
次の3つを日本語で書いてください。

1. honka_interpretation … 本卦が示す「いまの景色」。300〜400字程度。
2. shika_interpretation … 之卦（変化先）が示す「これから向かう方向性」。150〜250字程度。
   変爻が無い場合は必ず空文字 "" にすること。
3. advice … 問いに対する「捉え方の提案」。150〜250字程度。問いが無い場合は本卦のみに基づく。

出力は、必ず次のJSON「のみ」を返してください。前置き・後置き・説明文・
Markdownのコードフェンス（```）は一切付けないこと。

{"honka_interpretation": "...", "shika_interpretation": "...", "advice": "..."}
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
    """AI出力をJSONとして取り出す。コードフェンスや前後テキストが付いても耐える。"""
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    # 最外のJSONオブジェクトだけを取り出す
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        s = s[start:end + 1]
    data = json.loads(s)  # 失敗時は呼び出し側で500に変換しログを残す
    return {
        "honka_interpretation": data.get("honka_interpretation", ""),
        "shika_interpretation": data.get("shika_interpretation", ""),
        "advice": data.get("advice", ""),
    }
