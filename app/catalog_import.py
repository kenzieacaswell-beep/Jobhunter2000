"""Import public employer rankings as a deduplicated, disabled company catalog."""
import asyncio, hashlib, html, json, re
from dataclasses import dataclass
from typing import Callable
import httpx

from .db import connect, init_db, now

@dataclass
class Source:
    key: str
    name: str
    url: str
    parser: Callable[[str], list[tuple[str, int | None]]]

def clean(value: str) -> str:
    value=html.unescape(re.sub(r"<[^>]+>","",value)).strip()
    value=re.sub(r"^\d+\.\s*","",value)
    value=re.sub(r":\s+AI leadership.*$","",value,flags=re.I)
    aliases={"Adobe Systems Incorporated":"Adobe","Intuit Inc.":"Intuit","Atlassian, Inc.":"Atlassian","Box, Inc.":"Box","HP Inc.":"HP","Nvidia":"NVIDIA"}
    return aliases.get(value,value).strip()

def identity(value: str) -> str:
    value=clean(value).lower().replace("&","and")
    value=re.sub(r"\b(incorporated|inc|llc|ltd|corporation|corp|company|technologies)\b\.?","",value)
    return re.sub(r"[^a-z0-9]+","",value)

def parse_gmac(text: str) -> list[tuple[str,int|None]]:
    return [(clean(name),int(rank)) for rank,name in re.findall(r"<h3[^>]*>\s*(\d+)\.\s*(.*?)</h3>",text,re.S|re.I)]

def parse_gptw(text: str) -> list[tuple[str,int|None]]:
    companies=[]
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>',text,re.S|re.I):
        try: objects=json.loads(raw)
        except json.JSONDecodeError: continue
        for listing in objects if isinstance(objects,list) else [objects]:
            if listing.get("@type")!="ItemList": continue
            for entry in listing.get("itemListElement",[]):
                item=entry.get("item",{}); name=clean(item.get("name",""))
                if name: companies.append((name,entry.get("position")))
    return companies

def parse_crunchbase(text: str) -> list[tuple[str,int|None]]:
    match=re.search(r'<table class="unicorn-table.*?<tbody>(.*?)</tbody>',text,re.S|re.I)
    if not match: return []
    names=re.findall(r'<a href="https://www\.crunchbase\.com/organization/[^"]+"[^>]*>(.*?)</a>',match.group(1),re.S|re.I)
    return [(clean(name),rank) for rank,name in enumerate(names,1) if clean(name)]

def parse_cbinsights(text: str) -> list[tuple[str,int|None]]:
    names=re.findall(r'<td>\s*<a href="https://www\.cbinsights\.com/company/[^"]+">(.*?)</a>\s*</td>',text,re.S|re.I)
    return [(clean(name),rank) for rank,name in enumerate(names,1) if clean(name)]

SOURCES=[
 Source("gmac-tech-2026","GMAC Best Tech Companies 2026","https://www.gmac.com/resources/learners/business-careers/employers-salaries/best-tech-companies-work",parse_gmac),
 Source("gptw-tech-2025","Great Place to Work Technology 2025","https://www.greatplacetowork.com/best-workplaces/technology/2025",parse_gptw),
 Source("crunchbase-unicorns","Crunchbase Unicorn Board","https://news.crunchbase.com/unicorn-company-list/",parse_crunchbase),
 Source("glassdoor-tech-ai-2026","Glassdoor Best Tech & AI 2026","https://www.glassdoor.com/Award/Best-Places-to-Work-Tech-and-AI-LST_KQ0,31.htm",parse_gmac),
 Source("cbinsights-unicorns","CB Insights Unicorn Companies","https://www.cbinsights.com/research-unicorn-companies",parse_cbinsights),
]

async def download(source: Source) -> str:
    headers={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36","Accept":"text/html,application/xhtml+xml"}
    async with httpx.AsyncClient(timeout=60,follow_redirects=True,headers=headers) as client:
        response=await client.get(source.url); response.raise_for_status(); return response.text

def import_entries(source:Source, entries:list[tuple[str,int|None]]) -> tuple[int,int]:
    added=linked=0
    with connect() as db:
        existing=[dict(r) for r in db.execute("SELECT id,name FROM companies")]
        by_identity={identity(r["name"]):r for r in existing}
        for name,rank in entries:
            key=identity(name)
            if not key: continue
            company=by_identity.get(key)
            if not company:
                token="catalog-"+hashlib.sha1(key.encode()).hexdigest()[:16]
                cid=db.execute("INSERT INTO companies(name,ats_type,token,sector,enabled,created_at) VALUES(?,?,?,?,0,?)",(name,"catalog",token,"Technology",now())).lastrowid
                company={"id":cid,"name":name};by_identity[key]=company;added+=1
            before=db.total_changes
            db.execute("INSERT OR IGNORE INTO company_list_memberships(company_id,source_key,source_name,source_url,rank,imported_at) VALUES(?,?,?,?,?,?)",(company["id"],source.key,source.name,source.url,rank,now()))
            linked+=int(db.total_changes>before)
    return added,linked

async def run() -> dict:
    init_db(); result={"sources":{},"companies_added":0,"memberships_added":0}
    gmac_text=""
    for source in SOURCES:
        try:
            if source.key=="glassdoor-tech-ai-2026" and gmac_text:
                text=gmac_text
            else: text=await download(source)
            if source.key=="gmac-tech-2026": gmac_text=text
            entries=source.parser(text); added,linked=import_entries(source,entries)
            result["sources"][source.key]={"found":len(entries),"added":added,"linked":linked}
            result["companies_added"]+=added;result["memberships_added"]+=linked
        except Exception as exc: result["sources"][source.key]={"error":str(exc)[:300]}
    return result

if __name__=="__main__": print(json.dumps(asyncio.run(run()),indent=2))
