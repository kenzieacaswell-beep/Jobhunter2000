import re
from pathlib import Path
from pypdf import PdfReader

EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}")
URL = re.compile(r"https?://\S+|(?:www\.)\S+|linkedin\.com/\S+", re.I)
ADDRESS = re.compile(r"\b\d{1,6}\s+[A-Za-z0-9.' -]+\s(?:Street|St|Road|Rd|Avenue|Ave|Boulevard|Blvd|Lane|Ln|Drive|Dr)\b[^\n]*", re.I)

def extract_pdf(path: Path) -> str:
    return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages).strip()

def redact(text: str) -> str:
    text = re.sub(r"^\s*[A-Z][A-Z' -]{3,60}(?=https?://|\s+[A-Z0-9._%+-]+@)", "[NAME REDACTED] ", text)
    lines = text.splitlines()
    if lines and len(lines[0].split()) <= 5:
        lines[0] = "[NAME REDACTED]"
    text = "\n".join(lines)
    for pattern, label in [(EMAIL,"[EMAIL REDACTED]"),(PHONE,"[PHONE REDACTED]"),(URL,"[URL REDACTED]"),(ADDRESS,"[ADDRESS REDACTED]")]:
        text = pattern.sub(label, text)
    return text

def suggest_profile(text: str) -> dict:
    known = ["SQL","Python","Jira","Figma","Agile","Scrum","analytics","roadmap","user research","A/B testing","Tableau","Excel"]
    return {"summary": "Review and edit this locally extracted profile before approval.", "experience_years": 1.5,
            "skills": [s for s in known if s.lower() in text.lower()], "education": [], "roles": []}
