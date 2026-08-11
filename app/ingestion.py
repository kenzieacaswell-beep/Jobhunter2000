import hashlib, json

from .connectors import CONNECTORS
from .db import connect, get_settings, now, row, rows
from .scoring import combine, match_tier, rule_score
from .deepseek import evaluate_job


def content_hash(job: dict) -> str:
    return hashlib.sha256(json.dumps({k:job.get(k) for k in ("title","location","description","salary_min","salary_max")},sort_keys=True).encode()).hexdigest()


def _profile() -> dict:
    record=row("SELECT redacted_text,profile_json,approved FROM profile WHERE id=1") or {}
    record["parsed"]=json.loads(record.get("profile_json") or "{}")
    return record


async def _ingest_company(company:dict,settings:dict,profile:dict) -> dict:
    connector=CONNECTORS.get(company["ats_type"])
    if not connector: raise ValueError(f"Unsupported job board: {company['ats_type']}")
    postings=await connector.fetch(company["token"]); seen=[]; stats={"seen":0,"new":0,"updated":0}
    for item in postings:
        stats["seen"]+=1; seen.append(str(item["external_id"])); ch=content_hash(item)
        existing=row("SELECT * FROM jobs WHERE source_type=? AND external_id=? AND company_name=?",(company["ats_type"],str(item["external_id"]),company["name"]))
        item.update({"company_name":company["name"],"content_hash":ch})
        score,explain=rule_score(item,settings,profile); eligible=int(explain["eligible"]); reason=explain["eligibility_reason"]
        arrangement=explain.get("location",{}).get("arrangement","unknown")
        force_stretch="stretch_experience" in explain.get("penalty_codes",[])
        with connect() as db:
            if existing:
                changed=existing["content_hash"]!=ch; combined=combine(score,existing["ai_score"]) if eligible else 0.0
                status="not_applicable" if not eligible else ("pending" if changed else existing["ai_status"])
                db.execute("UPDATE jobs SET title=?,location=?,work_arrangement=?,description=?,source_url=?,canonical_url=?,raw_json=?,posted_at=?,last_seen_at=?,content_hash=?,active=1,rule_score=?,combined_score=?,eligible=?,eligibility_reason=?,match_tier=?,rule_result=?,ai_status=?,updated_at=? WHERE id=?",
                           (item["title"],item["location"],arrangement,item["description"],item["source_url"],item["source_url"],json.dumps(item["raw"]),item.get("posted_at"),now(),ch,score,combined,eligible,reason,match_tier(combined,bool(eligible),force_stretch),json.dumps(explain),status,now(),existing["id"])); stats["updated"]+=int(changed)
            else:
                db.execute("INSERT INTO jobs(company_id,company_name,external_id,source_type,source_url,canonical_url,title,location,work_arrangement,description,raw_json,posted_at,first_seen_at,last_seen_at,content_hash,rule_score,combined_score,eligible,eligibility_reason,match_tier,rule_result,ai_status,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (company["id"],company["name"],str(item["external_id"]),company["ats_type"],item["source_url"],item["source_url"],item["title"],item["location"],arrangement,item["description"],json.dumps(item["raw"]),item.get("posted_at"),now(),now(),ch,score,score,eligible,reason,match_tier(score,bool(eligible),force_stretch),json.dumps(explain),"pending" if eligible else "not_applicable",now())); stats["new"]+=1
    with connect() as db:
        db.execute("UPDATE companies SET last_success_at=?,last_error='' WHERE id=?",(now(),company["id"]))
        if seen:
            marks=",".join("?"*len(seen)); db.execute(f"UPDATE jobs SET active=0 WHERE company_id=? AND external_id NOT IN ({marks})",(company["id"],*seen))
    return stats


async def _enrich(profile:dict,company_id:int|None=None) -> None:
    if not profile.get("approved"): return
    clause=" AND company_id=?" if company_id is not None else ""; params=(company_id,) if company_id is not None else ()
    for job in rows("SELECT * FROM jobs WHERE active=1 AND eligible=1 AND ai_status IN ('pending','retry')"+clause+" ORDER BY rule_score DESC LIMIT 100",params):
        await evaluate_job(job,profile.get("redacted_text",""),profile["parsed"])


async def refresh_company(company_id:int,enrich:bool=True) -> dict:
    company=row("SELECT * FROM companies WHERE id=?",(company_id,))
    if not company: raise ValueError("Company not found")
    profile=_profile()
    try:
        stats=await _ingest_company(company,get_settings(),profile["parsed"])
        if enrich: await _enrich(profile,company_id)
        return {**stats,"company_id":company_id,"errors":[]}
    except Exception as exc:
        with connect() as db: db.execute("UPDATE companies SET last_error=? WHERE id=?",(str(exc)[:1000],company_id))
        raise


async def refresh_all(enrich:bool=True) -> dict:
    started=now()
    with connect() as db: run_id=db.execute("INSERT INTO ingestion_runs(started_at) VALUES(?)",(started,)).lastrowid
    stats={"seen":0,"new":0,"updated":0,"errors":[]}; settings=get_settings(); profile=_profile()
    for company in rows("SELECT * FROM companies WHERE enabled=1 AND ats_type!='catalog'"):
        try:
            result=await _ingest_company(company,settings,profile["parsed"])
            for key in ("seen","new","updated"): stats[key]+=result[key]
        except Exception as exc:
            stats["errors"].append(f"{company['name']}: {exc}")
            with connect() as db: db.execute("UPDATE companies SET last_error=? WHERE id=?",(str(exc)[:1000],company["id"]))
    if enrich: await _enrich(profile)
    status="partial" if stats["errors"] else "success"
    with connect() as db: db.execute("UPDATE ingestion_runs SET finished_at=?,status=?,jobs_seen=?,jobs_new=?,jobs_updated=?,error=? WHERE id=?",(now(),status,stats["seen"],stats["new"],stats["updated"],"\n".join(stats["errors"]),run_id))
    return stats
