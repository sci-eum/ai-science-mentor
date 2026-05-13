import streamlit as st
import google.generativeai as genai
import arxiv
import json
import re
import requests
from html import escape
from math import atan2, cos, radians, sin, sqrt
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

def extract_region(address):
    if not address:
        return None
    return address.split()[0]

def extract_city(address):
    if not address:
        return None
    parts = address.split()
    if len(parts) < 2:
        return None
    return parts[1]

def haversine_km(lat1, lng1, lat2, lng2):
    radius = 6371
    dlat = radians(float(lat2) - float(lat1))
    dlng = radians(float(lng2) - float(lng1))
    a = sin(dlat / 2) ** 2 + cos(radians(float(lat1))) * cos(radians(float(lat2))) * sin(dlng / 2) ** 2
    return radius * 2 * atan2(sqrt(a), sqrt(1 - a))

def geocode_address(address, place_name=None):
    """학교명/주소를 좌표로 변환한다. 공개 좌표원을 먼저 쓰고, VWorld는 보조 경로로 사용한다."""
    if not address:
        st.session_state.geocode_debug = "주소가 비어 있습니다."
        return None, None
    try:
        api_key = st.secrets.get("GEOCODING_API_KEY")
    except Exception:
        api_key = None

    try:
        referer = st.secrets.get("VWORLD_REFERER") or st.secrets.get("APP_URL")
    except Exception:
        referer = None

    headers = {"User-Agent": "ai-science-mentor/1.0"}
    if referer:
        headers["Referer"] = referer

    domain = referer or "http://map.vworld.kr/"
    address_candidates = [
        address,
        address.replace("충청남도", "충남").replace("충청북도", "충북"),
        address.replace("전라남도", "전남").replace("전라북도", "전북"),
        address.replace("경상남도", "경남").replace("경상북도", "경북"),
    ]
    address_candidates = list(dict.fromkeys(address_candidates))
    debug_messages = []

    if place_name:
        try:
            wikidata_query = f'''
            SELECT ?coord WHERE {{
              ?item rdfs:label "{place_name.replace('"', '')}"@ko;
                    wdt:P625 ?coord.
            }}
            LIMIT 1
            '''
            response = requests.get(
                "https://query.wikidata.org/sparql",
                params={"query": wikidata_query, "format": "json"},
                headers={
                    "Accept": "application/sparql-results+json",
                    "User-Agent": "ai-science-mentor/1.0",
                },
                timeout=8,
            )
            bindings = response.json().get("results", {}).get("bindings", [])
            if bindings:
                point_text = bindings[0]["coord"]["value"]
                if point_text.startswith("Point(") and point_text.endswith(")"):
                    lng, lat = point_text[6:-1].split()
                    st.session_state.geocode_debug = f"Wikidata 좌표 조회 성공: {place_name}"
                    return float(lat), float(lng)
            debug_messages.append(f"Wikidata:{place_name} -> 결과 없음")
        except Exception as e:
            debug_messages.append(f"Wikidata:{place_name} -> 요청 실패: {e}")

    try:
        nominatim_query = f"{place_name or ''} {address}".strip()
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": nominatim_query,
                "format": "jsonv2",
                "limit": 1,
                "countrycodes": "kr",
            },
            headers={"User-Agent": "ai-science-mentor/1.0"},
            timeout=8,
        )
        results = response.json()
        if results:
            st.session_state.geocode_debug = f"OpenStreetMap 좌표 조회 성공: {nominatim_query}"
            return float(results[0]["lat"]), float(results[0]["lon"])
        debug_messages.append(f"OpenStreetMap:{nominatim_query} -> 결과 없음")
    except Exception as e:
        debug_messages.append(f"OpenStreetMap -> 요청 실패: {e}")

    if not api_key:
        st.session_state.geocode_debug = " | ".join(debug_messages[-6:]) + " | VWorld 키 없음"
        return None, None

    for candidate in address_candidates:
        for endpoint in ("new2coord.do", "jibun2coord.do"):
            safe_target = f"{candidate} / legacy:{endpoint}"
            try:
                response = requests.get(
                    f"http://apis.vworld.kr/{endpoint}",
                    params={
                        "q": candidate,
                        "apiKey": api_key,
                        "domain": domain,
                        "output": "json",
                        "epsg": "EPSG:4326",
                    },
                    headers=headers,
                    timeout=8,
                )
                data = response.json()
                lng = data.get("EPSG_4326_X")
                lat = data.get("EPSG_4326_Y")
                if lat and lng:
                    st.session_state.geocode_debug = f"VWorld 지오코딩 성공: {safe_target}"
                    return float(lat), float(lng)
                debug_messages.append(f"{safe_target} -> {str(data)[:120]}")
            except Exception as e:
                debug_messages.append(f"{safe_target} -> 요청 실패: {e}")

    for candidate in address_candidates:
        for address_type in ("road", "parcel", "ROAD", "PARCEL"):
            params = {
                "service": "address",
                "request": "getcoord",
                "version": "2.0",
                "crs": "epsg:4326",
                "type": address_type,
                "address": candidate,
                "format": "json",
                "refine": "true",
                "simple": "false",
                "key": api_key,
            }
            safe_target = f"{candidate} / {address_type}"
            try:
                response = requests.get(
                    "https://api.vworld.kr/req/address",
                    params=params,
                    headers=headers,
                    timeout=5,
                )
                data = response.json()
                vworld_response = data.get("response", {})
                status = vworld_response.get("status")
                error_text = vworld_response.get("error", {}).get("text")
                point = data.get("response", {}).get("result", {}).get("point")
                if point:
                    st.session_state.geocode_debug = f"VWorld 지오코딩 성공: {safe_target}"
                    return float(point["y"]), float(point["x"])
                debug_messages.append(f"{safe_target} -> status={status}, error={error_text or '없음'}")
            except Exception as e:
                debug_messages.append(f"{safe_target} -> 요청 실패: {e}")

    st.session_state.geocode_debug = " | ".join(debug_messages[-6:]) or "VWorld 응답이 비어 있습니다."
    return None, None

