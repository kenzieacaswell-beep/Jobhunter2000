from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "job_tracker.sqlite3"
UPLOAD_DIR = DATA_DIR / "uploads"
FRONTEND_DIST = ROOT / "frontend" / "dist"
KEYCHAIN_SERVICE = "com.local.job-tracker"
DEEPSEEK_KEY_ACCOUNT = "deepseek-api-key"
GMAIL_TOKEN_ACCOUNT = "gmail-oauth-token"
PROMPT_VERSION = "2026-08-10-v2"

DEFAULT_SETTINGS = {
    "target_locations": ["San Francisco Bay Area", "Seattle", "Austin, TX", "US Remote"],
    "allow_us_remote": True,
    "allow_hybrid": True,
    "allow_onsite": True,
    "allow_unknown_location": False,
    "target_sectors": ["Technology"],
    "role_keywords": ["associate product manager", "junior product manager", "product manager i", "product analyst", "product operations", "technical program manager", "program manager", "project manager", "engineering project manager", "operations program manager"],
    "excluded_keywords": ["senior", "sr.", "staff", "principal", "director", "head of", "vice president", "vp", "distinguished", "group product manager"],
    "maximum_required_experience": 5,
    "max_job_age_days": 45,
    "minimum_match_score": 60,
    "scoring_weights": {"role": 30, "experience": 25, "location": 20, "skills": 15, "freshness": 10},
    "salary_floor": 90000,
    "monthly_ai_budget": 5.0,
    "deepseek_model": "deepseek-v4-flash",
    "daily_run_hour": 8,
    "digest_limit": 10,
    "digest_recipient": "",
}
