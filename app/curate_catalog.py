"""Create a conservative target-company shortlist from the imported source catalog."""
from .db import connect, init_db

RECOGNIZABLE_WORKPLACE_TECH={
 "Cisco","NVIDIA","World Wide Technology","Cadence","ServiceNow","Salesforce","Adobe","Box",
 "CrowdStrike","Experian","Intuit","Workiva","HPE","HP","Atlassian","SailPoint","Five9",
 "Databricks","AppFolio","SentinelOne","Calix","UKG","SAP America","Comcast","Accenture",
 "Deloitte","Slalom","PagerDuty","GitLab","Gong","Motive","PROS","Netskope","Klaviyo",
 "Snowflake","MongoDB","Okta","Cloudflare","HubSpot","Zoom","Dropbox","Twilio","Zscaler",
}

# Deliberately curated instead of selecting unicorns by valuation rank. High
# valuation alone says little about US hiring relevance, operating durability,
# or whether a candidate will recognize the employer.
RECOGNIZABLE_SCALED_STARTUPS={
 "OpenAI","Anthropic","SpaceX","Stripe","Databricks","Canva","Figma","Notion",
 "Airtable","Anduril","Scale AI","Ramp","Rippling","Brex","Plaid","Chime",
 "Discord","Reddit","Perplexity","Gusto","Deel","Flexport","Whatnot","Faire",
 "Vercel","Webflow","Zapier","Grammarly","Miro","Celonis","Fanatics","Epic Games",
 "CloudKitchens","Relativity Space","Sierra","Harvey","Wiz","Rubrik","Nuro",
 "Devoted Health","Ro","Hinge Health","EquipmentShare","ServiceTitan","Carta",
}

def run() -> dict:
    init_db()
    with connect() as db:
        db.execute("UPDATE companies SET shortlisted=0,shortlist_reason='' WHERE ats_type='catalog'")
        db.execute("UPDATE companies SET shortlisted=1,shortlist_reason='Verified supported career feed' WHERE ats_type!='catalog'")
        db.execute("""UPDATE companies SET shortlisted=1,shortlist_reason='Established employer recognized by GMAC or Glassdoor'
                      WHERE id IN (SELECT company_id FROM company_list_memberships WHERE source_key IN ('gmac-tech-2026','glassdoor-tech-ai-2026'))""")
        if RECOGNIZABLE_SCALED_STARTUPS:
            marks=",".join("?" for _ in RECOGNIZABLE_SCALED_STARTUPS)
            db.execute(f"UPDATE companies SET shortlisted=1,shortlist_reason='Recognizable, well-funded scaled startup' WHERE name IN ({marks})",tuple(RECOGNIZABLE_SCALED_STARTUPS))
        if RECOGNIZABLE_WORKPLACE_TECH:
            marks=",".join("?" for _ in RECOGNIZABLE_WORKPLACE_TECH)
            db.execute(f"UPDATE companies SET shortlisted=1,shortlist_reason='Recognizable, scaled workplace-ranked technology employer' WHERE name IN ({marks})",tuple(RECOGNIZABLE_WORKPLACE_TECH))
        counts=dict(db.execute("SELECT COUNT(*) total,SUM(shortlisted) shortlisted,SUM(shortlisted=0) archived_catalog FROM companies").fetchone())
    return counts

if __name__=="__main__": print(run())
