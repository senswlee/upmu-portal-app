"""여러 화면이 함께 쓰는 Streamlit 부품: 상태 관리, 사이드바 설정, 참고 자료 패널, 결과 표시"""

import copy

import streamlit as st

from core import llm
from core.resources import SUPPORTED, bytes_to_text, limit_text, read_resource
from core.text_utils import count_chars, neis_bytes


# ── 작성기별 상태 (작성기를 바꿔도 내용이 섞이지 않게 분리) ──
def wstate(wid: str, defaults: dict) -> dict:
    key = f"__state_{wid}"
    if key not in st.session_state:
        st.session_state[key] = copy.deepcopy(defaults)
    return st.session_state[key]


def reset_writer(wid: str, defaults: dict):
    st.session_state[f"__state_{wid}"] = copy.deepcopy(defaults)
    for k in [k for k in st.session_state.keys() if isinstance(k, str) and k.startswith(f"{wid}__")]:
        if not k.endswith("__uploads"):          # 올린 참고 파일은 새 학생에도 계속 사용
            del st.session_state[k]


def wkey(wid: str, name: str) -> str:
    return f"{wid}__{name}"


# ── 사이드바: AI 설정 ───────────────────────────
def sidebar_ai_settings() -> dict:
    st.subheader("⚙️ AI 설정")
    provider = st.radio("AI 서비스", llm.PROVIDERS, key="cfg_provider",
                        help="API 키가 없으면 '체험 모드'로 화면 흐름만 확인할 수 있습니다.")
    model, key = "", ""
    if provider != llm.DEMO:
        options = llm.MODEL_CHOICES[provider] + ["직접 입력"]
        choice = st.selectbox("모델", options, key=f"cfg_model_{provider}")
        model = st.text_input("모델 이름", key=f"cfg_model_custom_{provider}",
                              placeholder="예: gpt-5.6-terra") if choice == "직접 입력" else choice
        typed = st.text_input("API 키", type="password", key=f"cfg_key_{provider}",
                              help="키는 이 창(세션)에서만 쓰이며 서버에 저장되지 않습니다.")
        key = typed or llm.env_api_key(provider, getattr(st, "secrets", None) if _has_secrets() else None)
        if not key:
            st.caption("🔑 API 키를 입력해야 AI가 작성합니다.")
    cfg = {"provider": provider, "model": model, "api_key": key}
    st.session_state["cfg"] = cfg
    return cfg


def _has_secrets() -> bool:
    try:
        return len(st.secrets) > 0
    except Exception:
        return False


def is_demo() -> bool:
    return st.session_state.get("cfg", {}).get("provider") == llm.DEMO


