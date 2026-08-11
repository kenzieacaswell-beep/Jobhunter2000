"""Apply the reviewed resume profile and reclassify the existing job backlog."""
import json, shutil, sys
from pathlib import Path

from .config import UPLOAD_DIR
from .db import connect, get_settings, init_db, now, rows, set_settings
from .resume import extract_pdf, redact
from .scoring import combine, match_tier, rule_score

PROFILE={
 "summary":"Early-career technical program and engineering project manager with experience delivering cross-functional manufacturing, cost-reduction, operational, and systems initiatives in consumer products and electric vehicles.",
 "experience_years":2.0,
 "experience_including_internships_years":2.5,
 "target_roles":["Associate Product Manager","Product Operations Analyst","Product Analyst","Technical Program Manager","Program Manager","Project Manager","Engineering Project Manager","Operations Program Manager","Manufacturing Program Manager"],
 "roles":[
  {"title":"Engineering Project Manager","company":"Procter & Gamble","focus":["cross-functional delivery","cost optimization","manufacturing validation","PLM and BOM lifecycle","supply risk"]},
  {"title":"Technical Program Manager Intern","company":"Tesla","focus":["OKRs","executive reporting","Jira and Confluence systems","capacity planning"]},
  {"title":"Battery Cell Factory Engineering Co-op","company":"Rivian","focus":["capital projects","factory launch","resource planning","contractor coordination","cost modeling"]},
 ],
 "skills":["Technical program management","Project management","Cross-functional leadership","Risk management","OKRs","Process improvement","Manufacturing validation","Supply chain optimization","BOM lifecycle management","Cost modeling","Enovia PLM","SAP","Jira","Confluence","Tableau","SQL","Python","AutoCAD","SolidWorks","Simio","Microsoft 365","AI tool development"],
 "education":["B.E. Industrial & Systems Engineering, Texas A&M University","Minor in Engineering Project Management"],
 "product_context":{"strengths":["translating requirements into execution","analytical decision support","stakeholder alignment","systems and workflow design"],"gaps":["limited direct software roadmap ownership","limited consumer product discovery and experimentation"]},
}

PREFERENCES={
 "role_keywords":["associate product manager","junior product manager","product manager i","product analyst","product operations","technical program manager","program manager","project manager","engineering project manager","operations program manager","manufacturing program manager"],
 "excluded_keywords":["senior","sr.","staff","principal","director","head of","vice president","vp","distinguished","group product manager","manager ii","manager iii"],
 "maximum_required_experience":5,
}

def apply(resume_path:Path) -> dict:
    init_db(); UPLOAD_DIR.mkdir(parents=True,exist_ok=True)
    target=UPLOAD_DIR/"resume.pdf"; shutil.copy2(resume_path,target)
    raw=extract_pdf(target); safe=redact(raw)
    if any(value.lower() in safe.lower() for value in ["mackenzie caswell","kenzieacaswell@gmail.com","650.454.6379","linkedin.com/in/mackenziecaswell"]):
        raise ValueError("Resume redaction verification failed")
    set_settings(PREFERENCES); settings=get_settings()
    with connect() as db:
        db.execute("UPDATE profile SET resume_path=?,raw_text=?,redacted_text=?,profile_json=?,approved=1,updated_at=? WHERE id=1",(str(target),raw,safe,json.dumps(PROFILE),now()))
    stats={"eligible":0,"filtered":0,"reclassified":0}
    for job in rows("SELECT * FROM jobs"):
        score,explain=rule_score(job,settings,PROFILE); eligible=int(explain["eligible"])
        ai_score=job.get("ai_score") if eligible else None
        status="pending" if eligible else "not_applicable"
        with connect() as db:
            combined=combine(score,ai_score) if eligible else 0.0
            db.execute("UPDATE jobs SET rule_score=?,combined_score=?,eligible=?,eligibility_reason=?,match_tier=?,rule_result=?,ai_status=?,ai_score=?,updated_at=? WHERE id=?",(score,combined,eligible,explain["eligibility_reason"],match_tier(combined,bool(eligible),"stretch_experience" in explain.get("penalty_codes",[])),json.dumps(explain),status,ai_score,now(),job["id"]))
        stats["eligible" if eligible else "filtered"]+=1;stats["reclassified"]+=1
    return {"profile":PROFILE,"redacted_characters":len(safe),"jobs":stats}

if __name__=="__main__":
    if len(sys.argv)!=2: raise SystemExit("Usage: python -m app.refine_matching /path/to/resume.pdf")
    print(json.dumps(apply(Path(sys.argv[1])),indent=2))
