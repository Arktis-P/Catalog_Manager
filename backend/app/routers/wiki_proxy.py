import asyncio
import html
import re
from urllib.parse import quote, unquote, urlparse

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.config import settings

router = APIRouter()

_ALLOWED_HOSTS = {"danbooru.donmai.us", "cdn.donmai.us"}

# Placeholder {ORIGIN} is replaced at request-time with the local app origin.
_INJECT_TEMPLATE = """\
<base href="https://danbooru.donmai.us/">
<script>(function(){{
var _O="{ORIGIN}";
var _P=_O+"/api/wiki-proxy-image?url=";
var _W=_O+"/api/wiki-proxy?url=";
function _isDonmai(u){{return u&&u.indexOf("donmai.us")>=0;}}
function _targetUrl(href){{
  if(!href)return "";
  if(_isDonmai(href))return href;
  if(href.indexOf(_W)===0){{
    try{{return new URL(href).searchParams.get("url")||"";}}catch(e){{return "";}}
  }}
  return "";
}}
function _fixImg(img){{
  var ds=img.getAttribute("data-src")||"";
  if(_isDonmai(ds)&&img.src.indexOf(_P)<0){{
    img.removeAttribute("data-src");
    img.src=_P+encodeURIComponent(ds);
    return;
  }}
  var cs=img.getAttribute("src")||"";
  if(_isDonmai(cs)&&cs.indexOf(_P)<0&&cs.indexOf(_O)<0){{
    img.src=_P+encodeURIComponent(cs);
  }}
}}
function _fixAll(){{document.querySelectorAll("img").forEach(_fixImg);}}
document.addEventListener("DOMContentLoaded",_fixAll);
setTimeout(_fixAll,500);
setTimeout(_fixAll,1500);
new MutationObserver(function(muts){{
  muts.forEach(function(m){{
    if(m.type==="childList"){{
      m.addedNodes.forEach(function(n){{
        if(n.nodeType!==1)return;
        if(n.tagName==="IMG")_fixImg(n);
        if(n.querySelectorAll)n.querySelectorAll("img").forEach(_fixImg);
      }});
    }}
    if(m.type==="attributes"&&m.target.tagName==="IMG")_fixImg(m.target);
  }});
}}).observe(document.documentElement,{{
  childList:true,subtree:true,attributes:true,
  attributeFilter:["src","data-src"]
}});
document.addEventListener("click",function(e){{
  var a=e.target.closest("a");
  if(!a||!a.href)return;
  var u=_targetUrl(a.href);
  if(u){{
    e.preventDefault();
    e.stopImmediatePropagation();
    window.parent.postMessage({{type:"wiki-navigate",url:u}},"*");
  }}
}},true);
document.addEventListener("mousedown",function(e){{
  if(e.button===3){{e.preventDefault();window.parent.postMessage({{type:"wiki-back"}},"*");}}
  if(e.button===4){{e.preventDefault();window.parent.postMessage({{type:"wiki-forward"}},"*");}}
}},true);
}})();
</script>"""


def _danbooru_auth():
    if settings.danbooru_username and settings.danbooru_api_key:
        return (settings.danbooru_username, settings.danbooru_api_key)
    return None


