import json

from openai import OpenAI

from ..config import settings


def summarize_section(section: str, payload: dict) -> str:
    if not settings.openai_api_key:
        return _fallback_summary(section, payload)

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        prompt = (
            "You are ForecastHub assistant. Summarize this dashboard payload in 2 short bullet points "
            "with practical advice and no hype.\n"
            f"Section: {section}\n"
            f"Payload: {json.dumps(payload, default=str)}"
        )
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": "Write concise, practical weather guidance."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=150,
        )
        message = response.choices[0].message.content or ""
        cleaned = message.strip()
        if cleaned:
            return cleaned
    except Exception:
        pass

    return _fallback_summary(section, payload)


def _fallback_summary(section: str, payload: dict) -> str:
    if section == "overview":
        return (
            "- Use plan and health dashboards before long outdoor blocks.\n"
            "- Re-check anomalies for rapid weather shifts."
        )
    if section == "health":
        return (
            "- Hydrate earlier in the day when heat/dehydration risk is elevated.\n"
            "- Shift intense outdoor activity to lower-risk hours."
        )
    return "- Conditions generated from ForecastHub scoring rules.\n- Review hourly detail before committing plans."
