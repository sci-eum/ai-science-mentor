import streamlit as st
import google.generativeai as genai
import arxiv
import requests
from supabase import create_client, Client

st.set_page_config(page_title="AI 과학 조교", page_icon="🧬", layout="wide")

@st.cache_resource
def init_connection():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception as e:
        st.error("데이터베이스 연결 정보를 찾을 수 없습니다.")
        return None

supabase: Client = init_connection()

if supabase:
    st.sidebar.success("🟢 데이터베이스 연결 완료!")
else:
    st.sidebar.error("🔴 데이터베이스 연결 실패!")

st.sidebar.title("🧬 AI 과학 조교 메뉴")
menu = st.sidebar.radio("기능 선택:", ["🏠 메인", "🔍 논문 찾기 (A루트)", "🧪 실험 설계 (B루트)", "🗄️ 내 연구 노트"])

st.sidebar.markdown("---")
st.sidebar.write("⚙️ AI 연결 설정")
api_key = st.sidebar.text_input("발급받은 Gemini API Key를 붙여넣으세요:", type="password")

@st.cache_resource
def load_ai_model(api_key):
    genai.configure(api_key=api_key)
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            return genai.GenerativeModel(m.name)
    return None

model = None
if api_key:
    try:
        model = load_ai_model(api_key)
    except Exception as e:
        st.sidebar.error("API 키를 확인해 주세요.")

# --- 전역 상태(단기 기억 상자) 초기화 ---
if 'user' not in st.session_state: st.session_state.user = None
if 'paper_results' not in st.session_state: st.session_state.paper_results = []
if 'seen_titles' not in st.session_state: st.session_state.seen_titles = set()
if 'search_page' not in st.session_state: st.session_state.search_page = 0      # 논문 더보기 페이지
if 'current_sort' not in st.session_state: st.session_state.current_sort = None # 현재 검색 정렬 기준

if 'ai_topics' not in st.session_state: st.session_state.ai_topics = None
if 'past_topics' not in st.session_state: st.session_state.past_topics = []     # ✨ AI 이전 추천 주제 기억

if 'generated_manual' not in st.session_state: st.session_state.generated_manual = None
if 'past_manuals' not in st.session_state: st.session_state.past_manuals = []   # ✨ AI 이전 매뉴얼 기억
if 'current_idea' not in st.session_state: st.session_state.current_idea = None

