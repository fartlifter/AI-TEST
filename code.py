import streamlit as st
import requests
import httpx
from bs4 import BeautifulSoup
from datetime import datetime, date, time as dtime
from zoneinfo import ZoneInfo
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import time as t

# =====================================================
# 🔐 Gemini API 설정
# =====================================================
GEMINI_API_KEY = "AIzaSyAuFdphgr2zwl_6ddzjdqjFjvFdkcA5Yf4"

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-1.5-pro:generateContent"
)

SUMMARY_SYSTEM_PROMPT = """
📘 기사 요약 방식 설명
<요약 형식>
입력 기사 내용에 따라 다음 두 가지 형식을 사용:

1.
△매체/기사제목 기사본문 형식의 경우:
△매체/기사제목  
-개조식 요약 문장. 사실 단위로 구분해 마침표로 연결. 첫머리는 반드시 하이픈(-)으로 시작.

2.
△기사제목 기사본문 형식의 경우:
△기사제목  
-개조식 요약 문장. 위와 동일하게 처리.

***△ 다음 매체명 없이 바로 제목 나오는 경우엔 매체명 쓰지 않음! 
***매체명이 제목이 아니라, 본문에만 있는 경우는 매체명 쓰지 않음!

<규칙>
-문장 시작은 항상 - 하이픈으로 시작 (띄어쓰기 없이 바로 서술 시작)
-제목과 본문 사이에만 줄바꿈. 나머지 문장은 마침표(.)로 구분해 줄바꿈 없이 나열
-첫 문장은 반드시 다음 구성 순서를 따름:
① 기사에서 말하는 내용의 주체 + ② 주격조사 생략하고 쉼표(,) 사용 + ③ 어미는 '-다'가 아닌 평서형으로 끝맺음 (예: '밝혔다' 대신 '밝혀') + ④ 마침표로 종료
-이후 문장에서는 일반적인 조사 사용 가능
-서술어 어미는 평서형으로만 작성하고, '~함' 체(명사형 어미)는 사용하지 않음
-중복 표현, 수사, 감성적 표현 제거
-명확한 주어와 사건의 핵심 정보(일시, 인물, 장소, 배경 등) 반드시 포함
-가능한 한 구체적인 수치와 고유명사 포함
-불필요한 접속사, 인용 부호, 조사 생략

<예시>
△인권위, 3년여 우여곡절 끝 ‘수요시위 방해 중단’ 인용 결정  
-인권위, 2일 경찰이 수요시위 방해행위 막아야 한다는 취지로 진정 사건 인용 결정. 앞서 인권위는 같은 진정을 법적 근거 없이 기각했으나 3년 만에 입장 바꿔. 
"""

def summarize_with_gemini(title, body, source=None):
    if not GEMINI_API_KEY:
        return "- Gemini API 키 없음"

    full_title = f"△{source}/{title}" if source else f"△{title}"

    prompt = f"""{full_title}

[기사 본문]
{body}
"""

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": SUMMARY_SYSTEM_PROMPT + "\n\n" + prompt}]
            }
        ]
    }

    try:
        res = requests.post(
            GEMINI_ENDPOINT,
            params={"key": GEMINI_API_KEY},
            json=payload,
            timeout=25
        )
        res.raise_for_status()
        return res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return f"- 요약 실패: {e}"

# =====================================================
# 📺 Streamlit 기본 UI
# =====================================================
st.set_page_config(page_title="단독·통신기사 수집기", layout="wide")
st.title("📰 단독·통신기사 수집기")
st.caption("세계일보 경찰팀 라인별 보고용")

# =====================================================
# ⏰ 날짜/시간
# =====================================================
now = datetime.now(ZoneInfo("Asia/Seoul"))
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("시작 날짜", value=now.date())
    start_time = st.time_input("시작 시각", value=dtime(0, 0))
with col2:
    end_date = st.date_input("종료 날짜", value=now.date())
    end_time = st.time_input("종료 시각", value=dtime(now.hour, now.minute))

start_dt = datetime.combine(start_date, start_time).replace(tzinfo=ZoneInfo("Asia/Seoul"))
end_dt = datetime.combine(end_date, end_time).replace(tzinfo=ZoneInfo("Asia/Seoul"))

# =====================================================
# ☑ 기능 선택
# =====================================================
collect_wire = st.checkbox("통신기사", value=True)
collect_naver = st.checkbox("단독기사", value=True)

# =====================================================
# 🧠 세션 상태
# =====================================================
if "wire_articles" not in st.session_state:
    st.session_state.wire_articles = []
