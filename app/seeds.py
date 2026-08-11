from .db import connect, now

# Curated starting catalog. Sources are editable and disabled until the user reviews them;
# ATS board tokens can change, and a failed source never creates jobs.
SEED_COMPANIES = [
 ("Airtable","greenhouse","airtable"),("Anthropic","greenhouse","anthropic"),("Asana","greenhouse","asana"),
 ("Brex","greenhouse","brex"),("Chime","greenhouse","chime"),("Cloudflare","greenhouse","cloudflare"),
 ("Coinbase","greenhouse","coinbase"),("Datadog","greenhouse","datadog"),("Discord","greenhouse","discord"),
 ("Duolingo","greenhouse","duolingo"),("Figma","greenhouse","figma"),("Flexport","greenhouse","flexport"),
 ("Gusto","greenhouse","gusto"),("Instacart","greenhouse","instacart"),("Lyft","greenhouse","lyft"),
 ("Notion","ashby","notion"),("Plaid","ashby","plaid"),("Reddit","greenhouse","reddit"),
 ("Robinhood","greenhouse","robinhood"),("Scale AI","greenhouse","scaleai"),("Sentry","ashby","sentry"),
 ("Webflow","greenhouse","webflow"),("Zapier","ashby","zapier"),("Linear","ashby","linear"),
 ("Ramp","ashby","ramp"),("Vercel","greenhouse","vercel"),("Highspot","lever","highspot"),
]

def seed_companies() -> int:
    with connect() as db:
        for name,ats,token in SEED_COMPANIES:
            db.execute("INSERT OR IGNORE INTO companies(name,ats_type,token,enabled,created_at) VALUES(?,?,?,?,?)",(name,ats,token,0,now()))
    return len(SEED_COMPANIES)