# ==========================================
# 🔍 A루트: 다중 소스 통합 검색
# ==========================================
if menu == "🔍 논문 찾기 (A루트)":
    st.title("🔍 글로벌 & 국내 논문 통합 검색")
    keyword = st.text_input("검색 키워드 (예: Aspirin, 미세플라스틱)")
    tab1, tab2 = st.tabs(["🎯 관련도순 검색", "📅 최신순 검색"])

    # ✨ 검색 함수 업그레이드: '더 보기(append)' 기능 추가!
    def perform_search(sort_type, append=False):
        if not keyword:
            st.warning("키워드를 입력해 주세요.")
            return
            
        if not append:
            st.session_state.search_page = 0
            st.session_state.paper_results = []
            st.session_state.seen_titles = set()
            st.session_state.ai_topics = None
            st.session_state.past_topics = [] # 새 검색어면 이전 주제 기억 초기화
        else:
            st.session_state.search_page += 1

        st.session_state.current_sort = sort_type
        page = st.session_state.search_page

        with st.spinner(f'{sort_type}으로 논문을 {"추가 " if append else ""}수집하는 중...'):
            papers_info = []
            def normalize_title(t): return ''.join(c.lower() for c in t if c.isalnum())

            # 1. ArXiv 검색 (페이지 계산해서 다음 3개 가져오기)
            try:
                arxiv_max = (page + 1) * 3
                search = arxiv.Search(query=keyword, max_results=arxiv_max, sort_by=arxiv.SortCriterion.Relevance if sort_type == "관련도순" else arxiv.SortCriterion.SubmittedDate)
                client = arxiv.Client()
                results = list(client.results(search))
                new_arxivs = results[page * 3 : arxiv_max] # 딱 새로 추가된 페이지만 자르기
                
                for r in new_arxivs:
                    norm_title = normalize_title(r.title)
                    if norm_title not in st.session_state.seen_titles:
                        st.session_state.seen_titles.add(norm_title)
                        papers_info.append({"source": "ArXiv 🔵", "title": r.title, "authors": ", ".join([a.name for a in r.authors]), "year": r.published.year, "summary": r.summary.replace('\n', ' ')[:300] + '...', "url": r.pdf_url})
            except: pass

            # 2. Crossref 검색 (offset을 이용해 다음 4개 가져오기)
            try:
                crossref_offset = page * 4
                url = f"https://api.crossref.org/works?query={keyword}&select=title,abstract,URL,author,published&rows=4&offset={crossref_offset}&sort={'relevance' if sort_type == '관련도순' else 'published'}"
                response = requests.get(url, timeout=5).json()
                for item in response['message']['items']:
                    title = item.get('title', [''])[0]
                    if title:
                        norm_title = normalize_title(title)
                        if norm_title not in st.session_state.seen_titles:
                            st.session_state.seen_titles.add(norm_title)
                            year = item.get('published', {}).get('date-parts', [[None]])[0][0] or "연도 미상"
                            authors = ", ".join([f"{a.get('given', '')} {a.get('family', '')}".strip() for a in item.get('author', []) if f"{a.get('given', '')} {a.get('family', '')}".strip()]) or "정보 없음"
                            papers_info.append({"source": "Crossref 🔴", "title": title, "authors": authors, "year": year, "summary": item.get('abstract', '요약 없음')[:300] + '...', "url": item.get('URL', '')})
            except: pass
            
            st.session_state.paper_results.extend(papers_info) # 기존 결과 뒤에 새 결과 이어붙이기!
            
            if not st.session_state.paper_results: st.warning("결과가 없습니다.")
            else: st.success(f"현재까지 총 {len(st.session_state.paper_results)}건의 논문을 불러왔습니다.")

    with tab1:
        if st.button("관련도순으로 결과 보기"): perform_search("관련도순", append=False)
    with tab2:
        if st.button("최신순으로 결과 보기"): perform_search("최신순", append=False)

    if st.session_state.paper_results:
        saved_urls = []
        if st.session_state.get('user'):
            try:
                res = supabase.table("saved_papers").select("url").eq("user_id", st.session_state.user.id).execute()
                saved_urls = [item['url'] for item in res.data]
            except: pass

        for i, paper in enumerate(st.session_state.paper_results):
            with st.expander(f"[{paper['source']}] {paper['title']}"):
                st.write(f"**👨‍🔬 저자:** {paper['authors']} | **📅 발행:** {paper['year']}년")
                st.write(f"**📝 요약:** {paper['summary']}")
                col1, col2 = st.columns([4, 1])
                with col1: st.link_button("📄 원문 보기", paper['url'])
                with col2:
                    if not st.session_state.get('user'):
                        st.button("☆ 로그인 후 저장", key=f"dis_{paper['url']}", disabled=True)
                    else:
                        if paper['url'] in saved_urls:
                            if st.button("★ 저장됨", key=f"del_{paper['url']}"):
                                supabase.table("saved_papers").delete().eq("user_id", st.session_state.user.id).eq("url", paper['url']).execute()
                                st.rerun()
                        else:
                            if st.button("☆ 저장하기", key=f"add_{paper['url']}"):
                                data = {"user_id": st.session_state.user.id, "title": paper['title'], "authors": paper['authors'], "year": str(paper['year']), "summary": paper['summary'], "url": paper['url'], "source": paper['source']}
                                supabase.table("saved_papers").insert(data).execute()
                                st.rerun()
        
        # ✨ 논문 더 보기 버튼
        st.divider()
        if st.button(f"🔄 {st.session_state.current_sort} 다음 결과 더 불러오기 (논문 7개 추가)"):
            perform_search(st.session_state.current_sort, append=True)
            st.rerun()
        
        # ✨ AI 주제 추천 (기억 상자 활용하여 겹치지 않게!)
        if model:
            st.divider()
            st.subheader("💡 AI 과학 조교의 탐구 주제 제안")
            
            # 버튼 이름이 처음엔 '추천받기', 다음엔 '다른 주제'로 바뀜
            btn_text = "✨ 이 논문들을 바탕으로 탐구 주제 추천받기" if not st.session_state.ai_topics else "🔄 기존과 겹치지 않는 새로운 주제 추천받기"
            
            if st.button(btn_text):
                with st.spinner("이전 추천 기록을 피해서 새로운 주제를 생각하는 중..."):
                    prompt = f"다음 논문들을 참고해 고등학생용 연구 주제 2개를 한국어로 제안해줘: {[p['title'] for p in st.session_state.paper_results[-7:]]}"
                    
                    # 이전에 추천했던 주제가 있다면 프롬프트에 추가해서 경고!
                    if st.session_state.past_topics:
                        prompt += f"\n\n[매우 중요] 다음은 이전에 네가 이미 추천했던 내용들이야. 이 내용들과 절대로 겹치지 않는 완전히 새로운 접근 방식의 주제를 제안해줘:\n" + "\n".join(st.session_state.past_topics)
                    
                    try:
                        response = model.generate_content(prompt).text
                        st.session_state.ai_topics = response
                        st.session_state.past_topics.append(response) # 방금 추천한 것도 과거 기억에 추가!
                    except Exception as e:
                        st.error("주제 추천 중 에러가 발생했어요.")
            
            if st.session_state.ai_topics:
                st.info(st.session_state.ai_topics)
                if st.session_state.get('user'):
                    if st.button("💾 이 추천 주제를 내 연구 노트에 저장"):
                        try:
                            supabase.table("saved_topics").insert({"user_id": st.session_state.user.id, "topic_content": st.session_state.ai_topics}).execute()
                            st.toast("✅ 주제가 연구 노트에 저장되었습니다!")
                        except Exception as e:
                            st.error(f"저장 실패: {e}")
                else:
                    st.warning("로그인하시면 이 주제를 저장할 수 있습니다.")

