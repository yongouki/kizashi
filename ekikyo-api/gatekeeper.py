# -*- coding: utf-8 -*-
"""門番（gatekeeper）— 1日1回の利用判定。

【既知の制約・PoC段階の割り切り】
このCookieベースの判定は、プライベートブラウジング・Cookie削除・
別ブラウザの使用で容易に回避できる。これはPoC段階では許容する。
理由：回避者は元々課金しない層であり、1回あたり原価は数円のため実害が小さい。
本番で本気の不正対策が必要になった段階で、ログイン（認証）必須に切り替える。
認証導入時、この門番ロジックはユーザーID基準のDBカウントに置き換える。

【さらに強い但し書き】
フロント(GitHub Pages, *.github.io)とAPI(Render, *.onrender.com)はドメインが
異なるため、ここで使うCookieは「サードパーティCookie」になる。Safari/Brave等は
これを標準でブロックし、Chromeも段階的に廃止しているため、Cookieが保存されず
判定が効かない環境が多い。そのため実用上の「1日1回」はフロント側の
localStorage(kz_ai_date)が主に担い、このCookieは補助という位置づけ。
"""
import os
from datetime import datetime, timezone, timedelta

# 日本時間（JST, UTC+9）。JSTはDSTを持たないので固定オフセットで厳密に正しい。
JST = timezone(timedelta(hours=9))

COOKIE_NAME = "ekikyo_last"
# Cookieの寿命は2日（日付の変わり目をまたいでも翌日には判定がリセットされる）。
COOKIE_MAX_AGE = 60 * 60 * 24 * 2


def daily_limit() -> int:
    """0=無制限（門番無効・開発用）、1=1日1回。"""
    try:
        return int(os.environ.get("DAILY_LIMIT", "1"))
    except (TypeError, ValueError):
        return 1


def today_str() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def is_blocked(request) -> bool:
    """今日すでに占っていれば True（=429で弾く）。DAILY_LIMIT=0なら常に False。"""
    if daily_limit() == 0:
        return False
    return request.cookies.get(COOKIE_NAME) == today_str()


def stamp(response) -> None:
    """成功レスポンスに「今日占った」印を付ける。
    クロスオリジンでCookieをやり取りするため SameSite=None; Secure が必須。"""
    response.set_cookie(
        key=COOKIE_NAME,
        value=today_str(),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )
