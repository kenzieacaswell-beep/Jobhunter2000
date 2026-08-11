import re
from datetime import datetime, timezone

TARGET_ROLE_PATTERNS = [
    r"\b(?:associate|junior) product manager\b", r"\bproduct manager(?:\s+(?:i|ii|1|2))?\b",
    r"\bproduct (?:operations|ops)(?: associate| analyst| specialist| manager)?\b", r"\bproduct analyst\b",
    r"\btechnical program manager\b", r"\bprogram manager\b", r"\bproject manager\b",
    r"\bproject engineer\b", r"\bprogram analyst\b", r"\bprogram coordinator\b",
    r"\bproject coordinator\b", r"\boperations program manager\b",
    r"\bengineering project manager\b", r"\bmanufacturing program manager\b",
]
ADJACENT_ROLE_PATTERNS = [
    r"\bimplementation (?:manager|consultant|specialist|analyst)\b",
    r"\bdelivery (?:manager|consultant|lead|analyst)\b",
    r"\bbusiness (?:operations|systems) (?:manager|analyst|specialist)\b",
    r"\bstrategy (?:&|and) operations\b", r"\boperations (?:manager|analyst|specialist|coordinator)\b",
    r"\blaunch (?:manager|operations|coordinator)\b", r"\bportfolio (?:manager|analyst)\b",
    r"\bchief of staff\b", r"\bprogram specialist\b",
]
UNRELATED_FUNCTION = re.compile(
    r"\b(marketing|sales|account executive|recruit(?:er|ing)|talent|legal|counsel|finance|financial|"
    r"accounting|compensation|people operations|human resources|real estate|designer|design manager|"
    r"software engineer|data scientist|security engineer|engineering manager|clinical|medical)\b", re.I
)
SENIORITY_BLOCK = re.compile(
    r"\b(senior|sr\.?|staff|principal|director|head|vice president|vp|distinguished|chief|"
    r"group product manager|lead(?:\s+(?:product|program|project|operations))?)\b", re.I
)
EMPLOYMENT_BLOCK = re.compile(r"\b(contract|contractor|temporary|temp|intern|internship)\b", re.I)
MANAGER_II = re.compile(r"\bmanager\s+(?:ii|iii|2|3)\b", re.I)
REQUIRED_YEARS = re.compile(
    r"(?:minimum|required|requirements?|qualifications?|must have|need(?:ed)?|experience)"
    r"[^\n.!?]{0,140}?(\d+)\s*(?:\+|plus)?\s*(?:(?:-|to)\s*(\d+))?\s*years?", re.I
)
PREFERRED_YEARS = re.compile(
    r"(?:preferred|ideally|nice to have)[^\n.!?]{0,140}?(\d+)\s*(?:\+|plus)?\s*"
    r"(?:(?:-|to)\s*(\d+))?\s*years?", re.I
)
GENERIC_EXPERIENCE_YEARS = re.compile(
    r"(\d+)\s*(?:\+|plus)?\s*(?:(?:-|to)\s*(\d+))?\s*years?\s+"
    r"(?:of\s+[^\n.!?]{0,80}?\s+)?experience\b", re.I
)

LOCATION_GROUPS = {
    "San Francisco Bay Area": ("san francisco", "bay area", "oakland", "berkeley", "san mateo", "redwood city", "palo alto", "mountain view", "sunnyvale", "santa clara", "san jose", "menlo park", "south san francisco"),
    "Seattle": ("seattle", "bellevue", "redmond", "kirkland"),
    "Austin, TX": ("austin",),
    "New York City": ("new york", "nyc", "brooklyn", "manhattan"),
}
NON_US_MARKERS = ("canada", "toronto", "vancouver", "montreal", "london", "united kingdom", " uk", "europe", "emea", "india", "singapore", "australia", "germany", "france", "ireland", "poland", "mexico", "brazil", "japan", "amsterdam", "warsaw", "paris", "dublin")
US_MARKERS = ("united states", "u.s.", "usa", "us only", "remote - us", "remote, us", "anywhere in the us")
SKILL_ALIASES = {
    "technical program management": ("technical program", "tpm"),
    "project management": ("project management", "project manager", "project delivery"),
    "cross-functional leadership": ("cross-functional", "cross functional", "stakeholder alignment"),
    "risk management": ("risk management", "risk mitigation"),
    "process improvement": ("process improvement", "continuous improvement", "operational excellence"),
    "supply chain optimization": ("supply chain", "procurement", "sourcing"),
    "bom lifecycle management": ("bom", "bill of materials", "lifecycle management"),
    "ai tool development": ("artificial intelligence", "machine learning", " ai "),
}


def match_tier(score: float, eligible: bool = True, force_stretch: bool = False) -> str:
    if not eligible:
        return "excluded"
    if force_stretch:
        return "stretch"
    if score >= 75:
        return "strong"
    if score >= 60:
        return "good"
    if score >= 40:
        return "stretch"
    return "low"


