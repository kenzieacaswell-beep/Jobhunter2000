import csv, io, json, shutil
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl

from .config import DB_PATH, DEEPSEEK_KEY_ACCOUNT, UPLOAD_DIR
from .db import connect, get_settings, now, row, rows, set_settings
from .deepseek import month_spend
from .ingestion import content_hash, refresh_all, refresh_company
from .keychain import get_secret, set_secret
from .resume import extract_pdf, redact, suggest_profile
from .scoring import combine, match_tier, rule_score
from .gmail import connected as gmail_connected

router=APIRouter(prefix="/api")

class CompanyIn(BaseModel):
    name:str; ats_type:Literal["greenhouse","lever","ashby","recruitee"]; token:str; careers_url:str=""; sector:str="Technology"; enabled:bool=True
class CompanySourceIn(BaseModel): ats_type:Literal["greenhouse","lever","ashby","recruitee"]; token:str
class ReviewIn(BaseModel): status:Literal["inbox","saved","dismissed","preparing"]; reason:str=""
class ApplicationIn(BaseModel): stage:str="Preparing"; notes:str=""; next_follow_up:str|None=None
class ManualJob(BaseModel): company_name:str; title:str; source_url:HttpUrl; location:str=""; description:str=""; salary_min:float|None=None; salary_max:float|None=None
class ProfileIn(BaseModel): redacted_text:str; profile:dict; approved:bool
class SecretIn(BaseModel): value:str
class NoteIn(BaseModel): title:str=""; notes:str=""; due_at:str|None=None; name:str=""; email:str=""; role:str=""
class CompanyToggleIn(BaseModel): enabled:bool
class BulkCompaniesIn(BaseModel): company_ids:list[int]; enabled:bool
class TaskUpdateIn(BaseModel): title:str|None=None; due_at:str|None=None; completed:bool|None=None
class ContactUpdateIn(BaseModel): name:str|None=None; email:str|None=None; role:str|None=None; notes:str|None=None

SEARCH_SETTING_KEYS={"target_locations","allow_us_remote","allow_hybrid","allow_onsite","allow_unknown_location","role_keywords","excluded_keywords","maximum_required_experience","max_job_age_days","minimum_match_score","salary_floor","scoring_weights","monthly_ai_budget","deepseek_model","daily_run_hour","digest_limit","digest_recipient","target_sectors"}

def rescore_active_jobs() -> int:
    current=get_settings(); p=row("SELECT profile_json FROM profile WHERE id=1") or {}; profile=json.loads(p.get("profile_json") or "{}")
    jobs=rows("SELECT * FROM jobs WHERE active=1")
    with connect() as db:
        for item in jobs:
            score,explain=rule_score(item,current,profile)
            eligible=bool(explain["eligible"]); combined=combine(score,item.get("ai_score")) if eligible else 0.0
            status="not_applicable" if not eligible else ("pending" if not item.get("eligible") else item.get("ai_status","pending"))
            db.execute("UPDATE jobs SET rule_score=?,combined_score=?,eligible=?,eligibility_reason=?,work_arrangement=?,match_tier=?,rule_result=?,ai_status=?,updated_at=? WHERE id=?",
                       (score,combined,int(eligible),explain["eligibility_reason"],explain.get("location",{}).get("arrangement","unknown"),match_tier(combined,eligible,"stretch_experience" in explain.get("penalty_codes",[])),json.dumps(explain),status,now(),item["id"]))
    return len(jobs)

