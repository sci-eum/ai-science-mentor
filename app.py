import streamlit as st
import google.generativeai as genai
import arxiv
import requests

# 1. 웹앱 기본 설정
st.set_page_config(page_title="AI 과학 조교", page_icon="🧬", layout="wide")

# 2. 사이드바 설정 (API 키 입력창 유지 - 보안 목적)
st.sidebar.title("🧬 AI 과학 조교 메뉴")
menu = st.sidebar.radio("기능 선택:", ["🏠 메인", "🔍 논문 찾기 (A루트)", "🧪 실험 설계 (B루트)"])

st.sidebar.markdown("---")
st.sidebar.write("⚙️ AI 연결 설정")
api_key = st.sidebar.text_input("발급받은 Gemini API Key를 붙여넣으세요:", type="password")

# ----- ✨ 마법의 자동 모델 찾기 코드 ✨ -----
model = None
if api_key:
    try:
        genai.configure(api_key=api_key)
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                model = genai.GenerativeModel(m.name)
                break 
    except Exception as e:
        st.sidebar.error("API 키를 확인해 주세요.")

# ==========================================
# 🔍 A루트: 다중 소스 통합 검색 및 정렬 (관련도순/최신순)
# ==========================================
if menu == "🔍 논문 찾기 (A루트)":
    st.title("🔍 글로벌 & 국내 논문 통합 검색")
    st.write("ArXiv와 Crossref 데이터베이스를 검색하며, 중복된 논문은 자동으로 걸러냅니다.")

    keyword = st.text_input("검색 키워드 (예: Aspirin, 미세플라스틱)")
    
    # 기획자 피드백 반영: '정확도순' -> '관련도순'으로 명칭 변경 완료!
    tab1, tab2 = st.tabs(["🎯 관련도순 검색", "📅 최신순 검색"])

    def perform_search(sort_type):
        if not keyword:
            st.warning("키워드를 입력해 주세요.")
            return

        with st.spinner(f'{sort_type}으로 중복 없는 논문을 수집하는 중...'):
            papers_info = []
            seen_titles = set()
            
            def normalize_title(title):
                return ''.join(char.lower() for char in title if char.isalnum())

            # 1. ArXiv 검색 설정
            if sort_type == "관련도순":
                arxiv_sort = arxiv.SortCriterion.Relevance
            else:
                arxiv_sort = arxiv.SortCriterion.SubmittedDate # 최신 등록순

            try:
                search = arxiv.Search(query=keyword, max_results=3, sort_by=arxiv_sort)
                for result in search.results():
                    norm_title = normalize_title(result.title)
                    if norm_title not in seen_titles:
                        seen_titles.add(norm_title)
                        papers_info.append({
                            "source": "ArXiv 🔵", 
                            "title": result.title,
                            "authors": ", ".join([a.name for a in result.authors]),
                            "year": result.published.year,
                            "summary": result.summary.replace('\n', ' ')[:300] + '...',
                            "url": result.pdf_url
                        })
            except Exception as e:
                pass

            # 2. Crossref 검색 설정
            crossref_sort = "relevance" if sort_type == "관련도순" else "published"
            
            try:
                url = f"https://api.crossref.org/works?query={keyword}&select=title,abstract,URL,author,published&rows=4&sort={crossref_sort}"
                response = requests.get(url, timeout=5).json()
                for item in response['message']['items']:
                    title = item.get('title', [''])[0]
                    if title:
                        norm_title = normalize_title(title)
                        if norm_title not in seen_titles:
                            seen_titles.add(norm_title)
                            
                            year = item.get('published', {}).get('date-parts', [[None]])[0][0] or "연도 미상"
                            authors_list = []
                            for a in item.get('author', []):
                                name = f"{a.get('given', '')} {a.get('family', '')}".strip()
                                if name: authors_list.append(name)
                            authors = ", ".join(authors_list) if authors_list else "정보 없음"
                            
                            papers_info.append({
                                "source": "Crossref 🔴", 
                                "title": title,
                                "authors": authors, 
                                "year": year,
                                "summary": item.get('abstract', '요약 없음')[:300] + '...',
                                "url": item.get('URL', '')
                            })
            except Exception as e:
                pass

            # 결과 출력
            if not papers_info:
                st.warning("결과가 없습니다. 키워드를 변경해 보세요.")
            else:
                st.success(f"{sort_type} 기준, 총 {len(papers_info)}건의 논문을 찾았습니다!")
                for i, paper in enumerate(papers_info):
                    with st.expander(f"[{paper['source']}] {paper['title']}"):
                        st.write(f"**👨‍🔬 저자:** {paper['authors']} | **📅 발행:** {paper['year']}년")
                        st.write(f"**📝 요약:** {paper['summary']}")
                        st.link_button("📄 원문 보기", paper['url'])
                
                # AI 주제 추천
                if model:
                    st.divider()
                    st.subheader("💡 AI 과학 조교의 탐구 주제 제안")
                    prompt = f"다음 논문들을 참고해 고등학생용 연구 주제 2개를 한국어로 제안해줘: {[p['title'] for p in papers_info]}"
                    try:
                        st.info(model.generate_content(prompt).text)
                    except Exception as e:
                        st.error("주제 추천 중 에러가 발생했어요.")

    # 탭별 버튼 동작 연결
    with tab1:
        if st.button("관련도순으로 결과 보기"):
            perform_search("관련도순")
    
    with tab2:
        if st.button("최신순으로 결과 보기"):
            perform_search("최신순")