# ==========================================
# 🧪 B루트: 대화형 실험 설계 매뉴얼 생성
# ==========================================
elif menu == "🧪 실험 설계 (B루트)":
    st.title("🧪 대화형 실험 설계 매뉴얼")
    
    idea = st.text_area("실험 아이디어 (예: 콜라와 멘토스 반응, 비커에 소금 섞기 등)")
    
    # ✨ 아이디어가 바뀌면 매뉴얼 기억을 초기화
    if st.session_state.current_idea != idea:
        st.session_state.current_idea = idea
        st.session_state.generated_manual = None
        st.session_state.past_manuals = []

    btn_text = "실험 매뉴얼 생성하기" if not st.session_state.generated_manual else "🔄 기구/방법을 바꿔서 새로운 버전으로 다시 짜기"
    
    if st.button(btn_text):
        if not api_key or model is None:
            st.error("앗! 왼쪽 사이드바에 API Key를 정확히 입력해 주세요.")
        elif idea:
            with st.spinner('이전 제안과 겹치지 않게 안전 가이드라인을 적용하여 고민 중입니다...'):
                prompt = f"""너는 학생들의 과학과제연구(R&E)를 돕는 똑똑하고 친절한 AI 과학 조교야.
                학생이 다음 실험 아이디어를 냈어: [{idea}]
                이 아이디어를 바탕으로 구체적인 수치와 기구가 포함된 실험 매뉴얼을 작성해줘.
                단, 아래 3가지 규칙을 무조건 지켜야 해:
                1. 절대 임의의 화학 반응식을 만들지 말 것.
                2. 폭발/유독성 위험이 있는 조합이면 거부하고 경고문을 띄울 것.
                3. 답변 마지막에 "⚠️ 반드시 교사의 임장 지도하에 실험하시기 바랍니다." 고정."""
                
                # 이전 매뉴얼이 있으면 프롬프트에 추가해서 다르게 써달라고 요청!
                if st.session_state.past_manuals:
                    prompt += f"\n\n[매우 중요] 이전에 네가 작성했던 매뉴얼 내용이야. 이번에는 다른 측정 도구, 다른 재료 배합, 혹은 다른 변인을 통제하는 완전히 새로운 버전의 매뉴얼을 제안해:\n" + "\n".join(st.session_state.past_manuals)
                
                try:
                    response = model.generate_content(prompt).text
                    st.session_state.generated_manual = response
                    st.session_state.past_manuals.append(response) # 방금 만든 것도 과거 기억에 추가!
                except Exception as e:
                    st.error(f"AI와 연결 문제 발생: {e}")
        else:
            st.warning("실험 아이디어를 입력해 주세요.")

    if st.session_state.generated_manual:
        st.subheader("📋 구체화된 실험 매뉴얼")
        st.write(st.session_state.generated_manual)
        
        if st.session_state.get('user'):
            if st.button("💾 이 매뉴얼을 내 연구 노트에 저장"):
                try:
                    data = {"user_id": st.session_state.user.id, "idea": st.session_state.current_idea, "manual_content": st.session_state.generated_manual}
                    supabase.table("saved_manuals").insert(data).execute()
                    st.toast("✅ 매뉴얼이 연구 노트에 저장되었습니다!")
                except Exception as e:
                    st.error(f"저장 실패: {e}")
        else:
            st.warning("로그인하시면 이 매뉴얼을 저장할 수 있습니다.")

