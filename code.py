import streamlit as st
import requests
import httpx
from bs4 import BeautifulSoup
from datetime import datetime, date, time as dtime
from zoneinfo import ZoneInfo
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import time as t

# === 네이버 API 인증 정보 ===
client_id = "R7Q2OeVNhj8wZtNNFBwL"
client_secret = "49E810CBKY"

st.set_page_config(page_title="단독·통신기사 수집기", layout="wide")
st.title("📰 법조 단독·통신기사 수집기")
st.caption("세계일보 법조팀 보고를 도와줍니다. (만든이: 윤준호, 업데이트: 260412)")

# === 키워드 그룹 (공통) ===
keyword_groups = {
    '법원': ['서울중앙지법','서울고법','대법원','헌법재판소','대한변호사협회','서울지방변호사회','한국여성변호사회',
          '서울행정법원','서울가정법원','서울회생법원','법원행정처','특허법원','법무법인'],
    '검찰': ['서울중앙지검','서울고검','대검찰청','법무부','특검','고위공직자범죄수사처','합동수사본부','중수청','공소청','검찰','법제처']
}

now = datetime.now(ZoneInfo("Asia/Seoul"))
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("시작 날짜", value=now.date())
    start_time = st.time_input("시각", value=dtime(0, 0))
with col2:
    end_date = st.date_input("종료 날짜", value=now.date())
    end_time = st.time_input("종료 시각", value=dtime(now.hour, now.minute))

selected_groups = st.multiselect("키워드 그룹 선택", options=list(keyword_groups.keys()), default=['법원'])
selected_keywords = [kw for g in selected_groups for kw in keyword_groups[g]]

start_dt = datetime.combine(start_date, start_time).replace(tzinfo=ZoneInfo("Asia/Seoul"))
end_dt = datetime.combine(end_date, end_time).replace(tzinfo=ZoneInfo("Asia/Seoul"))

# === 기능 선택부 ===
collect_wire = st.checkbox("통신기사", value=True)
collect_naver = st.checkbox("단독기사", value=True)

# === 세션 상태 초기화 ===
if "wire_articles" not in st.session_state:
    st.session_state.wire_articles = []
for key in ["naver_articles", "naver_status_text", "naver_progress"]:
    if key not in st.session_state:
        st.session_state[key] = [] if key == "naver_articles" else 0 if key == "naver_progress" else ""

# === 통신기사 함수들 ===
def highlight_keywords(text, keywords):
    for kw in keywords:
        text = re.sub(f"({re.escape(kw)})", r'<mark style="background-color: #fffb91">\1</mark>', text)
    return text

def get_content(url, selector):
    try:
        with httpx.Client(timeout=5.0) as client:
            res = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(res.text, "html.parser")
            content = soup.select_one(selector)
            return content.get_text(separator="\n", strip=True) if content else ""
    except:
        return ""

def fetch_articles_concurrently(article_list, selector):
    results = []
    progress_bar = st.progress(0.0, text="본문 수집 중...")
    total = len(article_list)
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(get_content, art['url'], selector): art for art in article_list}
        for i, future in enumerate(as_completed(futures)):
            art = futures[future]
            try:
                content = future.result()
                if any(kw in content for kw in selected_keywords):
                    art['content'] = content
                    results.append(art)
            except:
                continue
            progress_bar.progress((i + 1) / total, text=f"{i+1}/{total} 기사 처리 완료")
    progress_bar.empty()
    return results

def parse_yonhap():
    collected, page = [], 1
    st.info("🔍 [연합뉴스] 기사 목록 수집 중...")
    while True:
        url = f"https://www.yna.co.kr/society/all/{page}"
        res = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5.0)
        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select("ul.list01 > li[data-cid]")
        if not items:
            break
        for item in items:
            cid = item.get("data-cid")
            title_tag = item.select_one(".title01")
            time_tag = item.select_one(".txt-time")
            if not (cid and title_tag and time_tag):
                continue
            try:
                dt = datetime.strptime(f"{start_dt.year}-{time_tag.text.strip()}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Seoul"))
            except:
                continue
            if dt < start_dt:
                return fetch_articles_concurrently(collected, "div.story-news.article")
            if start_dt <= dt <= end_dt:
                collected.append({
                    "source": "연합뉴스", "datetime": dt, "title": title_tag.text.strip(),
                    "url": f"https://www.yna.co.kr/view/{cid}"
                })
        page += 1
    return fetch_articles_concurrently(collected, "div.story-news.article")

