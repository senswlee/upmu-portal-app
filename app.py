"""
업무포털 자동화 도우미 (나이스 · 에듀파인)
실행:  streamlit run app.py
"""

import streamlit as st

st.set_page_config(page_title="업무포털 자동화 도우미", page_icon="🏫", layout="centered")

from core import ui                                   # noqa: E402
from engines import document_engine, record_engine, tools   # noqa: E402
from writers import MENU, WRITERS                     # noqa: E402

TOOLS = {"사용 안내": tools.guide_page, "참고 자료실": tools.library_page, "기본 자료 점검": tools.check_page}

# ── 사이드바: 업무포털 → 작성기 선택, AI 설정 ──
with st.sidebar:
    st.title("🏫 업무포털 도우미")
    portal = st.radio("업무포털", ["나이스", "에듀파인", "도구"], horizontal=True, key="nav_portal")
    if portal == "도구":
        menu = st.radio("도구", list(TOOLS), key="nav_tool")
    else:
        menu = st.radio(f"{portal} 작성기", list(MENU[portal]), key=f"nav_{portal}",
                        captions=None if portal != "나이스" else ["행동특성 및 종합의견", "자율·동아리 특기사항",
                                                                  "교과 세부능력 및 특기사항"])
    st.divider()
    ui.sidebar_ai_settings()
    st.divider()
    st.caption("입력 내용과 API 키는 저장되지 않습니다.    \nAI 결과는 초안이며    \n최종 확인은 교사가 합니다.")

# ── 본문 ──
if portal == "도구":
    TOOLS[menu]()
else:
    target = MENU[portal][menu]
    if isinstance(target, list):      # 창체: 자율 / 동아리 선택 (GPTs의 '자율' / '동아리' 질문과 같은 흐름)
        st.markdown("##### 창체작성기")
        kind = st.segmented_control("어떤 특기사항을 작성할까요?", ["자율", "동아리"], default="자율",
                                    key="nav_changche") or "자율"
        target = target[0] if kind == "자율" else target[1]
    w = WRITERS[target]
    if ui.is_demo():
        st.info("🧪 체험 모드입니다. AI를 호출하지 않고 예시 결과로 화면 흐름만 보여 줍니다.")
    (record_engine if w["engine"] == "record" else document_engine).render(w)
