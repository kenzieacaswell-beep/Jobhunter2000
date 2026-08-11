import asyncio, json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.connectors import Recruitee, clean_html
from app.deepseek import Evaluation
from app.resume import redact
from app.scoring import combine, eligibility_assessment, match_tier, rule_score

SETTINGS={"role_keywords":["product manager","program manager"],"excluded_keywords":["senior","director"],
          "target_locations":["San Francisco Bay Area","Seattle","Austin, TX","US Remote"],"salary_floor":90000,"maximum_required_experience":5,
          "allow_us_remote":True,"allow_hybrid":True,"allow_onsite":True,"allow_unknown_location":True,
          "max_job_age_days":45,"scoring_weights":{"role":30,"experience":25,"location":20,"skills":15,"freshness":10}}

def test_redaction_removes_personal_details():
    text="Jane Doe\njane@example.com | (415) 555-1212\n123 Main Street, San Francisco\nhttps://linkedin.com/in/jane\nProduct work"
    safe=redact(text)
    assert "Jane Doe" not in safe and "jane@example.com" not in safe and "555-1212" not in safe
    assert "123 Main" not in safe and "linkedin.com" not in safe and "Product work" in safe

def test_rule_scoring_rewards_junior_target_role():
    good={"title":"Associate Product Manager","description":"1-2 years. SQL and user research.","location":"San Francisco, CA","salary_min":110000}
    bad={"title":"Senior Product Manager","description":"8+ years","location":"New York","salary_min":80000}
    gs,detail=rule_score(good,SETTINGS,{"skills":["SQL","user research"]}); bs,_=rule_score(bad,SETTINGS,{})
    assert gs > bs and gs >= 70 and "product manager" in detail["role_hits"]

def test_unknown_salary_is_not_penalized():
    job={"title":"Program Manager","description":"Required experience: 2 years","location":"Remote","salary_min":None}
    score,detail=rule_score(job,SETTINGS,{})
    assert detail["components"]["salary"] == 0 and score > 50

def test_score_combination(): assert combine(80,60)==69 and combine(80,None)==80

def test_html_cleaning(): assert clean_html("<p>Hello &amp; welcome</p>") == "Hello & welcome"

def test_recruitee_connector_normalizes_public_offers():
    response=MagicMock(); response.raise_for_status.return_value=response
    response.json.return_value={"offers":[{"id":7,"title":"Program Manager","locations":[{"name":"Austin, TX"}],"description":"<p>Build programs</p>","requirements":"2 years experience","careers_url":"https://example.recruitee.com/o/program-manager","published_at":"2026-08-01T00:00:00Z"}]}
    with patch("app.connectors.httpx.AsyncClient") as client:
        client.return_value.__aenter__.return_value.get=AsyncMock(return_value=response)
        jobs=asyncio.run(Recruitee().fetch("example"))
    assert jobs[0]["title"]=="Program Manager" and jobs[0]["location"]=="Austin, TX"
    assert jobs[0]["description"]=="Build programs 2 years experience"

def test_deepseek_schema_rejects_out_of_range_score():
    payload={"role_family":"product","seniority":"junior","fit_score":101,"score_components":{},"rationale":"x"}
    try: Evaluation.model_validate(payload)
    except Exception: pass
    else: raise AssertionError("invalid score accepted")

def test_manager_role_without_level_is_ranked_with_a_concern():
    job={"title":"Technical Program Manager","description":"Own the company-wide platform roadmap."}
    score,detail=rule_score(job,SETTINGS,{})
    assert detail["eligible"] is True and score > 0
    assert "manager_level_unknown" in detail["penalty_codes"]

def test_five_year_role_is_stretch_but_six_year_and_contract_roles_are_filtered():
    stretch={"title":"Product Operations Manager","description":"Requirements include 5+ years of product operations experience.","location":"Seattle"}
    experienced={"title":"Product Operations Manager","description":"Requirements include 6+ years of product operations experience."}
    contract={"title":"Program Manager - Growth Operations, Contract","description":"Requires 2 years experience."}
    score,detail=rule_score(stretch,SETTINGS,{})
    assert detail["eligible"] is True and "stretch_experience" in detail["penalty_codes"] and detail["match_tier"]=="stretch" and score > 0
    assert eligibility_assessment(experienced,SETTINGS)[0] is False
    assert eligibility_assessment(contract,SETTINGS)[0] is False

def test_associate_product_and_operations_roles_are_eligible():
    assert eligibility_assessment({"title":"Associate Product Manager","description":"New graduate role"},SETTINGS)[0] is True
    assert eligibility_assessment({"title":"Product Manager","description":"Build product roadmaps"},SETTINGS)[0] is True
    assert eligibility_assessment({"title":"Product Operations Specialist","description":"Early career"},SETTINGS)[0] is True
    assert eligibility_assessment({"title":"Business Systems Analyst","description":"Improve operating workflows"},SETTINGS)[0] is True

def test_location_rules_distinguish_target_and_international_remote():
    strict={**SETTINGS,"allow_unknown_location":False}
    assert eligibility_assessment({"title":"Associate Product Manager","location":"Palo Alto, CA","description":"Entry level"},strict)[0] is True
    ok,reason,_=eligibility_assessment({"title":"Associate Product Manager","location":"Remote - Canada","description":"Entry level"},strict)
    assert ok is False and "International-only" in reason
    ok,_,detail=eligibility_assessment({"title":"Associate Product Manager","location":"Denver, CO","description":"Entry level"},strict)
    assert ok is True and detail["location"]["code"]=="outside_target_location"

def test_disclosed_salary_entirely_below_floor_is_downranked():
    job={"title":"Associate Product Manager","location":"Austin, TX","description":"Entry level","salary_min":60000,"salary_max":85000}
    score,detail=rule_score(job,SETTINGS,{})
    assert detail["eligible"] is True and score > 0 and "salary_below_floor" in detail["penalty_codes"]

def test_preferred_experience_does_not_trigger_hard_block():
    job={"title":"Product Manager","location":"Remote - USA","description":"Preferred: 8+ years. Required qualifications: 2 years product experience."}
    assert eligibility_assessment(job,SETTINGS)[0] is True

def test_match_tiers_have_stable_boundaries():
    assert [match_tier(x) for x in (75,60,40,39.9)]==["strong","good","stretch","low"]
    assert match_tier(90,False)=="excluded"
    assert match_tier(20,True,True)=="stretch"