def classify_role(title: str) -> dict:
    value = (title or "").strip()
    if EMPLOYMENT_BLOCK.search(value):
        return {"family": "excluded", "eligible": False, "code": "employment_type", "reason": "Contract, temporary, and internship roles are excluded"}
    if SENIORITY_BLOCK.search(value):
        return {"family": "excluded", "eligible": False, "code": "seniority", "reason": "Seniority is above the candidate's target level"}
    if UNRELATED_FUNCTION.search(value):
        return {"family": "excluded", "eligible": False, "code": "unrelated_function", "reason": "Core function is outside the candidate's target role families"}
    if any(re.search(pattern, value, re.I) for pattern in TARGET_ROLE_PATTERNS):
        return {"family": "target", "eligible": True, "code": "target_role", "reason": "Target product, program, or project role"}
    if any(re.search(pattern, value, re.I) for pattern in ADJACENT_ROLE_PATTERNS):
        return {"family": "adjacent", "eligible": True, "code": "adjacent_role", "reason": "Adjacent execution or operations role"}
    return {"family": "unrelated", "eligible": False, "code": "unrelated_function", "reason": "Core function is outside the candidate's target role families"}


def _years(pattern: re.Pattern, description: str) -> list[tuple[int, int]]:
    values = []
    for match in pattern.finditer(description or ""):
        low, high = int(match.group(1)), int(match.group(2) or match.group(1))
        if low <= 20 and high <= 20:
            values.append((low, high))
    return values


def required_experience(description: str) -> list[tuple[int, int]]:
    preferred_spans = [match.span() for match in PREFERRED_YEARS.finditer(description or "")]
    values = []
    for match in list(REQUIRED_YEARS.finditer(description or "")) + list(GENERIC_EXPERIENCE_YEARS.finditer(description or "")):
        if any(start <= match.start() < end for start, end in preferred_spans):
            continue
        low, high = int(match.group(1)), int(match.group(2) or match.group(1))
        if low <= 20 and high <= 20:
            values.append((low, high))
    return list(dict.fromkeys(values))


def location_assessment(job: dict, settings: dict) -> dict:
    raw = (job.get("location") or "").strip()
    value = raw.lower()
    description = (job.get("description") or "")[:1800].lower()
    remote = bool(re.search(r"\b(remote|distributed|work from home)\b", value))
    hybrid = "hybrid" in value or bool(re.search(r"\bhybrid\b", description))
    onsite = bool(re.search(r"\b(on[- ]?site|in[- ]?office)\b", value))
    arrangement = "remote" if remote else ("hybrid" if hybrid else ("onsite" if onsite else "unknown"))
    matched = []
    for target in settings.get("target_locations", []):
        if "remote" in target.lower():
            continue
        aliases = LOCATION_GROUPS.get(target, (target.lower().split(",")[0],))
        if any(alias in value for alias in aliases):
            matched.append(target)
    has_us = any(marker in value for marker in US_MARKERS) or bool(matched)
    non_us = any(marker in value for marker in NON_US_MARKERS)
    if matched:
        score = 20
        concerns = []
        if arrangement == "hybrid" and not settings.get("allow_hybrid", True):
            score, concerns = 8, ["Hybrid work is outside current preferences"]
        elif arrangement == "onsite" and not settings.get("allow_onsite", True):
            score, concerns = 8, ["Onsite work is outside current preferences"]
        return {"eligible": True, "score": score, "arrangement": arrangement, "match": matched[0], "reason": f"Matches {matched[0]}", "code": "target_location", "concerns": concerns}
    if remote and settings.get("allow_us_remote", True) and (has_us or not non_us):
        return {"eligible": True, "score": 20, "arrangement": "remote", "match": "US Remote", "reason": "Eligible US-remote role", "code": "us_remote", "concerns": []}
    if non_us and not has_us:
        return {"eligible": False, "score": 0, "arrangement": arrangement, "match": "International", "reason": f"International-only location: {raw}", "code": "international_only", "concerns": []}
    if not raw or value in {"unknown", "multiple locations", "hybrid", "north america"}:
        return {"eligible": True, "score": 6, "arrangement": arrangement, "match": "Unknown", "reason": "Location is not disclosed", "code": "unknown_location", "concerns": ["Location needs confirmation"]}
    return {"eligible": True, "score": 8, "arrangement": arrangement, "match": "Outside targets", "reason": f"Domestic location is outside targets: {raw}", "code": "outside_target_location", "concerns": [f"Outside preferred locations: {raw}"]}