def build_school_profile(profile):
    school_address = profile.get("school_address")
    return {
        "name": profile.get("school_name"),
        "code": profile.get("school_code"),
        "address": school_address,
        "region": profile.get("school_region") or extract_region(school_address),
        "city": extract_city(school_address),
        "lat": profile.get("school_lat"),
        "lng": profile.get("school_lng"),
    }

def save_school_profile(user_id, school_name, school_code, school_address):
    school = {
        "name": school_name,
        "code": school_code,
        "address": school_address,
        "region": extract_region(school_address),
        "city": extract_city(school_address),
        "lat": None,
        "lng": None,
    }

    base_profile = {
        "id": user_id,
        "role": "연구자",
        "school_code": school_code,
        "school_name": school_name,
    }

    full_profile = {
        **base_profile,
        "school_address": school_address,
        "school_region": school["region"],
    }

    try:
        supabase.table("user_profiles").upsert(full_profile).execute()
    except Exception:
        supabase.table("user_profiles").upsert(base_profile).execute()

    try:
        school_lat, school_lng = geocode_address(school_address, school_name)
        if school_lat and school_lng:
            school["lat"] = school_lat
            school["lng"] = school_lng
            try:
                supabase.table("user_profiles").update({
                    "school_address": school_address,
                    "school_region": school["region"],
                    "school_lat": school_lat,
                    "school_lng": school_lng,
                }).eq("id", user_id).execute()
            except Exception:
                pass
    except Exception as e:
        st.caption(f"학교 위치 좌표는 나중에 다시 계산됩니다: {e}")

    return school

