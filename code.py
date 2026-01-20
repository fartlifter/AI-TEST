import streamlit as st
import requests
import httpx
import google.generativeai as genai
from bs4 import BeautifulSoup
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import re

# =====================================================
# Gemini API (요청대로 코드에 직접 유지)
# =====================================================
GEMINI_API_KEY = "AIzaSyAuFdphgr2zwl_6ddzjdqjFjvFdkcA5Yf4"

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

# =====================================================
# 요약 규칙 프롬프트
# =====================================================
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

# =====================================================
# 요약 캐시
# =====================================================
if "summary_cache" not in st.session_state:
    st.session_state.summary_cache = {}

def summarize_with_gemini(title, body, source=None, cache_key=None):
    if cache_key and cache_key in st.session_state.summary_cache:
        return st.session_state.summary_cache[cache_key]

    full_title = f"△{source}/{title}" if source else f"△{title}"

    prompt = f"""{SUMMARY_SYSTEM_PROMPT}

{full_title}

[기사 본문]
{body}
"""

    try:
        res = gemini_model.generate_content(prompt)
        summary = res.text.strip()
    except Exception as e:
        summary = f"{full_title}\n-요약 실패: {e}"

    if cache_key:
        st.session_state.summary_cache[cache_key] = summary

    return summary

# =====================================================
# Streamlit UI
# =====================================================
st.set_page_config(page_title="단독·통신기사 수집기", layout="wide")
st.title("📰 단독·통신기사 수집기")

# =====================================================
# 🔑 키워드 그룹 (FULL SET – 누락 없음)
# =====================================================
keyword_groups = {
    '시경': ['서울경찰청'],
    '본청': ['경찰청'],
    '종혜북': [
        '종로', '종암', '성북', '고려대', '참여연대', '혜화', '동대문', '중랑',
        '성균관대', '한국외대', '서울시립대', '경희대', '경실련', '서울대병원',
        '노원', '강북', '도봉', '북부지법', '북부지검',
        '상계백병원', '국가인권위원회'
    ],
    '마포중부': [
        '마포', '서대문', '서부', '은평', '서부지검', '서부지법', '연세대',
        '신촌세브란스병원', '군인권센터', '중부', '남대문', '용산', '동국대',
        '숙명여대', '순천향대병원'
    ],
    '영등포관악': [
        '영등포', '양천', '구로', '강서', '남부지검', '남부지법',
        '여의도성모병원', '고대구로병원', '관악', '금천', '동작', '방배',
        '서울대', '중앙대', '숭실대', '보라매병원'
    ],
    '강남광진': [
        '강남', '서초', '수서', '송파', '강동',
        '삼성의료원', '현대아산병원', '강남세브란스병원',
        '광진', '성동', '동부지검', '동부지법',
        '한양대', '건국대', '세종대'
    ]
}

# =====================================================
# 키워드 선택
# =====================================================
selected_groups = st.multiselect(
    "키워드 그룹 선택",
    options=list(keyword_groups.keys()),
    default=['시경', '종혜북']
)
selected_keywords = [kw for g in selected_groups for kw in keyword_groups[g]]

# =====================================================
# 시간 설정
# =====================================================
now = datetime.now(ZoneInfo("Asia/Seoul"))
col1, col2 = st.columns(2)
with col1:
    start_time = st.time_input("시작 시각", value=dtime(0, 0))
with col2:
    end_time = st.time_input("종료 시각", value=dtime(now.hour, now.minute))

# =====================================================
# 세션 상태 (기사 목록은 이미 채워진다는 전제)
# =====================================================
if "wire_articles" not in st.session_state:
    st.session_state.wire_articles = []
if "naver_articles" not in st.session_state:
    st.session_state.naver_articles = []

# =====================================================
# 통신기사 결과 출력
# =====================================================
st.header("◆통신기사")
selected_articles = []

for i, art in enumerate(st.session_state.wire_articles):
    with st.expander(art["title"]):
        is_selected = st.checkbox("이 기사 선택", key=f"wire_{i}")
        st.markdown(f"[원문 보기]({art['url']})")
        if is_selected:
            selected_articles.append(art)

if selected_articles:
    st.subheader("📋 복사용 텍스트")
    text_block = "【사회면】\n"
    for row in selected_articles:
        cache_key = f"wire::{row['url']}"
        summary = summarize_with_gemini(
            title=row["title"],
            body=row["content"],
            source=row.get("source"),
            cache_key=cache_key
        )
        text_block += summary + "\n\n"
    st.code(text_block.strip(), language="markdown")

# =====================================================
# 네이버 단독 결과 출력
# =====================================================
st.header("◆단독기사")
selected_naver_articles = []

for i, art in enumerate(st.session_state.naver_articles):
    with st.expander(f"{art['매체']}/{art['제목']}"):
        is_selected = st.checkbox("이 기사 선택", key=f"naver_{i}")
        st.markdown(f"[원문 보기]({art['링크']})")
        if is_selected:
            selected_naver_articles.append(art)

if selected_naver_articles:
    st.subheader("📋 복사용 텍스트")
    text_block = "【타지】\n"
    for row in selected_naver_articles:
        clean_title = re.sub(
            r"\[단독\]|\(단독\)|【단독】|ⓧ단독|^단독\s*[:-]?",
            "",
            row["제목"]
        ).strip()

        cache_key = f"naver::{row['링크']}"
        summary = summarize_with_gemini(
            title=clean_title,
            body=row["본문"],
            source=row["매체"],
            cache_key=cache_key
        )
        text_block += summary + "\n\n"

    st.code(text_block.strip(), language="markdown")
