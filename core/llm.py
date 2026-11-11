"""AI 모델 호출 (OpenAI / Claude). API 키는 세션에서만 쓰고 저장하지 않음."""

import os
import time

PROVIDERS = ["OpenAI", "Claude", "체험 모드 (API 없이)"]
MODEL_CHOICES = {
    "OpenAI": ["gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-sol"],
    "Claude": ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
}
DEMO = "체험 모드 (API 없이)"


def env_api_key(provider: str, secrets=None) -> str:
    """secrets.toml 또는 환경변수에 등록된 키 (개인 PC에서 실행할 때 편의용)"""
    name = "OPENAI_API_KEY" if provider == "OpenAI" else "ANTHROPIC_API_KEY"
    try:
        if secrets is not None and name in secrets:
            return secrets[name]
    except Exception:
        pass
    return os.environ.get(name, "")


class LLMError(RuntimeError):
    pass


def call_llm(cfg: dict, system: str, user: str, json_mode: bool = False, retries: int = 2) -> str:
    """cfg: {"provider", "model", "api_key"} — 일시적 오류는 잠시 기다렸다 다시 시도"""
    provider = cfg.get("provider")
    if provider == DEMO:
        raise LLMError("체험 모드에서는 AI를 호출하지 않습니다.")
    key = cfg.get("api_key", "")
    if not key:
        raise LLMError("왼쪽 사이드바에 API 키를 입력하세요.")

    last = None
    for attempt in range(retries + 1):
        try:
            if provider == "OpenAI":
                return _openai(cfg["model"], key, system, user, json_mode)
            return _claude(cfg["model"], key, system, user, json_mode)
        except Exception as e:  # 네트워크·한도 초과 등
            last = e
            msg = str(e).lower()
            transient = any(w in msg for w in ("rate", "429", "timeout", "overloaded", "529", "503", "502"))
            if not transient or attempt == retries:
                break
            time.sleep(3 * (attempt + 1))
    raise LLMError(_friendly(last))


def _openai(model, key, system, user, json_mode):
    from openai import OpenAI

    client = OpenAI(api_key=key)
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    res = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        **kwargs,
    )
    return res.choices[0].message.content or ""


def _claude(model, key, system, user, json_mode):
    import anthropic

    client = anthropic.Anthropic(api_key=key)
    if json_mode:
        user += "\n\n반드시 JSON 객체 하나만 출력하세요."
    res = client.messages.create(
        model=model,
        max_tokens=3000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in res.content if getattr(b, "type", "") == "text")


def _friendly(e) -> str:
    msg = str(e)
    low = msg.lower()
    if "401" in low or "invalid" in low and "key" in low or "authentication" in low:
        return "API 키가 올바르지 않습니다. 키를 다시 확인해 주세요."
    if "429" in low or "rate" in low or "quota" in low or "credit" in low:
        return "사용 한도를 넘었거나 잔액이 부족합니다. 잠시 후 다시 시도하거나 결제 정보를 확인해 주세요."
    if "model" in low and ("not found" in low or "does not exist" in low or "404" in low):
        return "선택한 모델을 쓸 수 없습니다. 사이드바에서 다른 모델을 선택하거나 모델 이름을 확인해 주세요."
    return f"AI 호출 중 오류가 발생했습니다: {msg[:300]}"