@router.get("/settings")
def settings_get(): return get_settings()
@router.put("/settings")
def settings_put(values:dict):
    unknown=set(values)-SEARCH_SETTING_KEYS
    if unknown: raise HTTPException(400,f"Unknown settings: {', '.join(sorted(unknown))}")
    if "target_locations" in values and not isinstance(values["target_locations"],list): raise HTTPException(422,"target_locations must be a list")
    for key,low,high in (("maximum_required_experience",0,5),("max_job_age_days",1,365),("minimum_match_score",0,100),("salary_floor",0,1_000_000)):
        if key in values and (not isinstance(values[key],(int,float)) or not low<=values[key]<=high): raise HTTPException(422,f"{key} must be between {low} and {high}")
    if "scoring_weights" in values:
        weights=values["scoring_weights"]
        if not isinstance(weights,dict) or abs(sum(float(x) for x in weights.values())-100)>0.01: raise HTTPException(422,"Scoring weights must total 100")
    saved=set_settings(values)
    matching_keys={"target_locations","allow_us_remote","allow_hybrid","allow_onsite","allow_unknown_location","role_keywords","excluded_keywords","maximum_required_experience","max_job_age_days","minimum_match_score","salary_floor","scoring_weights","deepseek_model"}
    if matching_keys.intersection(values):
        rescore_active_jobs()
        with connect() as db: db.execute("UPDATE jobs SET ai_status='pending' WHERE active=1 AND eligible=1")
    return saved

def hydrate_job(item:dict) -> dict:
    item["ai_result"]=json.loads(item.get("ai_result") or "{}")
    item["rule_result"]=json.loads(item.get("rule_result") or "{}")
    return item

def hydrate_jobs(items:list[dict]) -> list[dict]: return [hydrate_job(item) for item in items]

def board_token(ats_type:str,value:str) -> str:
    raw=value.strip().lower().rstrip("/")
    if "://" not in raw and ("/" in raw or raw.endswith(".recruitee.com")): raw="https://"+raw
    if "://" not in raw: return raw
    parsed=urlparse(raw); host=parsed.netloc.split(":")[0]; parts=[part for part in parsed.path.split("/") if part]
    if ats_type in {"greenhouse","lever","ashby"}: return parts[0] if parts else ""
    if ats_type=="recruitee" and host.endswith(".recruitee.com"): return host.split(".")[0]
    return ""

@router.get("/companies")
def companies(include_all:bool=False): return rows("SELECT c.*,(SELECT group_concat(m.source_name, ' · ') FROM company_list_memberships m WHERE m.company_id=c.id) list_sources,(SELECT COUNT(*) FROM jobs j WHERE j.company_id=c.id AND j.active=1) active_jobs,(SELECT COUNT(*) FROM jobs j WHERE j.company_id=c.id AND j.active=1 AND j.eligible=1) matching_jobs FROM companies c WHERE (? OR c.shortlisted=1) ORDER BY c.name",(int(include_all),))
@router.post("/companies")
def company_add(item:CompanyIn):
    with connect() as db:
        cid=db.execute("INSERT INTO companies(name,ats_type,token,careers_url,sector,enabled,created_at) VALUES(?,?,?,?,?,?,?)",(item.name,item.ats_type,item.token,item.careers_url,item.sector,item.enabled,now())).lastrowid
    return row("SELECT * FROM companies WHERE id=?",(cid,))
@router.put("/companies/{company_id}")
def company_update(company_id:int,item:CompanyIn):
    with connect() as db: db.execute("UPDATE companies SET name=?,ats_type=?,token=?,careers_url=?,sector=?,enabled=? WHERE id=?",(item.name,item.ats_type,item.token,item.careers_url,item.sector,item.enabled,company_id))
    return row("SELECT * FROM companies WHERE id=?",(company_id,))
@router.delete("/companies/{company_id}")
def company_delete(company_id:int):
    with connect() as db: db.execute("UPDATE companies SET enabled=0 WHERE id=?",(company_id,))
    return {"ok":True}
@router.patch("/companies/{company_id}/enabled")
def company_enabled(company_id:int,item:CompanyToggleIn):
    with connect() as db: db.execute("UPDATE companies SET enabled=? WHERE id=?",(int(item.enabled),company_id))
    return row("SELECT * FROM companies WHERE id=?",(company_id,))
