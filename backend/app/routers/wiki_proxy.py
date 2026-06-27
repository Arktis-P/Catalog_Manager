import asyncio
import re
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

router = APIRouter()

_ALLOWED_HOST = "danbooru.donmai.us"

_INJECT = (
    '<base href="https://danbooru.donmai.us/">'
    "<script>(function(){"
    "document.addEventListener('click',function(e){"
    "var a=e.target.closest('a');if(!a||!a.href)return;"
    "var u=a.href;"
    "if(u.includes('danbooru.donmai.us')||u.startsWith('/')){"
    "e.preventDefault();"
    "window.parent.postMessage({type:'wiki-navigate',url:u},'*');"
    "}"
    "},true);"
    "})();</script>"
)


def _fetch_and_patch(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc != _ALLOWED_HOST:
        raise ValueError("disallowed host")
    resp = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; CatalogueManager/1.0)"},
        timeout=15,
        allow_redirects=True,
    )
    resp.raise_for_status()
    html = resp.text
    html = re.sub(r"(<head[^>]*>)", r"\1" + _INJECT, html, count=1, flags=re.IGNORECASE)
    if "<head" not in html.lower():
        html = _INJECT + html
    return html


@router.get("/wiki-proxy", response_class=HTMLResponse)
async def wiki_proxy(url: str) -> HTMLResponse:
    try:
        html = await asyncio.to_thread(_fetch_and_patch, url)
    except ValueError:
        raise HTTPException(status_code=400, detail="Only danbooru.donmai.us URLs are allowed")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch wiki page: {exc}")
    return HTMLResponse(content=html)