# ==========================================
# 🗄️ 내 연구 노트 (마이페이지)
# ==========================================
elif menu == "🗄️ 내 연구 노트":
    st.title("🗄️ 내 연구 노트 (마이페이지)")
    
    if 'role' not in st.session_state: st.session_state.role = None
    if 'school' not in st.session_state: st.session_state.school = None

    if not st.session_state.user:
        st.write("서비스를 이용하려면 먼저 로그인이나 회원가입을 해주세요.")
        tab_login, tab_signup = st.tabs(["🔑 로그인", "📝 회원가입"])
        
        with tab_login:
            login_email = st.text_input("이메일", key="login_email")
            login_pw = st.text_input("비밀번호", type="password", key="login_pw")
            if st.button("로그인하기"):
                try:
                    response = supabase.auth.sign_in_with_password({"email": login_email, "password": login_pw})
                    st.session_state.user = response.user
                    st.success("로그인 성공!")
                    st.rerun() 
                except Exception as e: st.error(f"로그인 실패: {e}")
        
        with tab_signup:
            st.info("비밀번호는 최소 6자리 이상이어야 합니다.")
            signup_email = st.text_input("새 이메일", key="signup_email")
            signup_pw = st.text_input("새 비밀번호", type="password", key="signup_pw")
            if st.button("회원가입하기"):
                try:
                    response = supabase.auth.sign_up({"email": signup_email, "password": signup_pw})
                    st.success("🎉 회원가입 완료! 왼쪽 탭에서 로그인해 주세요.")
                except Exception as e: st.error(f"회원가입 오류: {e}")

    else:
        if not st.session_state.school:
            try:
                res = supabase.table("user_profiles").select("*").eq("id", st.session_state.user.id).execute()
                if res.data:
                    st.session_state.role = res.data[0]['role']
                    st.session_state.school = {"name": res.data[0]['school_name'], "code": res.data[0]['school_code']}
                    st.rerun()
            except: pass

        st.success(f"환영합니다! {st.session_state.user.email} 님")
        if st.button("로그아웃"):
            supabase.auth.sign_out()
            st.session_state.user, st.session_state.role, st.session_state.school = None, None, None
            st.rerun()
            
        st.divider()

        if not st.session_state.school:
            st.subheader("👋 프로필을 설정해 주세요.")
            role = st.radio("역할이 무엇인가요?", ["👨‍🎓 학생", "👨‍🏫 교사"])
            keyword = st.text_input("학교 이름 검색")
            if st.button("학교 검색") and keyword:
                with st.spinner("검색 중..."):
                    try:
                        res = requests.get("https://open.neis.go.kr/hub/schoolInfo", params={"Type": "json", "pIndex": 1, "pSize": 5, "SCHUL_NM": keyword}).json()
                        st.session_state.search_results = res.get("schoolInfo", [{}, {"row": []}])[1].get("row", [])
                    except: st.error("네트워크 오류")
            
            if st.session_state.get('search_results'):
                for school in st.session_state.search_results:
                    s_name, s_code, s_addr = school.get('SCHUL_NM'), school.get('SD_SCHUL_CODE'), school.get('ORG_RDNMA')
                    col1, col2 = st.columns([3, 1])
                    with col1: st.write(f"**{s_name}** ({s_addr})")
                    with col2:
                        if st.button("선택하기", key=s_code):
                            try:
                                supabase.table("user_profiles").upsert({"id": st.session_state.user.id, "role": role, "school_code": s_code, "school_name": s_name}).execute()
                                st.session_state.role, st.session_state.school = role, {"name": s_name, "code": s_code}
                                st.session_state.search_results = None
                                st.rerun()
                            except Exception as e: st.error(f"저장 실패: {e}")

        else:
            st.info(f"**소속:** {st.session_state.school['name']} ({st.session_state.role})")
            
            if "학생" in st.session_state.role:
                st.subheader("📚 나의 탐구 기록 포트폴리오")
                tab_p, tab_t, tab_m = st.tabs(["📚 저장된 논문", "💡 추천 실험 주제", "📋 실험 매뉴얼"])
                
                with tab_p:
                    try:
                        saved_list = supabase.table("saved_papers").select("*").eq("user_id", st.session_state.user.id).order("created_at", desc=True).execute().data
                        if not saved_list: st.write("저장된 논문이 없습니다.")
                        for paper in saved_list:
                            with st.expander(f"⭐ {paper['title']}"):
                                st.write(f"**저자:** {paper['authors']} | **발행:** {paper['year']}년")
                                st.link_button("📄 원문 링크", paper['url'])
                                if st.button("🗑️ 삭제", key=f"del_p_{paper['id']}"):
                                    supabase.table("saved_papers").delete().eq("id", paper['id']).execute()
                                    st.rerun()
                    except: pass
                
                with tab_t:
                    try:
                        topic_list = supabase.table("saved_topics").select("*").eq("user_id", st.session_state.user.id).order("created_at", desc=True).execute().data
                        if not topic_list: st.write("저장된 주제가 없습니다.")
                        for topic in topic_list:
                            with st.expander(f"💡 저장된 주제 (날짜: {topic['created_at'][:10]})"):
                                st.write(topic['topic_content'])
                                if st.button("🗑️ 삭제", key=f"del_t_{topic['id']}"):
                                    supabase.table("saved_topics").delete().eq("id", topic['id']).execute()
                                    st.rerun()
                    except: pass
                
                with tab_m:
                    try:
                        manual_list = supabase.table("saved_manuals").select("*").eq("user_id", st.session_state.user.id).order("created_at", desc=True).execute().data
                        if not manual_list: st.write("저장된 매뉴얼이 없습니다.")
                        for manual in manual_list:
                            with st.expander(f"🧪 원본 아이디어: {manual['idea']}"):
                                st.write(manual['manual_content'])
                                if st.button("🗑️ 삭제", key=f"del_m_{manual['id']}"):
                                    supabase.table("saved_manuals").delete().eq("id", manual['id']).execute()
                                    st.rerun()
                    except: pass

            else:
                st.subheader("👨‍🏫 우리 학교 학생 지도 (교사 전용)")
                st.write(f"**{st.session_state.school['name']}** 학생들의 포트폴리오 열람 기능이 곧 추가됩니다!")

else:
    st.title("24시간 맞춤형 AI 과학 조교 🤖")
    st.write("막막한 과학 탐구 시작부터 구체적이고 안전한 실험 설계까지 도와드립니다!")
    st.info("왼쪽 사이드바에 API Key를 먼저 입력한 후 메뉴를 이용해 주세요.")