def parse_newsis():
    collected, page = [], 1
    st.info("🔍 [뉴시스] 기사 목록 수집 중...")
    while True:
        url = f"https://www.newsis.com/society/list/?cid=10200&scid=10201&page={page}"
        res = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5.0)
        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select("ul.articleList2 > li")
        if not items:
            break
        for item in items:
            title_tag = item.select_one("p.tit > a")
            time_tag = item.select_one("p.time")
            if not (title_tag and time_tag):
                continue
            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "")
            match = re.search(r"\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}", time_tag.text)
            if not match:
                continue
            dt = datetime.strptime(match.group(), "%Y.%m.%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Seoul"))
            if dt < start_dt:
                return fetch_articles_concurrently(collected, "div.viewer")
            if start_dt <= dt <= end_dt:
                collected.append({
                    "source": "뉴시스", "datetime": dt, "title": title,
                    "url": "https://www.newsis.com" + href
                })
        page += 1
    return fetch_articles_concurrently(collected, "div.viewer")

# === 네이버 단독기사 함수들 ===
def naver_parse_pubdate(pubdate_str):
    try:
        return datetime.strptime(pubdate_str, "%a, %d %b %Y %H:%M:%S %z")
    except:
        return None

def naver_extract_title_and_body(url):
    try:
        html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if html.status_code != 200:
            return None, None
        soup = BeautifulSoup(html.text, "html.parser")

        # LawTimes specific handling
        if "www.lawtimes.co.kr/news" in url:
            title_tag = soup.find("h1", class_="heading")
            content_div = soup.find("article", id="article-view-content-div")
        elif "n.news.naver.com" in url: # Original Naver News handling
            title_tag = soup.find("div", class_="media_end_head_title")
            content_div = soup.find("div", id="newsct_article")
        else:
            return None, None

        title = title_tag.get_text(strip=True) if title_tag else None
        body = content_div.get_text(separator="\n", strip=True) if content_div else None
        return title, body
    except:
        return None, None

def naver_extract_media_name(url):
    try:
        domain = url.split("//")[-1].split("/")[0]
        parts = domain.split(".")
        if len(parts) >= 3:
            composite_key = f"{parts[-3]}.{parts[-2]}"
        else:
            composite_key = parts[0]
        media_mapping = {
            "chosun": "조선", "joongang": "중앙", "donga": "동아", "hani": "한겨레",
            "khan": "경향", "hankookilbo": "한국", "segye": "세계", "seoul": "서울",
            "kmib": "국민", "munhwa": "문화", "kbs": "KBS", "sbs": "SBS", "mbn.co": "MBN",
            "imnews": "MBC", "jtbc": "JTBC", "ichannela": "채널A", "tvchosun": "TV조선",
            "mk": "매경", "sedaily": "서경", "hankyung": "한경", "news1": "뉴스1", "www.pressian": "프레시안",
            "newsis": "뉴시스", "yna": "연합", "mt": "머투", "weekly": "주간조선", "www.imaeil": "매일신문",
            "biz.chosun": "조선비즈", "fnnews": "파뉴", "etoday.co": "이투데이", "edaily.co": "이데일리", "tf.co": "더팩트",
            "yonhapnewstv.co": "연뉴TV", "ytn.co": "YTN", "nocutnews.co": "노컷", "asiae.co": "아경", "biz.heraldcorp": "헤경",
            "www.sisajournal": "시사저널", "www.ohmynews": "오마이", "dailian.co": "데일리안", "ilyo.co": "일요신문", "sisain.co": "시사IN",
            "lawtimes": "법률신문" 
        }
        if composite_key in media_mapping:
            return media_mapping[composite_key]
        for part in reversed(parts):
            if part in media_mapping:
                return media_mapping[part]
        return composite_key.upper()
    except:
        return "[매체추출실패]"

