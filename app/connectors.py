import html, re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
import httpx

def clean_html(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()

class Connector(ABC):
    @abstractmethod
    async def fetch(self, token: str) -> list[dict]: ...

class Greenhouse(Connector):
    async def fetch(self, token: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=30) as client:
            data = (await client.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", params={"content":"true"})).raise_for_status().json()
        return [{"external_id":str(j["id"]),"title":j["title"],"location":j.get("location",{}).get("name",""),
                 "description":clean_html(j.get("content","")),"source_url":j["absolute_url"],"posted_at":j.get("updated_at"),"raw":j} for j in data["jobs"]]

class Lever(Connector):
    async def fetch(self, token: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=30) as client:
            data = (await client.get(f"https://api.lever.co/v0/postings/{token}", params={"mode":"json"})).raise_for_status().json()
        return [{"external_id":j["id"],"title":j["text"],"location":j.get("categories",{}).get("location",""),
                 "description":clean_html(" ".join([j.get("descriptionPlain",""),j.get("additionalPlain","")])),
                 "source_url":j["hostedUrl"],"posted_at":datetime.fromtimestamp(j.get("createdAt",0)/1000,timezone.utc).isoformat(),"raw":j} for j in data]

class Ashby(Connector):
    async def fetch(self, token: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=30) as client:
            data = (await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}")).raise_for_status().json()
        return [{"external_id":j.get("jobUrl",j["title"]),"title":j["title"],"location":j.get("location",""),
                 "description":clean_html(j.get("descriptionPlain",j.get("descriptionHtml",""))),"source_url":j["jobUrl"],
                 "posted_at":j.get("publishedAt"),"raw":j} for j in data.get("jobs",[]) if j.get("isListed",True)]

class Recruitee(Connector):
    async def fetch(self, token: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=30) as client:
            data=(await client.get(f"https://{token}.recruitee.com/api/offers/",headers={"Accept":"application/json"})).raise_for_status().json()
        jobs=[]
        for j in data.get("offers",[]):
            locations=j.get("locations") or []
            location="; ".join(dict.fromkeys((x.get("name") or ", ".join(filter(None,(x.get("city"),x.get("state"),x.get("country"))))) for x in locations if isinstance(x,dict)))
            jobs.append({"external_id":str(j.get("id") or j.get("slug")),"title":j.get("title","") ,"location":location or j.get("location","") ,
                         "description":clean_html(" ".join(filter(None,(j.get("description"),j.get("requirements"),j.get("description_html"))))),
                         "source_url":j.get("careers_url") or j.get("url") or f"https://{token}.recruitee.com/o/{j.get('slug','')}",
                         "posted_at":j.get("published_at") or j.get("created_at"),"raw":j})
        return jobs

CONNECTORS = {"greenhouse": Greenhouse(), "lever": Lever(), "ashby": Ashby(), "recruitee": Recruitee()}
