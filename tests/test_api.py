import os
from fastapi.testclient import TestClient

import app.config as config
import app.db as dbmod
from app.api import board_token

def test_board_token_accepts_careers_urls_and_tokens():
    assert board_token("greenhouse","https://boards.greenhouse.io/example/jobs/1")=="example"
    assert board_token("greenhouse","https://boards.greenhouse.io/example")=="example"
    assert board_token("lever","https://jobs.lever.co/example")=="example"
    assert board_token("ashby","https://jobs.ashbyhq.com/example")=="example"
    assert board_token("recruitee","https://example.recruitee.com/")=="example"

def test_health_and_manual_job(tmp_path,monkeypatch):
    path=tmp_path/"test.sqlite3"
    monkeypatch.setattr(config,"DB_PATH",path); monkeypatch.setattr(dbmod,"DB_PATH",path)
    from app.main import app
    with TestClient(app) as client:
        assert client.get('/api/health').json()=={"status":"ok"}
        result=client.post('/api/jobs/manual',json={"company_name":"Example","title":"Associate Product Manager","source_url":"https://example.com/job/1","location":"Seattle","description":"1 year product experience"})
        assert result.status_code==200
        jobs=client.get('/api/jobs').json(); assert len(jobs)==1 and jobs[0]["company_name"]=="Example"
        assert jobs[0]["match_tier"] in {"strong","good","stretch","low"} and isinstance(jobs[0]["rule_result"],dict)
        assert len(client.get('/api/jobs/views/all-matches').json())==1
        blocked=client.post('/api/jobs/manual',json={"company_name":"Example","title":"Program Manager, Contract","source_url":"https://example.com/job/2","location":"Seattle","description":"2 years experience"})
        assert blocked.status_code==200 and blocked.json()["eligible"]==0
        assert len(client.get('/api/jobs/views/excluded').json())==1