def naver_safe_api_request(url, headers, params, max_retries=3):
    for _ in range(max_retries):
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            if res.status_code == 200:
                return res
            t.sleep(0.5)
        except:
            t.sleep(0.5)
    return res

def naver_fetch_and_filter(item_data):
    item, start_dt, end_dt, selected_keywords, use_keyword_filter = item_data
    link = item.get("link")

    title, body = naver_extract_title_and_body(link)
    
    # [수정됨] 단독, H-EXCLUSIVE, only이데일리 문패 확인 로직 추가
    exclusive_tags = ["[단독]", "[H-EXCLUSIVE]", "[only이데일리]"]
    if not title or not any(tag in title for tag in exclusive_tags) or not body:
        return None

    pub_dt = naver_parse_pubdate(item.get("pubDate"))
    if not pub_dt or not (start_dt <= pub_dt <= end_dt):
        return None

    matched_keywords = []
    if use_keyword_filter and selected_keywords:
        matched_keywords = [kw for kw in selected_keywords if kw in body]
        if not matched_keywords:
            return None

    highlighted_body = body
    for kw in matched_keywords:
        highlighted_body = highlighted_body.replace(kw, f"<mark>{kw}</mark>")
    highlighted_body = highlighted_body.replace("\n", "<br><br>")
    media = naver_extract_media_name(item.get("originallink", ""))

    # 가장 먼저 매칭된 태그를 키워드 항목에 저장
    matched_tag = next((tag for tag in exclusive_tags if tag in title), "[단독]")

    return {
        "키워드": matched_tag,
        "매체": media,
        "제목": title,
        "날짜": pub_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "본문": body,
        "필터일치": ", ".join(matched_keywords),
        "링크": link,
        "하이라이트": highlighted_body,
        "pub_dt": pub_dt
    }

# === 수집 버튼 ===
if st.button("✅ 기사 수집 시작"):
    if collect_wire:
        st.info("통신기사 수집 중...")
        newsis_articles = parse_newsis()
        yonhap_articles = parse_yonhap()
        st.session_state.wire_articles = newsis_articles + yonhap_articles
        st.success(f"✅ 통신기사 {len(st.session_state.wire_articles)}건 수집 완료")

    if collect_naver:
        use_keyword_filter = st.checkbox("📎 키워드 포함 기사만 필터링", value=True, key="naver_filter_run")
        st.info("단독기사 수집 중...")
        headers = {
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret
        }
        seen_links = set()
        all_articles = []
        total = 0

        progress_bar = st.empty()
        
        # [수정됨] 검색 쿼리를 3가지로 나누어 순회
        steps = list(range(1, 1001, 100))
        search_queries = ["[단독]", "[H-EXCLUSIVE]", "[only이데일리]"]
        total_steps = len(steps) * len(search_queries)
        current_step = 0

        for query_kw in search_queries:
            for start_index in steps:
                current_step += 1
                progress = current_step / total_steps
                progress_bar.progress(progress, text=f"{query_kw} 기사 {total}건 수집 중...")
                params = {
                    "query": query_kw,
                    "sort": "date",
                    "display": 100,
                    "start": start_index
                }
                res = naver_safe_api_request("https://openapi.naver.com/v1/search/news.json", headers, params)
                if res.status_code != 200:
                    st.warning(f"API 호출 실패: {res.status_code}")
                    break
                items = res.json().get("items", [])
                if not items:
                    break

                with ThreadPoolExecutor(max_workers=25) as executor:
                    futures = [
                        executor.submit(naver_fetch_and_filter, (item, start_dt, end_dt, selected_keywords, use_keyword_filter))
                        for item in items
                    ]
                    for future in as_completed(futures):
                        result = future.result()
                        if result and result["링크"] not in seen_links:
                            seen_links.add(result["링크"])
                            all_articles.append(result)
                            total += 1
                            
        st.session_state["naver_articles"] = all_articles
        st.success(f"✅ 단독기사 통합 {len(all_articles)}건 수집 완료")