if "naver_articles" not in st.session_state:
    st.session_state.naver_articles = []

# =====================================================
# 🔎 통신기사 (연합·뉴시스)
# =====================================================
def get_content(url, selector):
    try:
        res = httpx.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(res.text, "html.parser")
        el = soup.select_one(selector)
        return el.get_text("\n", strip=True) if el else ""
    except:
        return ""

def parse_newsis():
    collected, page = [], 1
    while True:
        url = f"https://www.newsis.com/society/list/?cid=10200&scid=10201&page={page}"
        res = httpx.get(url, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select("ul.articleList2 > li")
        if not items:
            break

        for it in items:
            title_tag = it.select_one("p.tit a")
            time_tag = it.select_one("p.time")
            if not title_tag or not time_tag:
                continue

            match = re.search(r"\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}", time_tag.text)
            if not match:
                continue

            dt = datetime.strptime(
                match.group(), "%Y.%m.%d %H:%M:%S"
            ).replace(tzinfo=ZoneInfo("Asia/Seoul"))

            if dt < start_dt:
                return collected

            if start_dt <= dt <= end_dt:
                link = "https://www.newsis.com" + title_tag["href"]
                collected.append({
                    "source": "뉴시스",
                    "title": title_tag.text.strip(),
                    "url": link,
                    "datetime": dt,
                    "content": get_content(link, "div.viewer")
                })
        page += 1
    return collected

# =====================================================
# 🔎 네이버 단독기사
# =====================================================
NAVER_CLIENT_ID = "R7Q2OeVNhj8wZtNNFBwL"
NAVER_CLIENT_SECRET = "49E810CBKY"

def naver_fetch():
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }

    results = []
    for start in range(1, 1001, 100):
        params = {
            "query": "[단독]",
            "display": 100,
            "start": start,
            "sort": "date"
        }
        res = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers=headers,
            params=params,
            timeout=5
        )
        if res.status_code != 200:
            break

        for item in res.json().get("items", []):
            link = item.get("link")
            if not link or "n.news.naver.com" not in link:
                continue

            pub_dt = datetime.strptime(
                item["pubDate"], "%a, %d %b %Y %H:%M:%S %z"
            ).astimezone(ZoneInfo("Asia/Seoul"))

            if not (start_dt <= pub_dt <= end_dt):
                continue

            html = requests.get(link, timeout=5)
            soup = BeautifulSoup(html.text, "html.parser")
            title = soup.select_one("h2#title_area")
            body = soup.select_one("div#newsct_article")

            if not title or not body:
                continue

            results.append({
                "매체": item["originallink"].split("//")[1].split("/")[0],
                "제목": title.text.strip(),
                "본문": body.get_text("\n", strip=True),
                "링크": link
            })
    return results

# =====================================================
# ▶ 기사 수집
# =====================================================
if st.button("✅ 기사 수집 시작"):
    if collect_wire:
        st.session_state.wire_articles = parse_newsis()
        st.success(f"통신기사 {len(st.session_state.wire_articles)}건")

    if collect_naver:
        st.session_state.naver_articles = naver_fetch()
        st.success(f"단독기사 {len(st.session_state.naver_articles)}건")

# =====================================================
# 🖨 결과 출력 + Gemini 요약
# =====================================================
if collect_wire and st.session_state.wire_articles:
    st.header("◆통신기사")
    selected = []

    for i, art in enumerate(st.session_state.wire_articles):
        with st.expander(art["title"]):
            if st.checkbox("이 기사 선택", key=f"wire_{i}"):
                selected.append(art)

    if selected:
        st.subheader("📋 복사용 텍스트 (요약)")
        text = "【사회면】\n"
        for a in selected:
            text += summarize_with_gemini(
                a["title"], a["content"], a["source"]
            ) + "\n\n"
        st.code(text.strip(), language="markdown")

if collect_naver and st.session_state.naver_articles:
    st.header("◆단독기사")
    selected = []

    for i, art in enumerate(st.session_state.naver_articles):
        with st.expander(f"{art['매체']}/{art['제목']}"):
            if st.checkbox("이 기사 선택", key=f"naver_{i}"):
                selected.append(art)

    if selected:
        st.subheader("📋 복사용 텍스트 (요약)")
        text = "【타지】\n"
        for a in selected:
            text += summarize_with_gemini(
                a["제목"], a["본문"], a["매체"]
            ) + "\n\n"
        st.code(text.strip(), language="markdown")
