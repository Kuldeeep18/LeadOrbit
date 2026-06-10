FREE_EMAIL_DOMAINS = {
    "aol.com",
    "gmail.com",
    "hotmail.com",
    "icloud.com",
    "live.com",
    "outlook.com",
    "proton.me",
    "protonmail.com",
    "yahoo.com",
}

HIGH_INTENT_TITLE_KEYWORDS = {
    "ceo",
    "chief",
    "co-founder",
    "cofounder",
    "director",
    "founder",
    "head",
    "lead",
    "manager",
    "owner",
    "vp",
}


def _clean(value):
    return str(value or "").strip()


def _email_domain(email):
    email = _clean(email).lower()
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[1]


def _has_high_intent_title(custom_data):
    if not isinstance(custom_data, dict):
        return False

    title = _clean(
        custom_data.get("title")
        or custom_data.get("job_title")
        or custom_data.get("role")
        or custom_data.get("position")
    ).lower()
    return any(keyword in title for keyword in HIGH_INTENT_TITLE_KEYWORDS)


def calculate_lead_score(lead):
    """Return a 0-100 fit score from lead completeness and buyer-fit signals."""
    score = 0
    email_domain = _email_domain(getattr(lead, "email", ""))

    if email_domain:
        score += 20
        if email_domain not in FREE_EMAIL_DOMAINS:
            score += 15

    if _clean(getattr(lead, "first_name", "")):
        score += 8
    if _clean(getattr(lead, "last_name", "")):
        score += 7
    if _clean(getattr(lead, "company", "")):
        score += 20
    if _clean(getattr(lead, "linkedin_url", "")):
        score += 15
    if _clean(getattr(lead, "phone", "")):
        score += 10

    custom_data = getattr(lead, "custom_data", {}) or {}
    if _has_high_intent_title(custom_data):
        score += 5

    return min(score, 100)