def parse_research_topics(response_text):
    """Gemini 응답 형식이 조금 흔들려도 추천 주제를 최대한 복구한다."""
    if not response_text:
        return []

    text = response_text.strip()

    def clean_title(value, index):
        title = re.sub(r"^[\s\-*#\d\.\)\[]+", "", str(value or "")).strip()
        title = title.replace("제목:", "", 1).strip()
        return title or f"추천 탐구 주제 {index}"

    def clean_content(value):
        content = str(value or "").strip()
        content = re.sub(r"^\s*내용\s*[:：]\s*", "", content).strip()
        return content or "상세 설명이 제공되지 않았습니다."

    def normalize(items):
        topics = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            title = clean_title(item.get("title") or item.get("제목"), len(topics) + 1)
            content = clean_content(item.get("content") or item.get("내용") or item.get("description") or item.get("설명"))
            key = re.sub(r"\W+", "", title.lower())
            if key and key not in seen:
                seen.add(key)
                topics.append({"title": title, "content": content})
        return topics

    json_candidates = [text]
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    json_candidates.extend(fenced)
    array_match = re.search(r"\[\s*\{.*?\}\s*\]", text, flags=re.DOTALL)
    if array_match:
        json_candidates.append(array_match.group(0))
    object_match = re.search(r"\{\s*\"topics\"\s*:\s*\[.*?\]\s*\}", text, flags=re.DOTALL)
    if object_match:
        json_candidates.append(object_match.group(0))

    for candidate in json_candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                data = data.get("topics") or data.get("추천주제") or []
            parsed = normalize(data if isinstance(data, list) else [])
            if parsed:
                return parsed
        except Exception:
            continue

    blocks = []
    tagged_blocks = re.findall(r"\[주제 시작\](.*?)(?:\[주제 종료\]|$)", text, flags=re.DOTALL)
    if tagged_blocks:
        blocks = tagged_blocks
    else:
        titled_blocks = re.split(r"(?=^\s*(?:[-*]|\d+[\.\)])?\s*제목\s*[:：])", text, flags=re.MULTILINE)
        blocks = [block for block in titled_blocks if re.search(r"제목\s*[:：]", block)]

    parsed = []
    for block in blocks:
        title_match = re.search(r"제목\s*[:：]\s*(.+)", block)
        content_match = re.search(r"내용\s*[:：]\s*(.+)", block, flags=re.DOTALL)
        if title_match:
            title = clean_title(title_match.group(1), len(parsed) + 1)
            content = clean_content(content_match.group(1) if content_match else block.replace(title_match.group(0), "", 1))
            parsed.append({"title": title, "content": content})

    if parsed:
        return normalize(parsed)

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    fallback = []
    for paragraph in paragraphs[:2]:
        lines = [line.strip("-* 0123456789.)") for line in paragraph.splitlines() if line.strip()]
        if lines:
            fallback.append({"title": clean_title(lines[0], len(fallback) + 1), "content": clean_content("\n".join(lines[1:]) or paragraph)})
    return normalize(fallback)

def update_school_coordinates_if_missing(school):
    if not st.session_state.get("user") or not school or school.get("lat") and school.get("lng"):
        return school, None

    lat, lng = geocode_address(school.get("address"), school.get("name"))
    if not lat or not lng:
        return school, "학교 주소를 좌표로 변환하지 못했습니다. VWorld 키, 주소 형식, 앱 재시작 여부를 확인해 주세요."

    try:
        supabase.table("user_profiles").update({
            "school_lat": lat,
            "school_lng": lng,
        }).eq("id", st.session_state.user.id).execute()
    except Exception as e:
        return school, f"좌표는 계산됐지만 Supabase 저장에 실패했습니다: {e}"

    school["lat"] = lat
    school["lng"] = lng
    st.session_state.school = school
    return school, None

def fetch_open_labs_by_area(school):
    if not supabase:
        return [], "Supabase 연결을 확인해 주세요."

    try:
        rows = supabase.table("open_labs").select("*").eq("is_active", True).execute().data or []
    except Exception as e:
        return [], f"open_labs 테이블 조회 실패: {e}"

    labs = []
    school_lat, school_lng = school.get("lat"), school.get("lng")
    school_region = school.get("region")
    school_city = school.get("city") or extract_city(school.get("address"))

    for lab in rows:
        distance = None
        if school_lat and school_lng and lab.get("lat") and lab.get("lng"):
            try:
                distance = haversine_km(school_lat, school_lng, lab["lat"], lab["lng"])
            except Exception:
                distance = None

        lab_region = lab.get("region") or extract_region(lab.get("address"))
        lab_city = extract_city(lab.get("address"))
        lab["distance_km"] = distance
        if school_city and lab_city == school_city:
            lab["area_group"] = "해당 시/군/구"
            lab["area_rank"] = 0
        elif school_region and lab_region == school_region:
            lab["area_group"] = "같은 도"
            lab["area_rank"] = 1
        else:
            lab["area_group"] = "전국"
            lab["area_rank"] = 2
        labs.append(lab)

    return sorted(
        labs,
        key=lambda x: (
            x["area_rank"],
            x["distance_km"] if x["distance_km"] is not None else 9999,
            x.get("name") or "",
        ),
    ), None

