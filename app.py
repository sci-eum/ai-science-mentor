import streamlit as st
import google.generativeai as genai
import arxiv
import requests
from supabase import create_client, Client

# ==========================================
# 1. 페이지 및 기본 설정
# ==========================================
st.set_page_config(page_title="AI 과학 조교", page_icon="🧬", layout="wide")

def local_css(file_name):
    try:
        with open(file_name, encoding="utf-8") as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
    except: pass

local_css("style.css")

@st.cache_resource
def init_connection():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except: return None

supabase: Client = init_connection()

# ==========================================
# 2. 전역 상태(Session State) 초기화
# ==========================================
states = [
    'user', 'role', 'school', 'paper_results', 'seen_titles', 'search_page', 
    'ai_topics_list', 'past_topics', 'generated_manual', 'past_manuals', 'current_idea', 'current_sort'
]
for s in states:
    if s not in st.session_state: 
        if s in ['paper_results', 'past_topics', 'past_manuals', 'ai_topics_list']: 
            st.session_state[s] = []
        elif s == 'seen_titles': 
            st.session_state[s] = set()
        else: 
            st.session_state[s] = None

# ==========================================
# 👤 3. 사이드바 (프로필 및 계정 관리 - 폼 적용 완료)
# ==========================================
st.sidebar.markdown("<br>", unsafe_allow_html=True)

if not st.session_state.user:
    st.sidebar.markdown("""
        <div class="profile-container">
            <div class="avatar-circle">?</div>
            <div class="profile-name">반갑습니다!</div>
            <p style="font-size:0.8rem; opacity:0.7;">로그인 후 연구를 시작하세요.</p>
        </div>
    """, unsafe_allow_html=True)
    
    t_login, t_signup = st.sidebar.tabs(["로그인", "회원가입"])
    
    with t_login:
        with st.form("login_form"):
            l_email = st.text_input("이메일")
            l_pw = st.text_input("비밀번호", type="password")
            login_submit = st.form_submit_button("로그인", use_container_width=True)
            
            if login_submit:
                try:
                    res = supabase.auth.sign_in_with_password({"email": l_email, "password": l_pw})
                    st.session_state.user = res.user
                    st.rerun()
                except Exception as e: 
                    st.error("로그인 실패: 정보를 확인해 주세요.")
            
    with t_signup:
        with st.form("signup_form"):
            s_email = st.text_input("새 이메일")
            s_pw = st.text_input("새 비번 (6자+)", type="password")
            signup_submit = st.form_submit_button("가입", use_container_width=True)
            
            if signup_submit:
                try:
                    supabase.auth.sign_up({"email": s_email, "password": s_pw})
                    st.success("가입 완료! 로그인 탭에서 로그인 해주세요.")
                except Exception as e: 
                    st.error(f"가입 실패: {e}")
else:
    if not st.session_state.school:
        try:
            res = supabase.table("user_profiles").select("*").eq("id", st.session_state.user.id).execute()
            if res.data:
                st.session_state.role = res.data[0]['role']
                st.session_state.school = {"name": res.data[0]['school_name'], "code": res.data[0]['school_code']}
        except: pass

    role_label = st.session_state.role if st.session_state.role else "연구원"
    school_label = st.session_state.school['name'] if st.session_state.school else "프로필 미설정"
    avatar_icon = "🎓" if "학생" in role_label else "🔬"
    
    st.sidebar.markdown(f"""
        <div class="profile-container">
            <div class="role-badge">{role_label}</div>
            <div class="avatar-circle">{avatar_icon}</div>
            <div class="profile-name">{st.session_state.user.email.split('@')[0]}</div>
            <div class="profile-school">{school_label}</div>
        </div>
    """, unsafe_allow_html=True)
    
    if st.sidebar.button("로그아웃", use_container_width=True):
        supabase.auth.sign_out()
        for s in ['user', 'role', 'school']: st.session_state[s] = None
        st.rerun()

st.sidebar.markdown("---")
api_key = st.sidebar.text_input("Gemini API Key:", type="password")
model = None

# ✨ AI 모델 자동 탐색
if api_key:
    try:
        genai.configure(api_key=api_key)
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                model = genai.GenerativeModel(m.name)
                break
    except Exception as e: 
        st.sidebar.error(f"API 설정 오류: {e}")

# ==========================================
# 🕹️ 상단 네비게이션
# ==========================================
st.write("") 