# === 결과 출력 ===
if collect_wire:
    st.header("◆통신기사")
    selected_articles = []
    articles = st.session_state.wire_articles
    if articles:
        for i, art in enumerate(articles):
            expander_key = f"wire_expander_{i}"
            checkbox_key = f"wire_{i}"

            if expander_key not in st.session_state:
                st.session_state[expander_key] = False

            if st.session_state.get(checkbox_key, False):
                st.session_state[expander_key] = True

            if "content" in art:
                matched_kw = [kw for kw in selected_keywords if kw in art["content"]]
            else:
                matched_kw = []

            with st.expander(art["title"], expanded=st.session_state[expander_key]):
                is_selected = st.checkbox("이 기사 선택", key=checkbox_key)
                st.markdown(f"[원문 보기]({art['url']})")
                dt_str = art["datetime"].strftime('%Y-%m-%d %H:%M') if "datetime" in art else ""
                st.markdown(f"{art['source']} | {dt_str} | 필터링 키워드: {', '.join(matched_kw)}")
                if "content" in art:
                    st.markdown(highlight_keywords(art["content"], matched_kw).replace("\n", "<br>"), unsafe_allow_html=True)
                if is_selected:
                    selected_articles.append(art)

        if selected_articles:
            st.subheader("📋 복사용 텍스트 (선택된 기사만)")
            text_block = "【사회면】\n"
            for row in selected_articles:
                text_block += f"▲{row['title']}\n-{row['content'].strip()}\n\n"
            st.code(text_block.strip(), language="markdown")
            st.caption("✅ 복사 버튼을 눌러 선택한 기사 내용을 복사하세요.")
        elif articles:
            st.subheader("📋 복사용 텍스트 (선택된 기사 없음)")
            st.info("체크박스로 기사 선택 시 이 영역에 텍스트가 표시됩니다.")

if collect_naver:
    st.header("◆단독기사")
    selected_naver_articles = []
    naver_articles = st.session_state["naver_articles"]

    for idx, result in enumerate(naver_articles):
        expander_key = f"naver_expander_{idx}"
        checkbox_key = f"naver_chk_{idx}"

        if expander_key not in st.session_state:
            st.session_state[expander_key] = False

        if st.session_state.get(checkbox_key, False):
            st.session_state[expander_key] = True

        # H-EXCLUSIVE나 only이데일리가 매칭된 경우 표기를 위해 제목 앞에 달아줌
        display_title = f"[{result['키워드']}] {result['제목']}" if result['키워드'] != "[단독]" else result['제목']

        with st.expander(f"{result['매체']}/{display_title}", expanded=st.session_state[expander_key]):
            is_selected = st.checkbox("이 기사 선택", key=checkbox_key)
            st.markdown(f"[🔗 원문 보기]({result['링크']})", unsafe_allow_html=True)
            st.caption(result["날짜"])
            if result["필터일치"]:
                st.write(f"**일치 키워드:** {result['필터일치']}")
            st.markdown(f"- {result['하이라이트']}", unsafe_allow_html=True)
            if is_selected:
                selected_naver_articles.append(result)

    if selected_naver_articles:
        st.subheader("📋 복사용 텍스트 (선택된 기사만)")
        text_block = "【타지】\n"
        for row in selected_naver_articles:
            # [수정됨] 정규식에 H-EXCLUSIVE와 only이데일리 추가하여 복사할 때 제목에서 깔끔하게 제거
            clean_title = re.sub(r"\[단독\]|\(단독\)|【단독】|ⓧ단독|^단독\s*[:-]?|\[H-EXCLUSIVE\]|\[only이데일리\]", "", row['제목'], flags=re.IGNORECASE).strip()
            text_block += f"▲{row['매체']}/{clean_title}\n-{row['본문']}\n\n"
        st.code(text_block.strip(), language="markdown")
        st.caption("✅ 복사 버튼을 눌러 선택한 기사 내용을 복사하세요.")
    elif naver_articles:
        st.subheader("📋 복사용 텍스트 (선택된 기사 없음)")
        st.info("체크박스로 기사 선택 시 이 영역에 텍스트가 표시됩니다.")