def render_open_lab_card(lab):
    with st.container(border=True):
        lab_key = str(lab.get("id") or f"{lab.get('name', '')}-{lab.get('address', '')}")
        distance = lab.get("distance_km")
        distance_text = f"{distance:.1f}km" if distance is not None else "거리 계산 전"
        area_group = escape(str(lab.get("area_group") or "추천"))
        category = escape(str(lab.get("category") or "진로체험처"))
        title = escape(str(lab.get("name") or "이름 미상"))
        host = escape(str(lab.get("host_org") or "운영기관 정보 없음"))
        address = escape(str(lab.get("address") or "주소 정보 없음"))
        target = escape(str(lab.get("target") or "대상 정보 없음"))
        description = escape(str(lab.get("description") or "공개된 프로그램 정보를 확인해 보세요."))

        st.markdown(f"""
            <div class="openlab-card-head">
                <span class="paper-source-badge badge-openlab">{category}</span>
                <span class="openlab-distance">{area_group} · {distance_text}</span>
            </div>
            <div class="paper-title">{title}</div>
            <div class="paper-authors">🏛️ {host}</div>
            <div class="openlab-address">📍 {address}</div>
            <div class="paper-abstract"><strong>대상:</strong> {target}<br>{description}</div>
        """, unsafe_allow_html=True)

        homepage_url = lab.get("homepage_url")
        c1, c2 = st.columns([2, 6])
        with c1:
            if homepage_url:
                st.link_button("홈페이지 보기", homepage_url, use_container_width=True)
            else:
                st.button("홈페이지 없음", disabled=True, use_container_width=True, key=f"openlab_home_none_{lab_key}")

