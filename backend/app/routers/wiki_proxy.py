import asyncio
import re
from urllib.parse import quote, urlparse

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

from app.config import settings

router = APIRouter()

_ALLOWED_HOSTS = {"danbooru.donmai.us", "cdn.donmai.us"}

# Only link-click interceptor remains in JS injection.
# Image URLs are rewritten server-side (more reliable than lazy-loader JS timing).
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


def _danbooru_auth():
    if settings.danbooru_username and settings.danbooru_api_key:
        return (settings.danbooru_username, settings.danbooru_api_key)
    return None


def _proxy_img_url(raw: str) -> str:
    """Convert an absolute or relative donmai image URL to our proxy path."""
    url = raw.strip()
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = "https://danbooru.donmai.us" + url
    return "/api/wiki-proxy-image?url=" + quote(url, safe="")


def _rewrite_img_urls(html: str) -> str:
    """
    Server-side rewrite of <img> src / data-src attributes that point to donmai CDN.
    Converting data-src to src ensures images load without needing danbooru's lazy-loader JS.
    Also removes srcset to prevent the browser fetching unreachable CDN URLs directly.
    """
    def _replace_attr(m: re.Match) -> str:
        attr = m.group(1)   # "src" or "data-src"
        quote_char = m.group(2)  # ' or "
        url = m.group(3)
        # skip already-proxied
        if "/api/wiki-proxy-image" in url:
            return m.group(0)
        if url.startswith("//"):
            full = "https:" + url
        elif url.startswith("/"):
            full = "https://danbooru.donmai.us" + url
        else:
            full = url
        if "donmai.us" not in full:
            return m.group(0)
        proxy = _proxy_img_url(url)
        # always emit as src= so the browser loads it immediately
        return f'src={quote_char}{proxy}{quote_char}'

    # Match src="..." data-src="..." (both single and double quotes)
    html = re.sub(
        r'((?:data-)?src)=(["\'])((?:https?:)?//[^"\']*|/[^"\']+)\2',
        _replace_attr,
        html,
    )
    # Strip srcset attributes entirely (they'd bypass the proxy)
    html = re.sub(r'\s*srcset=["\'][^"\']*["\']', "", html)
    return html


def _fetch_and_patch(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc not in _ALLOWED_HOSTS:
        raise ValueError("disallowed host")
    resp = requests.get(
        url,
        auth=_danbooru_auth(),
        headers={"User-Agent": "Mozilla/5.0 (compatible; CatalogueManager/1.0)"},
        timeout=15,
        allow_redirects=True,
    )
    resp.raise_for_status()
    html = resp.text
    # 1) rewrite image URLs before injecting our script
    html = _rewrite_img_urls(html)
    # 2) inject link-interceptor script
    html = re.sub(r"(<head[^>]*>)", r"\1" + _INJECT, html, count=1, flags=re.IGNORECASE)
    if "<head" not in html.lower():
        html = _INJECT + html
    return html


def _fetch_image(url: str) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.netloc not in _ALLOWED_HOSTS:
        raise ValueError("disallowed host")
    resp = requests.get(
        url,
        auth=_danbooru_auth(),
        headers={"User-Agent": "Mozilla/5.0 (compatible; CatalogueManager/1.0)"},
        timeout=30,
        allow_redirects=True,
    )
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "image/jpeg")
    return resp.content, content_type


@router.get("/wiki-proxy", response_class=HTMLResponse)
async def wiki_proxy(url: str) -> HTMLResponse:
    try:
        html = await asyncio.to_thread(_fetch_and_patch, url)
    except ValueError:
        raise HTTPException(status_code=400, detail="Only danbooru.donmai.us URLs are allowed")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch wiki page: {exc}")
    return HTMLResponse(content=html)


@router.get("/wiki-proxy-image")
async def wiki_proxy_image(url: str) -> Response:
    try:
        content, content_type = await asyncio.to_thread(_fetch_image, url)
    except ValueError:
        raise HTTPException(status_code=400, detail="Only danbooru/cdn.donmai.us URLs are allowed")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch image: {exc}")
    return Response(content=content, media_type=content_type)