# ==========================================
# 🧪 B루트: 대화형 실험 설계 매뉴얼 생성
# ==========================================
elif menu == "🧪 실험 설계 (B루트)":
    st.title("🧪 대화형 실험 설계 매뉴얼")
    st.write("아이디어를 입력하시면 안전 가이드라인이 적용된 구체적인 실험 매뉴얼을 작성해 드립니다.")
    
    idea = st.text_area("실험 아이디어 (예: 콜라와 멘토스 반응, 비커에 소금 섞기 등)")
    
    if st.button("실험 매뉴얼 생성하기"):
        if not api_key or model is None:
            st.error("앗! 왼쪽 사이드바에 API Key를 정확히 입력해 주세요.")
        elif idea:
            with st.spinner('AI가 안전 가이드라인을 엄격히 적용하여 고민 중입니다...'):
                prompt = f"""
                너는 학생들의 과학과제연구(R&E)를 돕는 똑똑하고 친절한 AI 과학 조교야.
                학생이 다음 실험 아이디어를 냈어: [{idea}]
                
                이 아이디어를 바탕으로 구체적인 수치와 기구가 포함된 실험 매뉴얼을 작성해줘.
                단, 아래 3가지 규칙을 무조건, 반드시 지켜야 해:
                1. 절대 임의의 화학 반응식을 만들지 말 것.
                2. 폭발/유독성 위험이 있는 조합이면 매뉴얼 작성을 거부하고 강력한 경고문을 띄울 것.
                3. 답변 맨 마지막에는 반드시 "⚠️ 반드시 교사의 임장 지도하에 실험하시기 바랍니다."라는 문구를 굵은 글씨로 고정할 것.
                """
                try:
                    response = model.generate_content(prompt)
                    st.subheader("📋 구체화된 실험 매뉴얼")
                    st.write(response.text)
                except Exception as e:
                    st.error(f"AI와 연결하는 중 문제가 발생했어요. (에러내용: {e})")
        else:
            st.warning("실험 아이디어를 입력해 주세요.")


# ==========================================
# 🏠 메인 화면
# ==========================================
else:
    st.title("24시간 맞춤형 AI 과학 조교 🤖")
    st.write("막막한 과학 탐구 시작부터 구체적이고 안전한 실험 설계까지 도와드립니다!")
    st.info("왼쪽 사이드바에 API Key를 먼저 입력한 후 메뉴를 이용해 주세요.")