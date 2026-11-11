"""도구 화면: 사용 안내, 참고 자료실, 기본 자료 점검"""

import json
from collections import Counter

import streamlit as st

from core.resources import RES, list_resources, read_resource


def guide_page():
    st.subheader("📖 사용 안내")
    st.markdown("""
**업무포털 자동화 도우미**는 교사의 관찰과 입력을 바탕으로 나이스·에듀파인 문서의 **초안**을 만들어 주는 도구입니다.

**1. AI 설정** — 왼쪽 사이드바에서 OpenAI 또는 Claude를 고르고 본인의 API 키를 입력합니다.
키가 없으면 **체험 모드**로 화면 흐름을 먼저 살펴볼 수 있습니다.

**2. 작성기 선택** — 업무포털(나이스/에듀파인)과 작성기를 고릅니다.
- 나이스: 행발 · 창체(자율/동아리) · 세특
- 에듀파인: 기안 · 품의

**3. 단계별 진행** — 화면 안내에 따라 자료를 입력하고, 분석 결과를 확인·수정한 뒤 최종 문장을 받습니다.
결과는 직접 고칠 수 있고, 나이스 바이트와 기재 금지 표현을 자동으로 점검합니다.

**4. 참고 자료 (선택)** — 기본 예시문과 작성요령이 이미 적용되어 있습니다.
나만의 예시문이 있으면 각 작성기의 '참고 자료'에서 올려 문체를 맞출 수 있습니다.
""")
    st.warning("""
**개인정보와 책임 안내**
- 입력한 내용은 선택한 AI 회사(OpenAI 또는 Anthropic)의 API로 전송되며, 이 앱의 서버에는 저장되지 않습니다.
- 학생 실명 대신 '학생'으로 입력하거나, 이름 칸을 쓰면 AI로 보내기 전에 자동으로 바뀝니다.
- AI가 만든 문장은 **초안**입니다. 사실 여부와 기재요령 준수 여부를 확인하고, 최종 기재 책임은 교사에게 있습니다.
""")
    with st.expander("API 키는 어떻게 만드나요?"):
        st.markdown("""
- **OpenAI**: platform.openai.com 로그인 → API keys → Create new secret key → 결제(Billing)에서 크레딧 충전
- **Claude**: console.anthropic.com 로그인 → API Keys → Create Key → Billing에서 크레딧 충전

키는 `sk-...`로 시작하는 긴 문자열입니다. 다른 사람과 공유하지 마세요.
학생 1명 작성 비용은 보통 수 원~수십 원 수준입니다.
""")


def library_page():
    st.subheader("📚 참고 자료실")
    st.caption("작성기에서 기본으로 쓰는 자료의 원본 문서입니다. 원본 PDF는 AI에 보내지 않고 열람용으로만 제공합니다.")
    originals = sorted((RES / "originals").glob("*.pdf"))
    for p in originals:
        c1, c2 = st.columns([4, 1])
        c1.markdown(f"📄 **{p.stem}**  \n<span style='color:gray;font-size:0.85em'>{p.stat().st_size / 1_048_576:.1f}MB</span>",
                    unsafe_allow_html=True)
        c2.download_button("내려받기", p.read_bytes(), file_name=p.name, mime="application/pdf",
                           key=f"dl_{p.name}", use_container_width=True)
    st.divider()
    st.markdown("**작성요령 요약본** (작성기에 적용되는 규칙)")
    for rel in ["neis/공통_기재유의사항.txt", "neis/행발_작성요령.txt", "neis/창체_작성요령.txt",
                "neis/세특_작성요령.txt", "edufine/기안품의_작성요령.txt"]:
        with st.expander(rel.split("/")[-1].replace(".txt", "").replace("_", " ")):
            st.text(read_resource(rel))


def check_page():
    st.subheader("🔎 기본 자료 점검")
    st.caption("배포 전에 resources 폴더의 파일이 제대로 읽히는지 확인하는 화면입니다.")
    rows = list_resources()
    for rel, size in rows:
        if rel.startswith("originals/"):
            continue
        if rel.endswith(".json"):
            data = json.loads((RES / rel).read_text(encoding="utf-8"))
            with st.expander(f"✅ {rel} — 예시 {len(data)}개"):
                st.write(dict(Counter(x["level"] for x in data)))
                subjects = sorted({f"{x['level']}·{x['subject']}" for x in data})
                st.caption(", ".join(subjects))
            continue
        try:
            text = read_resource(rel)
            ok = bool(text.strip())
            with st.expander(f"{'✅' if ok else '⚠️'} {rel} — {len(text):,}자 ({size / 1024:.1f}KB)"):
                st.text(text[:2000] + ("\n…" if len(text) > 2000 else ""))
        except Exception as e:
            st.error(f"❌ {rel}: {e}")
    st.markdown("**원본 PDF**")
    for rel, size in rows:
        if rel.startswith("originals/"):
            st.caption(f"• {rel.split('/')[-1]} ({size / 1_048_576:.1f}MB) — 열람용")