def eligibility_assessment(job: dict, settings: dict) -> tuple[bool, str, dict]:
    role = classify_role(job.get("title") or "")
    if not role["eligible"]:
        return False, role["reason"], {"role": role, "required_years": [], "preferred_years": []}
    required = required_experience(job.get("description") or "")
    preferred = _years(PREFERRED_YEARS, job.get("description") or "")
    minimum = max((low for low, _ in required), default=0)
    hard_max = int(settings.get("maximum_required_experience", 5))
    if minimum > hard_max:
        return False, f"Requires at least {minimum} years; maximum considered is {hard_max}", {"role": role, "required_years": required, "preferred_years": preferred}
    location = location_assessment(job, settings)
    if not location["eligible"]:
        return False, location["reason"], {"role": role, "required_years": required, "preferred_years": preferred, "location": location}
    return True, "Ranked for candidate fit", {"role": role, "required_years": required, "preferred_years": preferred, "location": location}


def _skill_matches(profile: dict, text: str) -> list[str]:
    matches = []
    for skill in profile.get("skills", []):
        label = str(skill)
        normalized = label.lower()
        aliases = SKILL_ALIASES.get(normalized, (normalized,))
        if any(alias in text for alias in aliases):
            matches.append(label)
    return matches


def rule_score(job: dict, settings: dict, profile: dict | None = None) -> tuple[float, dict]:
    title = (job.get("title") or "").lower()
    text = f" {title} {job.get('description', '')} ".lower()
    eligible, reason, details = eligibility_assessment(job, settings)
    weights = settings.get("scoring_weights", {"role": 30, "experience": 25, "location": 20, "skills": 15, "freshness": 10})
    role = details.get("role") or classify_role(title)
    role_quality = {"target": 1.0, "adjacent": 0.68}.get(role["family"], 0.0)
    requirements = details.get("required_years", [])
    minimum = max((low for low, _ in requirements), default=0)
    manager_ambiguity = "manager" in title and not requirements and not re.search(r"\b(associate|junior|entry(?:-level)?|early career|new grad|university|rotational|manager\s+(?:i|1))\b", title)
    experience_quality = 0.72 if not requirements else {0: 1.0, 1: 1.0, 2: 1.0, 3: 0.86, 4: 0.60, 5: 0.35}.get(minimum, 0.0)
    if manager_ambiguity:
        experience_quality = min(experience_quality, 0.60)
    location = details.get("location") or location_assessment(job, settings)
    skill_hits = _skill_matches(profile or {}, text)
    adjacency_hits = [term for term in ("technical program", "engineering project", "manufacturing", "operations program", "product operations", "project manager", "cross-functional", "supply chain", "plm", "sap", "jira", "sql") if term in text]
    skills_quality = min(1.0, (len(skill_hits) + len(adjacency_hits) * 0.75) / 6)
    age = None
    posted = job.get("posted_at")
    if posted:
        try:
            age = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(posted.replace("Z", "+00:00"))).days)
        except (ValueError, TypeError):
            pass
    max_age = max(1, int(settings.get("max_job_age_days", 45)))
    freshness_quality = 0.55 if age is None else max(0, 1 - age / max_age)
    parts = {
        "role": round(float(weights.get("role", 30)) * role_quality, 1),
        "experience": round(float(weights.get("experience", 25)) * experience_quality, 1),
        "location": round(float(weights.get("location", 20)) * (location["score"] / 20), 1),
        "skills": round(float(weights.get("skills", 15)) * skills_quality, 1),
        "freshness": round(float(weights.get("freshness", 10)) * freshness_quality, 1),
        "salary": 0.0,
    }
    concerns = list(location.get("concerns", []))
    penalty_codes = []
    if minimum in (4, 5):
        concerns.append(f"Stretch requirement: at least {minimum} years of experience")
        penalty_codes.append("stretch_experience")
    elif manager_ambiguity:
        concerns.append("Manager title does not disclose an experience level")
        penalty_codes.append("manager_level_unknown")
    if MANAGER_II.search(title):
        concerns.append("Manager II/III level may be a stretch")
        penalty_codes.append("manager_level_stretch")
    floor = float(settings.get("salary_floor", 0))
    salary_max = job.get("salary_max")
    salary_penalty = 0.0
    if floor and salary_max is not None and float(salary_max) < floor:
        salary_penalty = 10.0
        concerns.append(f"Disclosed maximum salary is below ${floor:,.0f}")
        penalty_codes.append("salary_below_floor")
    level_penalty = 6.0 if MANAGER_II.search(title) else 0.0
    raw_score = sum(parts.values()) - salary_penalty - level_penalty
    score = round(max(0, min(100, raw_score)), 1) if eligible else 0.0
    result = {
        "components": parts, "role_family": role["family"], "role_reason": role["reason"],
        "role_hits": [x for x in settings.get("role_keywords", []) if x.lower() in title],
        "skill_hits": skill_hits, "adjacency_hits": adjacency_hits, "eligible": eligible,
        "eligibility_reason": reason, "required_years": requirements,
        "preferred_years": details.get("preferred_years", []), "location": location,
        "job_age_days": age, "concerns": concerns, "penalty_codes": penalty_codes,
        "match_tier": match_tier(score, eligible, minimum in (4, 5)),
    }
    return score, result


def combine(rule: float, ai: float | None) -> float:
    return round(rule if ai is None else rule * 0.45 + ai * 0.55, 1)