@router.put("/companies/{company_id}/source")
async def company_source(company_id:int,item:CompanySourceIn):
    token=board_token(item.ats_type,item.token)
    if not token or not all(char.isalnum() or char in "-_" for char in token): raise HTTPException(422,"Enter the board token or subdomain, not the full URL")
    if not row("SELECT id FROM companies WHERE id=?",(company_id,)): raise HTTPException(404,"Company not found")
    with connect() as db: db.execute("UPDATE companies SET ats_type=?,token=?,enabled=1,last_error='' WHERE id=?",(item.ats_type,token,company_id))
    try: result=await refresh_company(company_id,enrich=False)
    except Exception as exc: raise HTTPException(502,f"Could not pull that job board: {str(exc)[:240]}")
    return {"company":row("SELECT * FROM companies WHERE id=?",(company_id,)),"refresh":result}
@router.post("/companies/{company_id}/refresh")
async def company_refresh(company_id:int):
    try: return await refresh_company(company_id)
    except ValueError as exc: raise HTTPException(404,str(exc))
    except Exception as exc: raise HTTPException(502,f"Job board refresh failed: {str(exc)[:240]}")
@router.patch("/companies/bulk-enabled")
def company_bulk_enabled(item:BulkCompaniesIn):
    if not item.company_ids: return {"updated":0}
    marks=",".join("?" for _ in item.company_ids)
    with connect() as db: db.execute(f"UPDATE companies SET enabled=? WHERE id IN ({marks})",(int(item.enabled),*item.company_ids))
    return {"updated":len(item.company_ids)}

@router.get("/jobs")
def jobs(q:str="",review_status:str="",active:bool=True,min_score:float=0,location:str=""):
    where=["j.active=?","j.eligible=1","j.combined_score>=?"]; params=[int(active),min_score]
    if q: where.append("(j.title LIKE ? OR j.company_name LIKE ? OR j.description LIKE ?)"); params += [f"%{q}%"]*3
    if review_status: where.append("j.review_status=?"); params.append(review_status)
    if location: where.append("j.location LIKE ?"); params.append(f"%{location}%")
    return hydrate_jobs(rows("SELECT j.*,a.stage application_stage FROM jobs j LEFT JOIN applications a ON a.job_id=j.id WHERE "+" AND ".join(where)+" ORDER BY j.combined_score DESC,j.first_seen_at DESC LIMIT 1000",params))
@router.get("/jobs/views/{view}")
def jobs_view(view:str,q:str="",location:str="",arrangement:str="",min_score:float|None=None,max_age:int|None=None,salary_disclosed:bool=False,sort:str="score"):
    settings=get_settings(); threshold=float(settings.get("minimum_match_score",60)); effective_age=int(settings.get("max_job_age_days",45))
    if min_score is not None: threshold=max(0,min(100,min_score))
    if max_age is not None: effective_age=max(1,min(365,max_age))
    quality="j.eligible=1 AND j.combined_score>=? AND (j.posted_at IS NULL OR j.posted_at>=datetime('now',?))"
    age_modifier=f"-{effective_age} day"
    clauses=["j.active=1"]; params=[]
    views={
        "all-matches":"j.eligible=1 AND j.review_status!='dismissed'",
        "best-matches":quality+" AND j.review_status='inbox'",
        "new-today":quality+" AND j.first_seen_at >= datetime('now','-1 day')",
        "remote":quality+" AND lower(j.work_arrangement)='remote'",
        "salary-confirmed":quality+" AND j.salary_min IS NOT NULL",
        "saved":"j.eligible=1 AND j.review_status='saved'",
        "awaiting-ai":"j.eligible=1 AND j.ai_status IN ('pending','retry')",
        "dismissed":"j.review_status='dismissed'",
        "excluded":"j.eligible=0",
    }
    if view not in views: raise HTTPException(404,"Unknown job view")
    clauses.append(views[view])
    if view in {"best-matches","new-today","remote","salary-confirmed"}: params += [threshold,age_modifier]
    elif min_score is not None: clauses.append("j.combined_score>=?"); params.append(threshold)
    if max_age is not None and view not in {"best-matches","new-today","remote","salary-confirmed","excluded"}:
        clauses.append("(j.posted_at IS NULL OR j.posted_at>=datetime('now',?))"); params.append(age_modifier)
    if q: clauses.append("(j.title LIKE ? OR j.company_name LIKE ? OR j.description LIKE ?)"); params += [f"%{q}%"]*3
    if location: clauses.append("j.location LIKE ?"); params.append(f"%{location}%")
    if arrangement in {"remote","hybrid","onsite"}: clauses.append("lower(j.work_arrangement)=?"); params.append(arrangement)
    if salary_disclosed: clauses.append("j.salary_min IS NOT NULL")
    ordering={"score":"j.combined_score DESC,j.first_seen_at DESC","newest":"COALESCE(j.posted_at,j.first_seen_at) DESC","salary":"j.salary_min DESC,j.combined_score DESC"}.get(sort,"j.combined_score DESC,j.first_seen_at DESC")
    return hydrate_jobs(rows("SELECT j.*,a.stage application_stage FROM jobs j LEFT JOIN applications a ON a.job_id=j.id WHERE "+" AND ".join(clauses)+" ORDER BY "+ordering+" LIMIT 1000",params))