def _to_full_url(url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://danbooru.donmai.us" + url
    return url


def _is_allowed_url(url: str) -> bool:
    return urlparse(url).netloc in _ALLOWED_HOSTS


def _proxy_img_url(raw: str, local_origin: str) -> str:
    """Absolute proxy URL; prevents <base href> from redirecting relative URLs."""
    return f"{local_origin}/api/wiki-proxy-image?url={quote(_to_full_url(raw.strip()), safe='')}"


def _proxy_page_url(raw: str, local_origin: str) -> str:
    return f"{local_origin}/api/wiki-proxy?url={quote(_to_full_url(raw.strip()), safe='')}"


def _wiki_tag_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path.startswith("/wiki_pages/"):
        return None
    tag = unquote(path.rsplit("/", 1)[-1]).strip()
    return tag or None


def _rewrite_img_tag(img_match: re.Match, local_origin: str) -> str:
    tag = img_match.group(0)

    ds_m = re.search(r'data-src=(["\'])((?:https?:)?//[^"\']+|/[^"\']+)\1', tag)
    if ds_m:
        raw = ds_m.group(2)
        if _is_allowed_url(_to_full_url(raw)):
            proxy = _proxy_img_url(raw, local_origin)
            tag = re.sub(r'\s*data-src=["\'][^"\']*["\']', "", tag)
            tag = re.sub(r'\s*src=["\'][^"\']*["\']', "", tag)
            tag = re.sub(
                r'(<img\b)',
                lambda m: m.group(1) + f' src="{proxy}"',
                tag,
                count=1,
                flags=re.IGNORECASE,
            )
            tag = re.sub(r'\s*srcset=["\'][^"\']*["\']', "", tag)
            return tag

    src_m = re.search(r'\bsrc=(["\'])((?:https?:)?//[^"\']+|/[^"\']+)\1', tag)
    if src_m:
        raw = src_m.group(2)
        if _is_allowed_url(_to_full_url(raw)) and "/api/wiki-proxy-image" not in raw:
            q = src_m.group(1)
            proxy = _proxy_img_url(raw, local_origin)
            tag = tag[: src_m.start()] + f"src={q}{proxy}{q}" + tag[src_m.end():]
            tag = re.sub(r'\s*srcset=["\'][^"\']*["\']', "", tag)

    return tag


def _rewrite_link_tag(link_match: re.Match, local_origin: str) -> str:
    tag = link_match.group(0)
    href_m = re.search(r'\bhref=(["\'])((?:https?:)?//[^"\']+|/[^"\']+)\1', tag)
    if not href_m:
        return tag

    raw = href_m.group(2)
    full = _to_full_url(raw)
    if not _is_allowed_url(full):
        return tag

    q = href_m.group(1)
    proxy = _proxy_page_url(full, local_origin)
    tag = tag[: href_m.start()] + f"href={q}{proxy}{q}" + tag[href_m.end():]
    return re.sub(r'\s*target=(["\'])[^"\']*\1', "", tag, flags=re.IGNORECASE)


def _strip_scripts(html: str) -> str:
    return re.sub(r'<script\b[^>]*>.*?</script>', "", html, flags=re.IGNORECASE | re.DOTALL)


def _rewrite_img_urls(html: str, local_origin: str) -> str:
    return re.sub(
        r'<img\b[^>]*>',
        lambda m: _rewrite_img_tag(m, local_origin),
        html,
        flags=re.IGNORECASE,
    )


def _rewrite_link_urls(html: str, local_origin: str) -> str:
    return re.sub(
        r'<a\b[^>]*>',
        lambda m: _rewrite_link_tag(m, local_origin),
        html,
        flags=re.IGNORECASE,
    )


def _fetch_post_previews(tag: str) -> list[dict]:
    resp = requests.get(
        "https://danbooru.donmai.us/posts.json",
        params={"tags": tag, "limit": 24},
        auth=_danbooru_auth(),
        headers={"User-Agent": "Mozilla/5.0 (compatible; CatalogueManager/1.0)"},
        timeout=15,
    )
    resp.raise_for_status()
    posts = resp.json()
    if not isinstance(posts, list):
        return []

    previews = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        preview_url = post.get("preview_file_url") or post.get("large_file_url") or post.get("file_url")
        post_id = post.get("id")
        if not preview_url or not post_id:
            continue
        previews.append(
            {
                "id": str(post_id),
                "preview_url": str(preview_url),
                "rating": str(post.get("rating") or ""),
                "score": str(post.get("score") or ""),
            }
        )
    return previews


def _render_post_previews(previews: list[dict], local_origin: str) -> str:
    if not previews:
        return ""

    items = []
    for post in previews:
        post_url = _proxy_page_url(f"https://danbooru.donmai.us/posts/{post['id']}", local_origin)
        img_url = _proxy_img_url(post["preview_url"], local_origin)
        title = f"post #{post['id']}"
        if post["rating"]:
            title += f" rating:{post['rating']}"
        if post["score"]:
            title += f" score:{post['score']}"
        items.append(
            '<a class="catalogue-proxy-post-preview" '
            f'href="{html.escape(post_url, quote=True)}" '
            f'title="{html.escape(title, quote=True)}">'
            f'<img src="{html.escape(img_url, quote=True)}" alt="{html.escape(title, quote=True)}" loading="lazy">'
            "</a>"
        )

    return (
        '<style>'
        '.catalogue-proxy-post-grid{display:flex;flex-wrap:wrap;gap:8px;margin:0.75rem 0 1.25rem;}'
        '.catalogue-proxy-post-preview{display:inline-flex;width:96px;height:96px;align-items:center;justify-content:center;'
        'background:#111827;border:1px solid rgba(148,163,184,.35);border-radius:4px;overflow:hidden;}'
        '.catalogue-proxy-post-preview img{max-width:100%;max-height:100%;object-fit:contain;display:block;}'
        '</style>'
        '<div class="catalogue-proxy-post-grid">'
        + "".join(items)
        + "</div>"
    )


def _inject_post_previews(html_text: str, source_url: str, local_origin: str) -> str:
    if "catalogue-proxy-post-grid" in html_text or "post-preview-image" in html_text:
        return html_text

    tag = _wiki_tag_from_url(source_url)
    if not tag:
        return html_text

    try:
        previews = _fetch_post_previews(tag)
    except Exception:
        return html_text

    gallery = _render_post_previews(previews, local_origin)
    if not gallery:
        return html_text

    posts_heading = re.search(r'(<h[1-6][^>]*>\s*Posts\s*</h[1-6]>)', html_text, flags=re.IGNORECASE)
    if posts_heading:
        insert_at = posts_heading.end()
        return html_text[:insert_at] + gallery + html_text[insert_at:]

    return html_text + gallery


def _fetch_and_patch(url: str, local_origin: str) -> str:
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

    html = _strip_scripts(html)
    html = _rewrite_img_urls(html, local_origin)
    html = _rewrite_link_urls(html, local_origin)
    html = _inject_post_previews(html, url, local_origin)

    inject = _INJECT_TEMPLATE.replace("{ORIGIN}", local_origin)
    patched = re.sub(
        r'(<head[^>]*>)',
        lambda m: m.group(1) + "\n" + inject,
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    if patched is html or "<head" not in html.lower():
        patched = inject + html
    return patched


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
async def wiki_proxy(url: str, request: Request) -> HTMLResponse:
    local_origin = str(request.base_url).rstrip("/")
    try:
        html = await asyncio.to_thread(_fetch_and_patch, url, local_origin)
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