# ── 참고 자료 패널 (기본 자료 + 선택 업로드) ─────
def reference_panel(wid: str, resources: dict) -> dict:
    """resources: {"examples": 경로, "reference": 경로 또는 설명, "guides": [경로...]}
    반환: {"teacher_examples": str, "guides": str, "uploads": [(이름, 텍스트)], "replace": bool}"""
    examples_text = read_resource(resources["examples"]) if resources.get("examples") else ""
    guides_text = "\n\n".join(read_resource(p) for p in resources.get("guides", []))

    with st.expander("📚 참고 자료 — 기본 자료가 적용되어 있습니다 (내 자료 추가는 선택)", expanded=False):
        files = ([("교사 예시문 (문체·톤 기준)", resources["examples"])] if resources.get("examples") else [])
        if resources.get("reference_label"):
            files.append((resources["reference_label"], resources.get("reference_file", "")))
        files += [("작성요령", p) for p in resources.get("guides", [])]
        st.markdown("**적용 중인 기본 자료**")
        for label, path in files:
            st.caption(f"• {label}: `{path.split('/')[-1]}`" if path else f"• {label}")
        names = [f"{label} — {path.split('/')[-1]}" for label, path in files if path and not path.endswith(".json")]
        if names:
            pick = st.selectbox("내용 미리보기", ["(선택 안 함)"] + names, key=wkey(wid, "preview"))
            if pick != "(선택 안 함)":
                path = [p for (l, p) in files if p and pick.endswith(p.split('/')[-1])][0]
                st.text_area("미리보기", read_resource(path)[:4000], height=220, disabled=True,
                             key=wkey(wid, f"preview_text_{abs(hash(pick))}"), label_visibility="collapsed")

        st.divider()
        st.markdown("**내 자료 올리기 (선택)** — 나만의 예시문이나 참고 파일을 올리면 함께 반영합니다.")
        ups = st.file_uploader("파일 선택", type=SUPPORTED, accept_multiple_files=True,
                               key=wkey(wid, "uploads"), label_visibility="collapsed",
                               help="txt, md, pdf, docx, hwpx 지원 · 구형 hwp는 PDF로 저장 후 올려 주세요. "
                                    "올린 파일은 저장되지 않으며 창을 닫으면 사라집니다.")
        uploads, replace = [], False
        cache = st.session_state.setdefault("__upload_cache", {})
        for f in ups or []:
            ck = f"{f.name}:{f.size}"
            if ck not in cache:
                try:
                    cache[ck] = ("ok", bytes_to_text(f.getvalue(), f.name))
                except Exception as e:
                    cache[ck] = ("error", str(e))
            status, text = cache[ck]
            if status == "error":
                st.error(f"{f.name}: {text}")
                continue
            if not text.strip():
                st.warning(f"{f.name}: 글자를 읽지 못했습니다. 스캔본 PDF일 수 있습니다.")
                continue
            text, cut = limit_text(text)
            st.caption(f"✅ {f.name} — {len(text):,}자 반영" + (" (분량이 많아 앞부분만 반영)" if cut else ""))
            uploads.append((f.name, text))
        if uploads:
            mode = st.radio("반영 방식", ["기본 자료 + 내 자료 함께 (권장)", "내 자료로 대체 (기본 예시문 제외)"],
                            key=wkey(wid, "upload_mode"),
                            help="작성요령(기재 규칙)은 어느 방식이든 항상 적용됩니다.")
            replace = mode.startswith("내 자료로 대체")

    return {"teacher_examples": examples_text, "guides": guides_text, "uploads": uploads, "replace": replace}


def uploads_block(uploads: list) -> str:
    return "\n\n".join(f"### {name}\n{text}" for name, text in uploads)


# ── 결과 표시 ──────────────────────────────────
def length_metrics(text: str, unit: str, target: int, max_bytes: int, hard: bool):
    b, c = neis_bytes(text), count_chars(text)
    col1, col2 = st.columns(2)
    if unit == "bytes":
        over = b > target
        col1.metric("나이스 바이트", f"{b:,} / {target:,}",
                    delta=f"{b - target:,} 초과" if over else f"{target - b:,} 남음",
                    delta_color="inverse" if over else "normal")
        col2.metric("글자 수 (공백 포함)", f"{c:,}자")
    else:
        lo, hi = int(target * 0.8), int(target * 1.2)
        state = "적정" if lo <= c <= hi else ("많음" if c > hi else "적음")
        col1.metric("글자 수 (공백 포함)", f"{c:,}자", delta=f"목표 {target}자 내외 · {state}",
                    delta_color="off" if state == "적정" else "inverse")
        col2.metric("나이스 바이트", f"{b:,} / {max_bytes:,}")
    if b > max_bytes:
        st.error(f"나이스 입력 한도({max_bytes:,}바이트)를 넘었습니다. '더 짧게'를 누르거나 직접 줄여 주세요.")
    elif hard and unit == "bytes" and b > target:
        st.error("바이트 제한을 넘었습니다. '더 짧게'를 누르거나 직접 줄여 주세요.")


def show_issues(issues: list):
    if not issues:
        st.success("✔ 자동 점검: 이름, 서식 기호, 기재 금지 표현, 어미 규칙에서 문제가 발견되지 않았습니다.")
        return
    with st.container(border=True):
        st.markdown("**🔎 자동 점검 결과** — 기재 전에 확인해 주세요")
        for level, msg in issues:
            {"error": st.error, "warning": st.warning}.get(level, st.info)(msg)


def copy_box(text: str, hint: str):
    st.caption(hint)
    st.code(text, language=None, wrap_lines=True)