@router.get("/jobs/filter-metadata")
def job_filter_metadata():
    return {"locations":get_settings().get("target_locations",[]),"arrangements":["remote","hybrid","onsite"],"score_range":{"min":0,"max":100},"sorts":["score","newest","salary"]}
@router.get("/jobs/{job_id}")
def job(job_id:int):
    found=row("SELECT j.*,a.id application_id,a.stage application_stage,a.notes application_notes FROM jobs j LEFT JOIN applications a ON a.job_id=j.id WHERE j.id=?",(job_id,))
    if not found: raise HTTPException(404,"Job not found")
    return hydrate_job(found)
@router.post("/jobs/manual")
def manual_job(item:ManualJob):
    data=item.model_dump(mode="json"); ch=content_hash(data); settings=get_settings(); score,explain=rule_score(data,settings,{})
    ext=ch[:20]
    with connect() as db:
        jid=db.execute("INSERT INTO jobs(company_name,external_id,source_type,source_url,canonical_url,title,location,description,salary_min,salary_max,first_seen_at,last_seen_at,content_hash,rule_score,combined_score,eligible,eligibility_reason,match_tier,rule_result,ai_status,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(item.company_name,ext,"manual",str(item.source_url),str(item.source_url),item.title,item.location,item.description,item.salary_min,item.salary_max,now(),now(),ch,score,score,int(explain["eligible"]),explain["eligibility_reason"],match_tier(score,bool(explain["eligible"]),"stretch_experience" in explain.get("penalty_codes",[])),json.dumps(explain),"pending" if explain["eligible"] else "not_applicable",now())).lastrowid
    return hydrate_job(row("SELECT * FROM jobs WHERE id=?",(jid,)))
@router.patch("/jobs/{job_id}/review")
def review(job_id:int,item:ReviewIn):
    with connect() as db: db.execute("UPDATE jobs SET review_status=?,dismiss_reason=?,updated_at=? WHERE id=?",(item.status,item.reason,now(),job_id))
    if item.status=="preparing": application_save(job_id,ApplicationIn())
    return {"ok":True}

@router.get("/applications")
def applications(): return rows("SELECT a.*,j.title,j.company_name,j.location,j.source_url,j.combined_score FROM applications a JOIN jobs j ON j.id=a.job_id ORDER BY a.updated_at DESC")
@router.put("/applications/{job_id}")
def application_save(job_id:int,item:ApplicationIn):
    existing=row("SELECT * FROM applications WHERE job_id=?",(job_id,)); previous=existing["stage"] if existing else None
    with connect() as db:
        db.execute("INSERT INTO applications(job_id,stage,notes,next_follow_up,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET stage=excluded.stage,notes=excluded.notes,next_follow_up=excluded.next_follow_up,updated_at=excluded.updated_at",(job_id,item.stage,item.notes,item.next_follow_up,now(),now()))
        app=db.execute("SELECT id FROM applications WHERE job_id=?",(job_id,)).fetchone()[0]
        if previous != item.stage: db.execute("INSERT INTO stage_events(application_id,from_stage,to_stage,happened_at) VALUES(?,?,?,?)",(app,previous,item.stage,now()))
        db.execute("UPDATE jobs SET review_status='preparing' WHERE id=?",(job_id,))
    return row("SELECT * FROM applications WHERE job_id=?",(job_id,))
@router.get("/applications/{app_id}/details")
def app_details(app_id:int): return {"tasks":rows("SELECT * FROM tasks WHERE application_id=?",(app_id,)),"contacts":rows("SELECT * FROM contacts WHERE application_id=?",(app_id,)),"history":rows("SELECT * FROM stage_events WHERE application_id=? ORDER BY happened_at DESC",(app_id,))}
@router.post("/applications/{app_id}/tasks")
def task_add(app_id:int,item:NoteIn):
    with connect() as db: tid=db.execute("INSERT INTO tasks(application_id,title,due_at) VALUES(?,?,?)",(app_id,item.title,item.due_at)).lastrowid
    return row("SELECT * FROM tasks WHERE id=?",(tid,))
@router.patch("/tasks/{task_id}")
def task_update(task_id:int,item:TaskUpdateIn):
    existing=row("SELECT * FROM tasks WHERE id=?",(task_id,))
    if not existing: raise HTTPException(404,"Task not found")
    values=item.model_dump(exclude_none=True)
    if values:
        with connect() as db: db.execute("UPDATE tasks SET "+", ".join(f"{k}=?" for k in values)+" WHERE id=?",(*values.values(),task_id))
    return row("SELECT * FROM tasks WHERE id=?",(task_id,))
@router.delete("/tasks/{task_id}")
def task_delete(task_id:int):
    with connect() as db: db.execute("DELETE FROM tasks WHERE id=?",(task_id,))
    return {"ok":True}
@router.post("/applications/{app_id}/contacts")
def contact_add(app_id:int,item:NoteIn):
    with connect() as db: cid=db.execute("INSERT INTO contacts(application_id,name,email,role,notes) VALUES(?,?,?,?,?)",(app_id,item.name,item.email,item.role,item.notes)).lastrowid
    return row("SELECT * FROM contacts WHERE id=?",(cid,))
@router.patch("/contacts/{contact_id}")
def contact_update(contact_id:int,item:ContactUpdateIn):
    existing=row("SELECT * FROM contacts WHERE id=?",(contact_id,))
    if not existing: raise HTTPException(404,"Contact not found")
    values=item.model_dump(exclude_none=True)
    if values:
        with connect() as db: db.execute("UPDATE contacts SET "+", ".join(f"{k}=?" for k in values)+" WHERE id=?",(*values.values(),contact_id))
    return row("SELECT * FROM contacts WHERE id=?",(contact_id,))
@router.delete("/contacts/{contact_id}")
def contact_delete(contact_id:int):
    with connect() as db: db.execute("DELETE FROM contacts WHERE id=?",(contact_id,))
    return {"ok":True}

@router.get("/profile")
def profile():
    p=row("SELECT redacted_text,profile_json,approved,updated_at FROM profile WHERE id=1"); p["profile"]=json.loads(p.pop("profile_json") or "{}"); return p
@router.post("/profile/resume")
async def profile_resume(file:UploadFile=File(...)):
    if file.content_type!="application/pdf" and not file.filename.lower().endswith(".pdf"): raise HTTPException(400,"Upload a PDF")
    target=UPLOAD_DIR/"resume.pdf"; target.write_bytes(await file.read()); raw=extract_pdf(target); safe=redact(raw); suggested=suggest_profile(safe)
    with connect() as db: db.execute("UPDATE profile SET resume_path=?,raw_text=?,redacted_text=?,profile_json=?,approved=0,updated_at=? WHERE id=1",(str(target),raw,safe,json.dumps(suggested),now()))
    return {"redacted_text":safe,"profile":suggested,"approved":False}
@router.put("/profile")
def profile_save(item:ProfileIn):
    with connect() as db:
        db.execute("UPDATE profile SET redacted_text=?,profile_json=?,approved=?,updated_at=? WHERE id=1",(item.redacted_text,json.dumps(item.profile),int(item.approved),now()))
        # Profile edits invalidate prior AI matches without deleting results.
        db.execute("UPDATE jobs SET ai_status='pending' WHERE active=1 AND eligible=1")
    rescore_active_jobs()
    return profile()

@router.post("/deepseek/key")
def deepseek_key(item:SecretIn): set_secret(DEEPSEEK_KEY_ACCOUNT,item.value); return {"configured":True}
@router.get("/deepseek/status")
def deepseek_status(): return {"configured":bool(get_secret(DEEPSEEK_KEY_ACCOUNT)),"month_spend":month_spend(),"budget":get_settings()["monthly_ai_budget"]}
@router.post("/refresh")
async def refresh(): return await refresh_all()

@router.get("/analytics")
def analytics():
    return {"jobs":row("SELECT COUNT(*) total,SUM(active) active,SUM(review_status='inbox') inbox,SUM(ai_status IN ('pending','retry')) pending_ai FROM jobs"),
            "applications":rows("SELECT stage,COUNT(*) count FROM applications GROUP BY stage"),
            "sources":rows("SELECT source_type,COUNT(*) count FROM jobs GROUP BY source_type"),"month_ai_spend":month_spend()}
@router.get("/today")
def today():
    settings=get_settings(); threshold=float(settings.get("minimum_match_score",60)); age=f"-{int(settings.get('max_job_age_days',45))} day"
    return {
        "review":row("SELECT COUNT(*) total, SUM(review_status='inbox' AND combined_score>=? AND (posted_at IS NULL OR posted_at>=datetime('now',?))) remaining, SUM(review_status='saved') saved FROM jobs WHERE active=1 AND eligible=1",(threshold,age)),
        "top_matches":hydrate_jobs(rows("SELECT * FROM jobs WHERE active=1 AND eligible=1 AND review_status='inbox' AND combined_score>=? AND (posted_at IS NULL OR posted_at>=datetime('now',?)) ORDER BY combined_score DESC,first_seen_at DESC LIMIT 5",(threshold,age))),
        "tasks":rows("SELECT t.*,a.stage,j.title,j.company_name FROM tasks t JOIN applications a ON a.id=t.application_id JOIN jobs j ON j.id=a.job_id WHERE t.completed=0 ORDER BY CASE WHEN t.due_at IS NULL THEN 1 ELSE 0 END,t.due_at LIMIT 8"),
        "follow_ups":rows("SELECT a.*,j.title,j.company_name FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.next_follow_up IS NOT NULL AND a.next_follow_up <= date('now','+7 day') ORDER BY a.next_follow_up LIMIT 8"),
        "attention":rows("SELECT a.*,j.title,j.company_name FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.stage IN ('Preparing','Recruiter Screen','Interviewing') ORDER BY COALESCE(a.next_follow_up,a.updated_at) LIMIT 6"),
        "system":system(),
    }
@router.get("/system")
def system(): return {"source_counts":row("SELECT COUNT(*) total,SUM(shortlisted) shortlisted,SUM(enabled AND ats_type!='catalog') active,SUM(ats_type='catalog') catalog FROM companies"),"last_run":row("SELECT * FROM ingestion_runs ORDER BY id DESC LIMIT 1"),"gmail_connected":gmail_connected(),"deepseek":deepseek_status()}
@router.get("/export/jobs.csv")
def export_jobs():
    data=rows("SELECT company_name,title,location,source_url,combined_score,review_status,active,first_seen_at FROM jobs ORDER BY combined_score DESC")
    out=io.StringIO(); writer=csv.DictWriter(out,fieldnames=list(data[0]) if data else ["company_name"]); writer.writeheader(); writer.writerows(data)
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=jobs.csv"})
@router.post("/backup")
def backup():
    target=DB_PATH.parent/f"job-tracker-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
    with connect() as db, __import__('sqlite3').connect(target) as dest: db.backup(dest)
    return {"path":str(target)}