# ==========================================
# 2. 전역 상태(Session State) 초기화
# ==========================================
states = [
    'user', 'role', 'school', 'paper_results', 'seen_titles', 'search_page', 
    'ai_topics_list', 'past_topics', 'generated_manual', 'past_manuals', 'current_idea', 'current_sort', 'profile_edit'
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
                st.session_state.role = "연구자"
                st.session_state.school = build_school_profile(res.data[0])
        except: pass

    role_label = "연구자"
    school_label = st.session_state.school['name'] if st.session_state.school else "프로필 미설정"
    avatar_icon = "🔬"
    
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
        for s in ['user', 'role', 'school', 'profile_edit']: st.session_state[s] = None
        st.rerun()

st.sidebar.markdown("---")
model = None
gemini_api_key = None

try:
    gemini_api_key = st.secrets.get("GEMINI_API_KEY")
except Exception:
    gemini_api_key = None

# ✨ AI 모델 자동 탐색 (gemini-1.5-flash 최우선 적용)
if gemini_api_key:
    try:
        genai.configure(api_key=gemini_api_key)
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # 1.5-flash 모델이 있다면 가장 먼저 선택 (무료 한도가 넉넉함)
        if 'models/gemini-1.5-flash' in available_models:
            model = genai.GenerativeModel('models/gemini-1.5-flash')
        elif available_models:
            model = genai.GenerativeModel(available_models[0])
    except Exception as e: 
        st.sidebar.error(f"API 설정 오류: {e}")
else:
    st.sidebar.info("Gemini API 키가 Secrets에 설정되지 않았습니다.")

# ==========================================
# 🕹️ 상단 네비게이션
# ==========================================
st.write("") 

with st.container():
    st.markdown('<span class="top-menu-marker"></span>', unsafe_allow_html=True)
    menu = st.radio(
        "메뉴 선택", 
        ["메인", "논문 찾기", "실험 설계", "주변 진로체험처", "내 연구 노트"],
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
            <p style="color:rgba(255,255,255,0.8); font-size:1.2rem;">세상을 바꾸는 당신의 과학 탐구, AI가 지도를 그려드립니다.</p>
        </div>
    """, unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    features = [
        ("🔍", "논문 검색", "글로벌 DB 통합 탐색<br>논문 기반 AI 탐구 주제 제안"), 
        ("🧪", "실험 설계", "탐구 주제 기반 AI 실험 매뉴얼 생성<br>실험 세부 사항 설정 가능"), 
        ("🧭", "주변 진로체험처", "학교 위치 기반 거리순 체험처 추천<br>공공기관, 대학, 과학관 등"),
        ("🗄️", "연구 노트", "나만의 탐구 포트폴리오<br>논문, 탐구 주제, 실험 매뉴얼 저장")
    ]
    for col, (i, t, d) in zip([c1, c2, c3, c4], features):
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
            keyword = st.text_input("검색어 입력", placeholder="", label_visibility="collapsed")
            st.markdown("""
                <div class="search-guide">
                    <div>키워드 중심으로 짧고 구체적으로 입력하면 논문을 더 잘 찾을 수 있습니다.</div>
                    <div>영어 키워드로 검색하면 더 많은 해외 논문이 검색됩니다.</div>
                </div>
            """, unsafe_allow_html=True)
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
                st.warning("Gemini API 키가 아직 설정되지 않았습니다. Streamlit Secrets에 GEMINI_API_KEY를 추가해 주세요.")
            else:
                btn_text = "✨ 주제 추천받기" if not st.session_state.ai_topics_list else "🔄 새로운 주제 추가로 받기"
                
                if st.button(btn_text, use_container_width=True, type="primary"):
                    with st.spinner("논문을 분석 중입니다..."):
                        prompt = f"""
                        다음 논문들을 참고해 창의적인 고등학생용 연구 주제 2개를 제안해줘.
                        반드시 JSON 배열만 출력해줘. 설명 문장이나 코드블록은 쓰지 마.
                        각 항목은 title, content 키를 가진 객체여야 해.

                        예시:
                        [
                          {{
                            "title": "주제 제목",
                            "content": "탐구 동기, 실험 방법, 기대 효과 등 상세 설명"
                          }}
                        ]
                        
                        논문 리스트: {[p['title'] for p in st.session_state.paper_results[:5]]}
                        """
                        if st.session_state.past_topics: 
                            prompt += f"\n[중요] 이전 추천들과 절대 겹치지 않게 해:\n" + "\n".join(st.session_state.past_topics)
                        
                        try:
                            response = model.generate_content(prompt).text
                            st.session_state.past_topics.append(response)

                            parsed_topics = parse_research_topics(response)
                            if not parsed_topics:
                                st.warning("AI 응답에서 추천 주제를 읽지 못했습니다. 다시 한 번 눌러 주세요.")
                            else:
                                existing_titles = {
                                    re.sub(r"\W+", "", topic["title"].lower())
                                    for topic in st.session_state.ai_topics_list
                                }
                                for topic in parsed_topics:
                                    topic_key = re.sub(r"\W+", "", topic["title"].lower())
                                    if topic_key not in existing_titles:
                                        st.session_state.ai_topics_list.append(topic)
                                        existing_titles.add(topic_key)
                        except Exception as e:
                            error_msg = str(e)
                            if "429" in error_msg or "Quota" in error_msg:
                                st.warning("⏳ 구글 API 무료 호출 횟수(1분당 15회)를 초과했습니다. 약 1분만 기다렸다가 다시 눌러주세요!")
                            else:
                                st.error("AI 호출에 실패했습니다. API 키를 확인해 주세요.")

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
        st.markdown("<h2 style='text-align: center; color: white; margin-bottom: 1.5rem;'>🧪 실험 설계 AI</h2>", unsafe_allow_html=True)
        
        topic_col, guide_col = st.columns([5, 1.6])
        with topic_col:
            st.markdown("<span class='label-essential'>🎯 탐구 주제 (필수)</span>", unsafe_allow_html=True)
            topic = st.text_input("topic", placeholder="비타민 C 항산화 반응 속도 측정 등", label_visibility="collapsed")
        with guide_col:
            st.markdown("<div class='experiment-required-note'>필수 입력</div>", unsafe_allow_html=True)

        ind_var, dep_var, materials, idea_details = "", "", "", ""
        with st.expander("선택 입력 열기: 변인, 준비물, 상세 요청 사항", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("<span class='label-optional'>➡️ 독립 변인 (선택)</span>", unsafe_allow_html=True)
                ind_var = st.text_input("ind", placeholder="비타민 C 수용액의 농도 등", label_visibility="collapsed")

                st.markdown("<span class='label-optional'>🧫 준비물 (선택)</span>", unsafe_allow_html=True)
                materials = st.text_input("mat", placeholder="아이오딘 용액, 전분, 비커 등", label_visibility="collapsed")

            with col2:
                st.markdown("<span class='label-optional'>📈 종속 변인 (선택)</span>", unsafe_allow_html=True)
                dep_var = st.text_input("dep", placeholder="아이오딘 용액의 탈색 시간 등", label_visibility="collapsed")

                st.markdown("<span class='label-optional'>💡 상세 아이디어 및 요청 사항 (선택)</span>", unsafe_allow_html=True)
                idea_details = st.text_area("details", placeholder="실험 과정에서 특히 신경 쓰고 싶은 부분을 자유롭게 적어주세요.", label_visibility="collapsed", height=96)
        
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
        elif not gemini_api_key or model is None:
            st.error("❗ Streamlit Secrets에 GEMINI_API_KEY를 먼저 설정해 주세요.")
        else:
            with st.spinner("AI가 안전 수칙을 검토하며 체계적인 매뉴얼을 작성 중입니다..."):
                prompt = f"""
                연구자의 실험 아이디어를 바탕으로 고등학생 수준에 맞는 안전하고 구체적인 실험 매뉴얼을 작성해줘.
                
                [연구 아이디어]
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
                - 마지막 줄에 '> ⚠️ **지도자 임장 지도 필수**' 라는 문구를 인용구 형태로 꼭 넣을 것.
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
# 🧭 4. 주변 진로체험처
# ==========================================
elif menu == "주변 진로체험처":
    st.markdown("""
        <div class="openlab-hero">
            <span class="openlab-marker"></span>
            <h2>🧭 학교 주변 진로체험처</h2>
            <p>학교 위치를 기준으로 연구와 진로 탐색에 참고할 만한 공공기관, 대학, 청소년단체를 가까운 순서로 정리합니다.</p>
        </div>
    """, unsafe_allow_html=True)

    if not st.session_state.user:
        st.warning("왼쪽 사이드바에서 로그인하면 학교 위치 기반 추천을 볼 수 있습니다.")
    elif not st.session_state.school:
        st.warning("먼저 '내 연구 노트'에서 학교 프로필을 설정해 주세요.")
    else:
        school = st.session_state.school
        st.markdown(f"""
            <div class="openlab-school-card">
                <span class="paper-source-badge badge-openlab">기준 학교</span>
                <div class="note-profile-title">{escape(str(school.get('name') or '학교 정보 없음'))}</div>
                <div class="paper-authors">📍 {escape(str(school.get('address') or '주소 정보 없음'))}</div>
            </div>
        """, unsafe_allow_html=True)

        if not school.get("lat") or not school.get("lng"):
            with st.spinner("학교 주소를 좌표로 변환해 다시 저장하는 중입니다..."):
                school, geocode_error = update_school_coordinates_if_missing(school)
            if geocode_error:
                st.warning("학교 좌표가 아직 저장되지 않았습니다. 그래도 주소를 기준으로 같은 시/군/구, 같은 도, 전국 순서로 보여줍니다.")
                st.caption(geocode_error)
                if st.session_state.get("geocode_debug"):
                    st.caption(f"VWorld 응답: {st.session_state.geocode_debug}")
            else:
                st.success(f"학교 좌표를 저장했습니다: {school.get('lat'):.6f}, {school.get('lng'):.6f}")

        labs, error = fetch_open_labs_by_area(school)

        if error:
            st.error(error)
            st.info("Supabase에 open_labs 테이블과 진로체험처 데이터가 준비되어 있는지 확인해 주세요.")
        elif not labs:
            st.warning("표시할 진로체험처를 찾지 못했습니다. open_labs 데이터를 추가해 주세요.")
        else:
            total_count = len(labs)
            local_count = sum(1 for lab in labs if lab.get("area_rank") == 0)
            province_count = sum(1 for lab in labs if lab.get("area_rank") in (0, 1))
            national_count = total_count
            stat_all, stat_local, stat_region, stat_national = st.columns(4)
            stat_all.markdown(f"<div class='openlab-stat-card'><span>전체 진로체험처</span><strong>{total_count}</strong></div>", unsafe_allow_html=True)
            stat_local.markdown(f"<div class='openlab-stat-card'><span>같은 시/군/구</span><strong>{local_count}</strong></div>", unsafe_allow_html=True)
            stat_region.markdown(f"<div class='openlab-stat-card'><span>같은 도</span><strong>{province_count}</strong></div>", unsafe_allow_html=True)
            stat_national.markdown(f"<div class='openlab-stat-card'><span>전국</span><strong>{national_count}</strong></div>", unsafe_allow_html=True)

            scope = st.radio(
                "추천 범위",
                ["같은 시/군/구", "같은 도", "전국"],
                horizontal=True,
                label_visibility="collapsed",
                key="openlab_scope",
            )

            if scope == "같은 시/군/구":
                scoped_labs = [lab for lab in labs if lab.get("area_rank") == 0]
                empty_message = "현재 학교와 같은 시/군/구에 등록된 진로체험처가 없습니다."
                group_title = "해당 시/군/구"
            elif scope == "같은 도":
                scoped_labs = [lab for lab in labs if lab.get("area_rank") in (0, 1)]
                empty_message = "현재 학교와 같은 도에 등록된 진로체험처가 없습니다."
                group_title = "같은 도"
            else:
                scoped_labs = labs
                empty_message = "표시할 전국 진로체험처가 없습니다."
                group_title = "전국"

            scoped_labs = sorted(
                scoped_labs,
                key=lambda lab: (
                    lab["distance_km"] if lab.get("distance_km") is not None else 9999,
                    lab.get("name") or "",
                ),
            )

            if not scoped_labs:
                st.warning(empty_message)
            else:
                page_size = 5
                total_pages = (len(scoped_labs) + page_size - 1) // page_size
                page_options = [str(page) for page in range(1, total_pages + 1)]
                page_choice = st.radio(
                    "페이지",
                    page_options,
                    horizontal=True,
                    label_visibility="collapsed",
                    key="openlab_local_page",
                )
                page_index = int(page_choice) - 1
                start = page_index * page_size
                end = start + page_size

                st.markdown(f"<div class='openlab-group-title'>{escape(group_title)}</div>", unsafe_allow_html=True)
                for lab in scoped_labs[start:end]:
                    render_open_lab_card(lab)

# ==========================================
# 🗄️ 5. 내 연구 노트
# ==========================================
elif menu == "내 연구 노트":
    st.markdown("""
        <div class="note-hero">
            <span class="note-marker"></span>
            <h2>🗄️ 내 연구 노트</h2>
            <p>찾아둔 논문, AI가 제안한 탐구 주제, 실험 매뉴얼을 한곳에 모아 관리하세요.</p>
        </div>
    """, unsafe_allow_html=True)

    if not st.session_state.user: st.warning("왼쪽 사이드바에서 로그인 해주세요.")
    else:
        if not st.session_state.school or st.session_state.profile_edit:
            with st.container():
                st.markdown('<span class="note-profile-marker"></span>', unsafe_allow_html=True)
                st.markdown("<h3 class='note-section-title'>👋 프로필 설정</h3>", unsafe_allow_html=True)
                st.markdown("<p class='note-section-caption'>학교 정보를 연결하면 주변 진로체험처 추천과 연구 노트 저장 기능을 더 정확하게 사용할 수 있어요.</p>", unsafe_allow_html=True)
                search_col, button_col = st.columns([5, 1.4])
                with search_col:
                    keyword = st.text_input("학교 이름 검색", placeholder="학교 이름을 입력하세요", label_visibility="collapsed")
                with button_col:
                    search_clicked = st.button("검색", use_container_width=True, type="primary")

                if search_clicked and keyword:
                    try:
                        res = requests.get("https://open.neis.go.kr/hub/schoolInfo", params={"Type": "json", "pIndex": 1, "pSize": 5, "SCHUL_NM": keyword}).json()
                        st.session_state.search_results = res.get("schoolInfo", [{}, {"row": []}])[1].get("row", [])
                    except: st.error("네트워크 오류")
            
            if st.session_state.get('search_results'):
                st.write("")
                for idx, school in enumerate(st.session_state.search_results):
                    s_name, s_code, s_addr = school.get('SCHUL_NM'), school.get('SD_SCHUL_CODE'), school.get('ORG_RDNMA')
                    with st.container(border=True):
                        col1, col2 = st.columns([5, 1])
                        with col1:
                            st.markdown(f"""
                                <div class="paper-source-badge badge-note">학교 프로필</div>
                                <div class="paper-title">{escape(str(s_name))}</div>
                                <div class="paper-authors">{escape(str(s_addr or '주소 정보 없음'))}</div>
                            """, unsafe_allow_html=True)
                        with col2:
                            if st.button("선택", key=f"profile_school_{s_code}_{idx}", use_container_width=True):
                                try:
                                    selected_school = save_school_profile(
                                        st.session_state.user.id,
                                        s_name,
                                        s_code,
                                        s_addr,
                                    )
                                    st.session_state.role = "연구자"
                                    st.session_state.school = selected_school
                                    st.session_state.search_results = None
                                    st.session_state.profile_edit = False
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"저장 실패: {e}")
        else:
            st.markdown(f"""
                <div class="note-profile-summary">
                    <div>
                        <span class="paper-source-badge badge-note">현재 프로필</span>
                        <div class="note-profile-title">{escape(str(st.session_state.school.get('name')))}</div>
                        <div class="paper-authors">연구자 | {escape(str(st.session_state.school.get('address') or '주소 정보 없음'))}</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            _, action_col = st.columns([5, 1])
            with action_col:
                if st.button("프로필 수정", use_container_width=True):
                    st.session_state.profile_edit = True
                    st.rerun()

            saved_list, topic_list, manual_list = [], [], []
            try:
                saved_list = supabase.table("saved_papers").select("*").eq("user_id", st.session_state.user.id).order("created_at", desc=True).execute().data or []
                topic_list = supabase.table("saved_topics").select("*").eq("user_id", st.session_state.user.id).order("created_at", desc=True).execute().data or []
                manual_list = supabase.table("saved_manuals").select("*").eq("user_id", st.session_state.user.id).order("created_at", desc=True).execute().data or []
            except Exception:
                st.error("저장된 연구 노트를 불러오지 못했습니다.")

            stat_p, stat_t, stat_m = st.columns(3)
            stat_p.markdown(f"<div class='note-stat-card'><span>저장된 논문</span><strong>{len(saved_list)}</strong></div>", unsafe_allow_html=True)
            stat_t.markdown(f"<div class='note-stat-card'><span>추천 주제</span><strong>{len(topic_list)}</strong></div>", unsafe_allow_html=True)
            stat_m.markdown(f"<div class='note-stat-card'><span>실험 매뉴얼</span><strong>{len(manual_list)}</strong></div>", unsafe_allow_html=True)

            tab_p, tab_t, tab_m = st.tabs(["📚 저장된 논문", "💡 추천 실험 주제", "📋 실험 매뉴얼"])
            with tab_p:
                if not saved_list:
                    st.markdown("<div class='note-empty'>아직 저장된 논문이 없습니다. 논문 찾기에서 관심 있는 자료를 저장해 보세요.</div>", unsafe_allow_html=True)
                for paper in saved_list:
                    paper_title = str(paper.get('title') or '제목 없음')
                    paper_year = str(paper.get('year') or '연도 미상')
                    paper_source = str(paper.get('source') or 'Paper')
                    paper_label_title = paper_title if len(paper_title) <= 80 else f"{paper_title[:80]}..."
                    with st.expander(f"📚 {paper_label_title} · {paper_source} · {paper_year}", expanded=False):
                        st.markdown(f"""
                            <div class="paper-source-badge badge-arxiv">{escape(paper_source)} • {escape(paper_year)}</div>
                            <div class="paper-title">{escape(paper_title)}</div>
                            <div class="paper-authors">저자: {escape(str(paper.get('authors') or '정보 없음'))}</div>
                            <div class="paper-abstract">{escape(str(paper.get('summary') or '초록 정보가 없습니다.'))}</div>
                        """, unsafe_allow_html=True)
                        link_col, delete_col, _ = st.columns([2, 1.2, 5])
                        with link_col:
                            st.link_button("📄 원문 링크", paper['url'], use_container_width=True)
                        with delete_col:
                            if st.button("🗑️ 삭제", key=f"del_p_{paper['id']}", use_container_width=True):
                                supabase.table("saved_papers").delete().eq("id", paper['id']).execute()
                                st.rerun()
            with tab_t:
                if not topic_list:
                    st.markdown("<div class='note-empty'>저장된 주제가 없습니다. 논문 분석 결과에서 탐구 주제를 저장하면 이곳에 쌓입니다.</div>", unsafe_allow_html=True)
                for topic in topic_list:
                    topic_content = str(topic.get('topic_content') or '내용 없음')
                    topic_date = str(topic.get('created_at') or '')[:10]
                    topic_title = "추천 실험 주제"
                    for line in topic_content.splitlines():
                        clean_line = line.strip()
                        if clean_line.startswith("제목:"):
                            topic_title = clean_line.replace("제목:", "", 1).strip() or topic_title
                            break
                    topic_label_title = topic_title if len(topic_title) <= 80 else f"{topic_title[:80]}..."
                    with st.expander(f"💡 {topic_label_title} · {topic_date}", expanded=False):
                        st.markdown(f"""
                            <div class="paper-source-badge badge-topic">추천 주제 • {escape(topic_date)}</div>
                            <div class="paper-title">{escape(topic_title)}</div>
                            <div class="paper-abstract note-full-text">{escape(topic_content)}</div>
                        """, unsafe_allow_html=True)
                        if st.button("🗑️ 삭제", key=f"del_t_{topic['id']}"):
                            supabase.table("saved_topics").delete().eq("id", topic['id']).execute()
                            st.rerun()
            with tab_m:
                if not manual_list:
                    st.markdown("<div class='note-empty'>저장된 매뉴얼이 없습니다. 실험 설계에서 만든 매뉴얼을 저장해 보세요.</div>", unsafe_allow_html=True)
                for manual in manual_list:
                    manual_idea = str(manual.get('idea') or '원본 아이디어 없음')
                    manual_label_title = manual_idea if len(manual_idea) <= 80 else f"{manual_idea[:80]}..."
                    with st.expander(f"📋 {manual_label_title}", expanded=False):
                        st.markdown(f"""
                            <div class="paper-source-badge badge-manual">실험 매뉴얼</div>
                            <div class="paper-title">{escape(manual_idea)}</div>
                        """, unsafe_allow_html=True)
                        st.markdown(manual.get('manual_content') or '내용 없음')
                        st.divider()
                        if st.button("🗑️ 삭제", key=f"del_m_{manual['id']}"):
                            supabase.table("saved_manuals").delete().eq("id", manual['id']).execute()
                            st.rerun()