with st.container():
    st.markdown('<span class="top-menu-marker"></span>', unsafe_allow_html=True)
    menu = st.radio(
        "메뉴 선택", 
        ["메인", "논문 찾기", "실험 설계", "내 연구 노트"],
        horizontal=True, 
        label_visibility="collapsed" 
    )
st.markdown("---")

# ==========================================
# 🏠 1. 메인 화면
# ==========================================
if menu == "메인":
    st.markdown("""
        <div class="hero-container">
            <h1 style="color:white; font-size:3rem; font-weight:900;">🧬 AI SCIENCE ADVISOR</h1>
            <p style="color:rgba(255,255,255,0.8); font-size:1.2rem;">세상을 바꾸는 당신의 위대한 탐구, AI가 지도를 그려드립니다.</p>
        </div>
    """, unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    features = [
        ("🔍", "논문 검색", "글로벌 DB 통합 탐색"), 
        ("🧪", "실험 설계", "AI 기반 안전 매뉴얼"), 
        ("🗄️", "연구 노트", "나만의 탐구 포트폴리오")
    ]
    for col, (i, t, d) in zip([c1, c2, c3], features):
        col.markdown(f"<div style='background:white; padding:2rem; border-radius:20px; text-align:center; box-shadow:0 10px 20px rgba(0,0,0,0.05);'><h3>{i} {t}</h3><p>{d}</p></div>", unsafe_allow_html=True)

# ==========================================
# 🔍 2. 논문 찾기 (A루트)
# ==========================================
elif menu == "논문 찾기":
    
    with st.container():
        st.markdown('<span class="search-marker"></span>', unsafe_allow_html=True)
        st.markdown("<h2 style='text-align: center; color: white; font-weight: 800; margin-bottom: 0.5rem;'>🔍 스마트 논문 탐색</h2>", unsafe_allow_html=True)
        
        sort_choice = st.radio("정렬 방식", ["🎯 관련도순", "📅 최신순"], horizontal=True, label_visibility="collapsed", key="search_sort")
        st.write("") 
        
        col1, col2, col3, col4 = st.columns([1.5, 6, 1.5, 1.5]) 
        with col2:
            keyword = st.text_input("검색어 입력", placeholder="예: 그래핀 합성, 미세플라스틱, 초전도체...", label_visibility="collapsed")
        with col3:
            search_clicked = st.button("검색", use_container_width=True, type="primary")

    def perform_search(sort_type, append=False):
        if not keyword:
            st.warning("키워드를 입력해 주세요.")
            return
            
        if not append:
            st.session_state.search_page, st.session_state.paper_results, st.session_state.seen_titles = 0, [], set()
            st.session_state.ai_topics_list, st.session_state.past_topics = [], []
        else: 
            st.session_state.search_page += 1

        st.session_state.current_sort = sort_type
        page = st.session_state.search_page

        with st.spinner(f'논문을 수집하는 중...'):
            papers_info = []
            def normalize_title(t): return ''.join(c.lower() for c in t if c.isalnum())

            try:
                arxiv_max = (page + 1) * 3
                search = arxiv.Search(
                    query=keyword, 
                    max_results=arxiv_max, 
                    sort_by=arxiv.SortCriterion.Relevance if sort_type == "관련도순" else arxiv.SortCriterion.SubmittedDate
                )
                client = arxiv.Client()
                new_arxivs = list(client.results(search))[page * 3 : arxiv_max] 
                for r in new_arxivs:
                    if normalize_title(r.title) not in st.session_state.seen_titles:
                        st.session_state.seen_titles.add(normalize_title(r.title))
                        papers_info.append({"source": "ArXiv", "title": r.title, "authors": ", ".join([a.name for a in r.authors]), "year": r.published.year, "summary": r.summary.replace('\n', ' '), "url": r.pdf_url})
            except: pass

            try:
                url = f"https://api.crossref.org/works?query={keyword}&select=title,abstract,URL,author,published&rows=4&offset={page * 4}&sort={'relevance' if sort_type == '관련도순' else 'published'}"
                for item in requests.get(url, timeout=5).json()['message']['items']:
                    title = item.get('title', [''])[0]
                    if title and normalize_title(title) not in st.session_state.seen_titles:
                        st.session_state.seen_titles.add(normalize_title(title))
                        year = item.get('published', {}).get('date-parts', [[None]])[0][0] or "연도 미상"
                        authors = ", ".join([f"{a.get('given', '')} {a.get('family', '')}".strip() for a in item.get('author', []) if f"{a.get('given', '')} {a.get('family', '')}".strip()]) or "정보 없음"
                        summary_raw = item.get('abstract', '요약이 제공되지 않는 논문입니다.')
                        summary_clean = summary_raw.replace('<jats:p>', '').replace('</jats:p>', '').replace('<jats:title>', '').replace('</jats:title>', '')
                        papers_info.append({"source": "Crossref", "title": title, "authors": authors, "year": year, "summary": summary_clean, "url": item.get('URL', '')})
            except: pass
            
            st.session_state.paper_results.extend(papers_info) 
            if not st.session_state.paper_results: st.warning("결과가 없습니다.")

    sort_type_str = "관련도순" if "관련도순" in sort_choice else "최신순"
    if search_clicked:
        perform_search(sort_type_str, False)

    if st.session_state.paper_results:
        st.write("") 
        st.success(f"총 {len(st.session_state.paper_results)}건의 논문을 찾았습니다! 🎉")
        
        res_col, ai_col = st.columns([7, 3])

        # 💡 [우측 영역] AI 탐구 주제 제안 (개별 토글 + 누적형)
        with ai_col:
            st.markdown("### 💡 AI 탐구 주제 제안")
            
            if not model:
                st.warning("👈 왼쪽 메뉴에서 API Key를 입력해주세요.")
            else:
                btn_text = "✨ 주제 추천받기" if not st.session_state.ai_topics_list else "🔄 새로운 주제 추가로 받기"
                
                if st.button(btn_text, use_container_width=True, type="primary"):
                    with st.spinner("논문을 분석 중입니다..."):
                        prompt = f"""
                        다음 논문들을 참고해 창의적인 고등학생용 연구 주제 2개를 제안해줘.
                        반드시 아래 형식을 정확히 지켜줘. (파싱을 위해 중요함)
                        
                        [주제 시작]
                        제목: 주제 제목
                        내용: 탐구 동기, 실험 방법, 기대 효과 등 상세 설명
                        [주제 종료]
                        
                        논문 리스트: {[p['title'] for p in st.session_state.paper_results[:5]]}
                        """
                        if st.session_state.past_topics: 
                            prompt += f"\n[중요] 이전 추천들과 절대 겹치지 않게 해:\n" + "\n".join(st.session_state.past_topics)
                        
                        try:
                            response = model.generate_content(prompt).text
                            st.session_state.past_topics.append(response)
                            
                            raw_topics = response.split("[주제 시작]")
                            for rt in raw_topics:
                                if "[주제 종료]" in rt:
                                    clean_t = rt.split("[주제 종료]")[0].strip()
                                    lines = clean_t.split('\n')
                                    t_title = lines[0].replace("제목:", "").strip()
                                    t_content = clean_t.replace(lines[0], "").replace("내용:", "").strip()
                                    st.session_state.ai_topics_list.append({"title": t_title, "content": t_content})
                        except Exception as e: 
                            st.error(f"오류가 발생했습니다: {e}")

            if st.session_state.ai_topics_list:
                saved_topic_contents = []
                if st.session_state.user:
                    try:
                        res = supabase.table("saved_topics").select("topic_content").eq("user_id", st.session_state.user.id).execute()
                        saved_topic_contents = [item['topic_content'] for item in res.data]
                    except: pass

                for idx, topic in enumerate(reversed(st.session_state.ai_topics_list)):
                    with st.expander(f"📌 {topic['title']}", expanded=False):
                        st.write(topic['content'])
                        
                        if st.session_state.user:
                            full_topic_text = f"제목: {topic['title']}\n내용: {topic['content']}"
                            is_saved = any(topic['title'] in s for s in saved_topic_contents)
                            
                            col_btn, col_empty = st.columns([1, 1])
                            with col_btn:
                                if is_saved:
                                    if st.button("★ 저장됨", key=f"unsave_t_{idx}", use_container_width=True):
                                        supabase.table("saved_topics").delete().eq("user_id", st.session_state.user.id).ilike("topic_content", f"%{topic['title']}%").execute()
                                        st.rerun()
                                else:
                                    if st.button("☆ 저장하기", key=f"save_t_{idx}", use_container_width=True):
                                        supabase.table("saved_topics").insert({"user_id": st.session_state.user.id, "topic_content": full_topic_text}).execute()
                                        st.rerun()

        # 📚 [좌측 영역] 논문 검색 결과 리스트
        with res_col:
            saved_urls = []
            if st.session_state.get('user'):
                try: saved_urls = [item['url'] for item in supabase.table("saved_papers").select("url").eq("user_id", st.session_state.user.id).execute().data]
                except: pass

            for paper in st.session_state.paper_results:
                with st.container(border=True): 
                    badge_class = "badge-arxiv" if paper['source'] == "ArXiv" else "badge-crossref"
                    st.markdown(f"""
                        <div class="paper-source-badge {badge_class}">{paper['source']} • {paper['year']}</div>
                        <div class="paper-title">{paper['title']}</div>
                        <div class="paper-authors">👨‍🔬 저자: {paper['authors']}</div>
                        <div class="paper-abstract">{paper['summary']}</div>
                    """, unsafe_allow_html=True)
                    
                    c1, c2, c3 = st.columns([3, 3, 4])
                    with c1: 
                        st.link_button("📄 원문 보기", paper['url'], use_container_width=True)
                    with c2:
                        if not st.session_state.user: 
                            st.button("☆ 로그인 후 저장", key=f"dis_{paper['url']}", disabled=True, use_container_width=True)
                        else:
                            if paper['url'] in saved_urls:
                                if st.button("★ 저장됨", key=f"del_{paper['url']}", use_container_width=True):
                                    supabase.table("saved_papers").delete().eq("user_id", st.session_state.user.id).eq("url", paper['url']).execute()
                                    st.rerun()
                            else:
                                if st.button("☆ 저장하기", key=f"add_{paper['url']}", use_container_width=True):
                                    supabase.table("saved_papers").insert({"user_id": st.session_state.user.id, "title": paper['title'], "authors": paper['authors'], "year": str(paper['year']), "summary": paper['summary'], "url": paper['url'], "source": paper['source']}).execute()
                                    st.rerun()
            
            st.divider()
            if st.button(f"🔄 다음 논문 더 불러오기", use_container_width=True):
                perform_search(st.session_state.current_sort, True)
                st.rerun()

# ==========================================
# 🧪 3. 실험 설계 (B루트) - 완벽한 UI 고도화!
# ==========================================
elif menu == "실험 설계":
    with st.container():
        # ✨ 여기에 CSS 마커를 삽입하여 다크 배경을 통일시킵니다!
        st.markdown('<span class="experiment-marker"></span>', unsafe_allow_html=True)
        st.markdown("<h2 style='text-align: center; color: white; margin-bottom: 1.5rem;'>🧪 대화형 실험 설계 매뉴얼</h2>", unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("<span class='label-essential'>🎯 탐구 주제 (필수)</span>", unsafe_allow_html=True)
            topic = st.text_input("topic", placeholder="비타민 C 항산화 반응 속도 측정 등", label_visibility="collapsed")
            
            st.markdown("<span class='label-optional'>➡️ 독립 변인 (선택)</span>", unsafe_allow_html=True)
            ind_var = st.text_input("ind", placeholder="비타민 C 수용액의 농도 등", label_visibility="collapsed")
            
        with col2:
            st.markdown("<span class='label-optional'>📈 종속 변인 (선택)</span>", unsafe_allow_html=True)
            dep_var = st.text_input("dep", placeholder="아이오딘 용액의 탈색 시간 등", label_visibility="collapsed")
            
            st.markdown("<span class='label-optional'>🧫 준비물 (선택)</span>", unsafe_allow_html=True)
            materials = st.text_input("mat", placeholder="아이오딘 용액, 전분, 비커 등", label_visibility="collapsed")
            
        st.markdown("<span class='label-optional'>💡 상세 아이디어 및 요청 사항 (선택)</span>", unsafe_allow_html=True)
        idea_details = st.text_area("details", placeholder="실험 과정에서 특히 신경 쓰고 싶은 부분을 자유롭게 적어주세요.", label_visibility="collapsed")
        
        combined_idea = f"주제: {topic}\n독립변인: {ind_var}\n종속변인: {dep_var}\n준비물: {materials}\n상세내용: {idea_details}"
        
        if st.session_state.current_idea != combined_idea:
            st.session_state.current_idea = combined_idea
            st.session_state.generated_manual = None
            
        btn_text = "✨ 실험 매뉴얼 생성하기" if not st.session_state.generated_manual else "🔄 조건 수정해서 다시 짜기"
        
        st.write("")
        submit_clicked = st.button(btn_text, use_container_width=True, type="primary")

    if submit_clicked:
        if not topic:
            st.error("❗ 탐구 주제는 필수 입력 사항입니다.")
        elif not api_key or model is None:
            st.error("❗ 왼쪽 사이드바에서 API Key를 먼저 입력해 주세요.")
        else:
            with st.spinner("AI가 안전 수칙을 검토하며 체계적인 매뉴얼을 작성 중입니다..."):
                prompt = f"""
                학생의 실험 아이디어를 바탕으로 고등학생 수준에 맞는 안전하고 구체적인 실험 매뉴얼을 작성해줘.
                
                [학생 아이디어]
                {combined_idea}
                
                [출력 형식 (반드시 아래 마크다운 헤더 형식을 지켜서 예쁘게 작성해줘)]
                ### ⚠️ 안전 수칙 및 주의사항
                (여기에 실험 시 주의할 점, 폐기물 처리 방법 등을 상세히 작성)
                
                ### 🧫 필요 기구 및 시약
                (여기에 규격과 수량이 포함된 준비물 목록을 불릿 포인트로 작성)
                
                ### 👣 단계별 실험 과정
                1. (스텝 1 상세 설명)
                2. (스텝 2 상세 설명)
                ...
                
                [제약조건]
                - 수치와 기구의 규격을 구체적으로 포함할 것.
                - 절대 임의의 위험한 화학식이나 폭발/유독성 실험은 거부하고 안전한 대안을 제시할 것.
                - 마지막 줄에 '> ⚠️ **교사 임장 지도 필수**' 라는 문구를 인용구 형태로 꼭 넣을 것.
                """
                if st.session_state.past_manuals: 
                    prompt += f"\n[중요] 이전 매뉴얼 내용과 다른 방식이나 조건을 추가해서 제안해줘:\n" + "\n".join(st.session_state.past_manuals)
                    
                try:
                    response = model.generate_content(prompt).text
                    st.session_state.generated_manual = response
                    st.session_state.past_manuals.append(response) 
                except Exception as e: 
                    st.error(f"연결 에러가 발생했습니다: {e}")

    if st.session_state.generated_manual:
        st.write("")
        st.markdown("### 📋 AI 맞춤형 실험 매뉴얼")
        with st.container(border=True):
            st.markdown(st.session_state.generated_manual)
            st.divider()
            if st.session_state.user:
                col1, col2, col3 = st.columns([1, 2, 1])
                with col2:
                    if st.button("💾 이 실험 매뉴얼 저장하기", use_container_width=True):
                        try:
                            supabase.table("saved_manuals").insert({
                                "user_id": st.session_state.user.id, 
                                "idea": topic, 
                                "manual_content": st.session_state.generated_manual
                            }).execute()
                            st.toast("✅ 내 연구 노트에 저장되었습니다!")
                        except: 
                            st.error("저장 실패")

# ==========================================
# 🗄️ 4. 내 연구 노트
# ==========================================
elif menu == "내 연구 노트":
    st.title("🗄️ 내 연구 포트폴리오")
    if not st.session_state.user: st.warning("왼쪽 사이드바에서 로그인 해주세요.")
    else:
        if not st.session_state.school:
            st.subheader("👋 프로필을 설정해 주세요.")
            role = st.radio("역할", ["👨‍🎓 학생", "👨‍🏫 교사"])
            keyword = st.text_input("학교 이름 검색")
            if st.button("검색") and keyword:
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
                        if st.button("선택", key=s_code):
                            try:
                                supabase.table("user_profiles").upsert({"id": st.session_state.user.id, "role": role, "school_code": s_code, "school_name": s_name}).execute()
                                st.session_state.role, st.session_state.school = role, {"name": s_name, "code": s_code}
                                st.session_state.search_results = None
                                st.rerun()
                            except: st.error("저장 실패")
        else:
            if "학생" in st.session_state.role:
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
                            with st.expander(f"💡 주제 ({topic['created_at'][:10]})"):
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
                st.write(f"**{st.session_state.school['name']}** 학생 포트폴리오 열람 기능 준비 중입니다.")
