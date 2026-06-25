# -*- coding: utf-8 -*-
"""FastAPIアプリ本体・エンドポイント。

POST /api/divine : 卦データを受け取り、本卦・之卦・捉え方をAIが生成して返す。
GET  /health     : 死活監視用。
"""
import logging
import os
import re
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()  # ローカルは .env、本番(Render)は環境変数から読む

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import gatekeeper
import interpreter
from hexagrams import HEXAGRAMS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ekikyo")

app = FastAPI(title="ekikyo-api")

# ---- CORS ----------------------------------------------------------------
# allow_origins は環境変数 ALLOWED_ORIGINS（カンマ区切り）から。Cookieを使うため
# allow_credentials=True、ワイルドカード '*' は使わない（*と併用不可）。
_origins = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "https://yongouki.github.io").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


# ---- request schema ------------------------------------------------------
class Hexagram(BaseModel):
    name: str
    # 八卦の漢字1文字想定。長大入力（コスト増幅/注入）を弾く保険として上限を付ける。
    lower: str = Field(max_length=16)
    upper: str = Field(max_length=16)


class DivineRequest(BaseModel):
    question: Optional[str] = ""
    hexagram: Hexagram
    changing_lines: List[int] = Field(default_factory=list)
    future_hexagram: Optional[Hexagram] = None


# ---- endpoints -----------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/divine")
def divine(body: DivineRequest, request: Request):
    # (1) 本卦名の検証（64卦マスタに無ければ400）
    if body.hexagram.name not in HEXAGRAMS:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_hexagram", "message": "卦名が正しくありません。"},
        )

    # 変爻は 1〜6 の範囲だけ採用
    changing = sorted({n for n in (body.changing_lines or []) if isinstance(n, int) and 1 <= n <= 6})
    has_changing = bool(changing)

    # 変爻があるなら之卦(future_hexagram)が必須・正当であること（契約: 変爻⇔之卦）。
    # これにより has_changing_lines と shika の整合が崩れず、プロンプトへの 'None' 混入も防ぐ。
    shika_name = None
    if has_changing:
        if body.future_hexagram is None:
            return JSONResponse(
                status_code=400,
                content={"error": "missing_future", "message": "変爻があるときは之卦(future_hexagram)も必要です。"},
            )
        if body.future_hexagram.name not in HEXAGRAMS:
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_hexagram", "message": "之卦の卦名が正しくありません。"},
            )
        shika_name = body.future_hexagram.name

    # (2) 門番判定（1日1回）
    if gatekeeper.is_blocked(request):
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limited",
                "message": "今日はもう一度、同じ問いと向き合ってみてください。明日また占えます。",
            },
        )

    # (3) AI解釈生成
    # 問いは改行・余分な空白を畳んで200文字に丸める（プロンプト構造の汚染防止）。
    question = re.sub(r"\s+", " ", (body.question or "")).strip()[:200]
    # 上下の八卦はクライアント値を信用せず、マスタの正値を使う（コスト増幅/注入の遮断）。
    honka = HEXAGRAMS[body.hexagram.name]
    try:
        gen = interpreter.generate(
            question=question,
            honka_name=body.hexagram.name,
            honka_lower=honka["lower"],
            honka_upper=honka["upper"],
            changing_lines=changing,
            shika_name=shika_name,
        )
    except Exception:
        log.exception("interpretation generation failed")
        return JSONResponse(
            status_code=500,
            content={
                "error": "generation_failed",
                "message": "解釈の生成に失敗しました。もう一度お試しください。",
            },
        )

    # (4) 整形して返す（成功時のみ門番のCookieを更新）
    honka_reading = honka["reading"]
    payload = {
        "honka": {
            "name": body.hexagram.name,
            "reading": honka_reading,
            "interpretation": gen["honka_interpretation"],
        },
        "shika": (
            {"name": shika_name, "interpretation": gen["shika_interpretation"]}
            if (has_changing and shika_name)
            else None
        ),
        "advice": gen["advice"],
        "has_changing_lines": has_changing,
    }
    response = JSONResponse(content=payload)
    gatekeeper.stamp(response)
    return response
