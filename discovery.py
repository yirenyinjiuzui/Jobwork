"""Read-only public ATS adapters and pure job snapshot comparison."""

from __future__ import annotations

import hashlib
import html
import json
import re
import socket
import time
import unicodedata
from collections.abc import Mapping
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote_plus, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BYTES = 12 * 1024 * 1024
MAX_ROWS = 5000
LEVER_PAGE_SIZE = 100
SMARTRECRUITERS_PAGE_SIZE = 100
_IDENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$", re.ASCII)
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$", re.ASCII)
_PROVIDERS = {"greenhouse", "greenhouse_eu", "lever", "lever_eu", "ashby", "smartrecruiters", "demo"}
_BOARD_HOSTS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "boards-api.greenhouse.io": "greenhouse",
    "boards.eu.greenhouse.io": "greenhouse_eu",
    "job-boards.eu.greenhouse.io": "greenhouse_eu",
    "jobs.lever.co": "lever",
    "api.lever.co": "lever",
    "jobs.eu.lever.co": "lever_eu",
    "api.eu.lever.co": "lever_eu",
    "jobs.ashbyhq.com": "ashby",
    "api.ashbyhq.com": "ashby",
    "careers.smartrecruiters.com": "smartrecruiters",
    "jobs.smartrecruiters.com": "smartrecruiters",
    "api.smartrecruiters.com": "smartrecruiters",
}
_API_HOSTS = {
    "greenhouse": "boards-api.greenhouse.io",
    # Greenhouse documents one public API host. This provider labels the EU
    # *board UI*, not a separately documented API host.
    "greenhouse_eu": "boards-api.greenhouse.io",
    "lever": "api.lever.co",
    "lever_eu": "api.eu.lever.co",
    "ashby": "api.ashbyhq.com",
    "smartrecruiters": "api.smartrecruiters.com",
}

class DiscoveryError(ValueError):
    """A source is invalid, unreadable, or not a complete authoritative snapshot."""

def _str(value, limit=600):
    if not isinstance(value, str):
        return ""
    return " ".join(value[:limit * 2].split())[:limit]

def _key(value):
    return unicodedata.normalize("NFKC", _str(value)).casefold()

def _public_url(value, *, official_only=False):
    """Validate a display-only URL. Never use this helper for outbound requests."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if len(value) > 4096 or re.search(r"[\\\x00-\x20\x7f]", value):
        return ""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or "@" in parsed.netloc or parsed.port not in (None, 443)):
            return ""
        if official_only and parsed.hostname not in _BOARD_HOSTS:
            return ""
        if not re.fullmatch(r"[a-z0-9.-]+", parsed.hostname, re.I):
            return ""
        return value
    except ValueError:
        return ""

def _board_from_url(value):
    if not _public_url(value, official_only=True):
        raise DiscoveryError("请输入官方 Greenhouse / Lever / Ashby / SmartRecruiters 招聘板链接，或只输入板块代号。")
    parsed = urlsplit(value.strip())
    provider = _BOARD_HOSTS[parsed.hostname]
    components = [part for part in parsed.path.strip("/").split("/") if part]
    if parsed.hostname == "boards-api.greenhouse.io":
        board = components[2] if components[:2] == ["v1", "boards"] and len(components) >= 3 else ""
    elif parsed.hostname == "api.ashbyhq.com":
        board = components[2] if components[:2] == ["posting-api", "job-board"] and len(components) == 3 else ""
    elif parsed.hostname == "api.smartrecruiters.com":
        board = components[2] if (len(components) in (4, 5)
                and components[:2] == ["v1", "companies"] and components[3] == "postings") else ""
    elif parsed.hostname.startswith("api."):
        board = components[2] if components[:2] == ["v0", "postings"] and len(components) >= 3 else ""
    elif components == ["embed", "job_board"] or components == ["embed", "job_app"]:
        board = parse_qs(parsed.query).get("for", [""])[0]
    else:
        board = components[0] if components else ""
    return provider, board

def validate_source(source: dict) -> dict:
    if not isinstance(source, Mapping):
        raise DiscoveryError("来源格式错误。")
    provider = _str(source.get("provider"), 30).casefold().replace("-", "_")
    raw_board = source.get("board")
    if not isinstance(raw_board, str) or len(raw_board) > 4096:
        raise DiscoveryError("请填写招聘板代号或官方 URL。")
    board = raw_board.strip()
    if "://" in board:
        actual, board = _board_from_url(board)
        if provider and provider != actual and not (
                {actual, provider} == {"greenhouse", "greenhouse_eu"}
                and raw_board.strip().startswith("https://boards-api.greenhouse.io/")):
            raise DiscoveryError("链接中的平台或地区与来源类型不一致。")
        provider = provider or actual
    if provider not in _PROVIDERS:
        raise DiscoveryError("仅支持 Greenhouse、Lever、Ashby、SmartRecruiters 和离线演示来源。")
    board = board.lower()
    if not _IDENT.fullmatch(board):
        raise DiscoveryError("板块代号只可包含英文字母、数字、下划线和短横线。")
    company = _str(source.get("company"), 160)
    if not company:
        raise DiscoveryError("请填写公司名。")
    return {"provider": provider, "board": board, "company": company}

def board_url(source: dict) -> str:
    source = validate_source(source)
    host = {
        "greenhouse": "job-boards.greenhouse.io",
        "greenhouse_eu": "job-boards.eu.greenhouse.io",
        "lever": "jobs.lever.co",
        "lever_eu": "jobs.eu.lever.co",
        "ashby": "jobs.ashbyhq.com",
        "smartrecruiters": "careers.smartrecruiters.com",
    }.get(source["provider"])
    return f"https://{host}/{source['board']}" if host else ""

class _Plain(HTMLParser):
    breaks = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "tr", "td", "section"}
    hidden = {"script", "style"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.hidden:
            self.suppressed += 1
        if tag in self.breaks and not self.suppressed:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.hidden and self.suppressed:
            self.suppressed -= 1
        if tag in self.breaks and not self.suppressed:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.suppressed:
            self.parts.append(data)

def _text(value):
    if not isinstance(value, str):
        return ""
    content = value[:175_000]
    # Greenhouse can return an HTML-escaped HTML string.
    if not re.search(r"<[A-Za-z]", content) and re.search(r"&lt;[A-Za-z]", content):
        content = html.unescape(content)
    if re.search(r"<[A-Za-z]", content):
        parser = _Plain()
        parser.feed(content)
        parser.close()
        content = "".join(parser.parts)
    return "\n".join(line for raw in content.splitlines() if (line := _str(raw, 1500)))

def classify_career(title, commitment=""):
    raw = _key(title)
    term = _key(commitment)
    if re.search(r"\b(?:intern(?:ship)?s?|co[ -]?op|placement student)\b|实习|實習|見習生", raw + " " + term):
        return "intern"
    if re.search(r"\b(?:graduate(?:s)?|campus (?:hir(?:e|ing)|recruit(?:ing|ment))|new grads?|early careers?|management trainee)\b|校招|校园招聘|校園招聘|應屆|应届|管培|毕业生计划|畢業生計劃", raw + " " + term):
        return "graduate"
    return "other"

def classify_region(location):
    value = _key(location)
    if not value:
        return "unknown"
    is_hk = bool(re.search(r"\bhong\s*kong\b|\bhksar\b|\bhk\b|香港|九龙|九龍|\bkowloon\b|新界", value))
    is_cn = bool(re.search(r"(?<!hong kong, )\b(?:mainland china|shenzhen|beijing|shanghai|guangzhou|hangzhou|chengdu|wuhan|nanjing|suzhou|xi'an|xian|zhuhai|dongguan|chongqing|xiamen|changsha|hefei|fuzhou|tianjin|qingdao|ningbo)\b|中国大陆|中國大陸|内地|內地|深圳|北京|上海|广州|廣州|杭州|成都|武汉|武漢|南京|苏州|蘇州|西安|珠海|东莞|東莞|重庆|重慶|厦门|廈門|长沙|長沙|合肥|福州|天津|青岛|青島|宁波|寧波", value))
    if is_hk and is_cn:
        return "both"
    if is_hk:
        return "hong_kong"
    if is_cn or value in {"china", "prc", "中国", "中國"}:
        return "mainland"
    return "other"

def _iso_deadline(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    match = re.fullmatch(r"(\d{4})[年/](\d{1,2})[月/](\d{1,2})日?", value)
    if not match:
        match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    try:
        if match:
            return date(*(int(part) for part in match.groups())).isoformat()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})", value):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return ""
    return ""

_DEADLINE_LABEL = r"(?:applications?\s+(?:deadline|closes?)|closing\s+date|apply\s+by|报名截止(?:时间|日期)?|申請截止(?:時間|日期)?|申请截止(?:时间|日期)?|投遞截止(?:時間|日期)?|投递截止(?:时间|日期)?|截止(?:时间|日期))"
_DATE_TOKEN = r"(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})|\d{4}[年/-]\d{1,2}[月/-]\d{1,2}日?)"
_ELIG_LABEL = r"(?:graduation\s+(?:window|date|year)|eligibility|毕业(?:时间|年份|要求)|畢業(?:時間|年份|要求))"
_START_LABEL = r"(?:start\s+date|availability|到岗(?:日期|时间)|到崗(?:日期|時間)|入職(?:日期|時間)|入职(?:日期|时间))"

def _extract(label, content):
    match = re.search(rf"(?:^|\n)[ \t]*(?:{label})[ \t]*[:：][ \t]*([^\n]+)", content, re.I)
    return _str(match.group(1), 240) if match else ""

def _deadline(row, content, metadata):
    for key in ("deadline", "application_deadline", "applicationDeadline", "closing_date", "closingDate"):
        if parsed := _iso_deadline(row.get(key)):
            return parsed
    for name, value in metadata:
        if re.fullmatch(_DEADLINE_LABEL, name, re.I):
            if parsed := _iso_deadline(value):
                return parsed
    match = re.search(rf"(?<![A-Za-z]){_DEADLINE_LABEL}[ \t]*(?:is[ \t]+|on[ \t]+|[:：＝][ \t]*)?({_DATE_TOKEN})(?!\d)", content, re.I)
    return _iso_deadline(match.group(1)) if match else ""

def _show_locations(*values):
    names = {}
    for value in values:
        for candidate in value if isinstance(value, (tuple, list)) else [value]:
            name = _str(candidate, 220)
            if name:
                names.setdefault(_key(name), name)
    return " / ".join(names.values())[:500]

def _required(value, label, limit):
    val = _str(value, limit)
    if not val:
        raise DiscoveryError(f"缺少{label}。")
    return val

_MARKETING_PARAMS = {
    "gh_src", "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "yclid", "mc_cid", "mc_eid",
}

def _canonical_manual_url(url):
    """Drop unambiguous ad tracking for identity only, leaving functional pairs untouched."""
    uri = urlsplit(url)
    query = []
    for segment in uri.query.split("&") if uri.query else []:
        key = unquote_plus(segment.partition("=")[0]).casefold()
        if key.startswith("utm_") or key in _MARKETING_PARAMS:
            continue
        query.append(segment)
    # _public_url has already restricted userinfo, port and hostname syntax.
    return uri._replace(netloc=uri.netloc.lower(), query="&".join(query), fragment="").geturl()

def manual_job(data: dict) -> dict:
    if not isinstance(data, Mapping):
        raise DiscoveryError("岗位格式错误。")
    company = _required(data.get("company"), "公司名称", 160)
    title = _required(data.get("title"), "岗位名称", 240)
    url = _public_url(data.get("url", ""))
    if not url:
        raise DiscoveryError("请提供完整的 HTTPS 岗位或官方招聘链接。")
    location = _str(data.get("location"), 500)
    requisition = _str(data.get("requisition"), 120)
    career_type = _str(data.get("career_type"), 20).lower() or classify_career(title)
    if career_type not in {"intern", "graduate", "other"}:
        raise DiscoveryError("岗位类型仅支持实习、校招或其他。")
    deadline = _iso_deadline(data.get("deadline"))
    if _str(data.get("deadline")) and not deadline:
        raise DiscoveryError("截止时间请用 YYYY-MM-DD；若包含时间，须注明时区偏移。")
    stable_url = _canonical_manual_url(url)
    identity = (_key(company), "page+id", stable_url, _key(requisition)) if requisition else (
        _key(company), "url+title", stable_url, _key(title), _key(location))
    stable = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:24]
    return {
        "source_id": "manual:" + stable, "company": company, "title": title,
        "location": location, "region": classify_region(location), "career_type": career_type,
        "url": url, "deadline": deadline, "active": True, "requisition": requisition,
        "description": _str(data.get("description"), 600),
        "eligibility": _str(data.get("eligibility"), 240),
        "start": _str(data.get("start"), 240),
    }

def _ashby_posting_url(value, board, *, allow_apply=False):
    url = _public_url(value, official_only=True)
    if not url:
        return "", ""
    parsed = urlsplit(url)
    parts = parsed.path.strip("/").split("/")
    if (parsed.hostname != "jobs.ashbyhq.com" or len(parts) < 2
            or parts[0].casefold() != board or not _JOB_ID.fullmatch(parts[1])):
        return "", ""
    if len(parts) != 2 and not (
        allow_apply and len(parts) == 3 and parts[2] in {"application", "apply"}
    ):
        return "", ""
    posting_id = parts[1].lower()
    if len(parts) == 2 and parts[1].casefold() in {"embed", "application", "apply"}:
        return "", ""
    clean = parsed._replace(path=f"/{parts[0]}/{parts[1]}", query="", fragment="").geturl()
    return posting_id, clean

def _ashby_address(location, addr):
    if not isinstance(addr, dict):
        addr = {}
    locality = _str(addr.get("addressLocality"))
    area = _str(addr.get("addressRegion"))
    country = _str(addr.get("addressCountry"))
    label = _str(location) or locality or area or country
    region = classify_region(label)
    if region in {"other", "unknown"}:
        region = {
            "hk": "hong_kong", "hong kong": "hong_kong", "hkg": "hong_kong", "hksar": "hong_kong",
            "cn": "mainland", "chn": "mainland", "china": "mainland", "prc": "mainland",
        }.get(_key(country), region)
    return label, region

def _ashby_normalize(source, row):
    if not isinstance(row, dict) or type(row.get("isListed")) is not bool:
        raise DiscoveryError("Ashby 岗位的公开状态字段缺失或异常，原记录未更新。")
    # Ashby explicitly says these should only be available via a direct link.
    if not row["isListed"]:
        return None
    primary_id, canonical = _ashby_posting_url(row.get("jobUrl"), source["board"])
    secondary_id, backup = _ashby_posting_url(row.get("applyUrl"), source["board"], allow_apply=True)
    if (row.get("jobUrl") and not primary_id) or (row.get("applyUrl") and not secondary_id):
        raise DiscoveryError("Ashby 岗位链接不属于已配置的招聘板，原记录未更新。")
    job_id = primary_id or secondary_id
    if not job_id or (primary_id and secondary_id and primary_id != secondary_id):
        raise DiscoveryError("Ashby 岗位缺少一致的公开编号，原记录未更新。")
    title = _required(row.get("title"), "岗位标题", 240)
    primary = row.get("address") or {}
    if not isinstance(primary, dict):
        raise DiscoveryError("Ashby 岗位的地址字段异常，原记录未更新。")
    locations = [_ashby_address(row.get("location"), primary.get("postalAddress"))]
    extras = row.get("secondaryLocations") or []
    if not isinstance(extras, list) or any(not isinstance(item, dict) for item in extras):
        raise DiscoveryError("Ashby 岗位的其他地点字段异常，原记录未更新。")
    locations.extend(_ashby_address(item.get("location"), item.get("address")) for item in extras)
    location = _show_locations([label for label, _ in locations])
    regions = {region for _, region in locations}
    if "both" in regions or {"hong_kong", "mainland"} <= regions:
        region = "both"
    else:
        region = next((key for key in ("hong_kong", "mainland", "other") if key in regions), "unknown")
    requisition = row.get("requisitionId") or row.get("requisition_id")
    if isinstance(requisition, int) and not isinstance(requisition, bool):
        requisition = str(requisition)
    content = _text(row.get("descriptionPlain")) or _text(row.get("descriptionHtml"))
    return {
        "source_id": f"ashby:{source['board']}:{job_id}",
        "company": source["company"], "title": title, "location": location,
        "region": region, "career_type": classify_career(title, row.get("employmentType")),
        "url": canonical or backup, "deadline": _deadline(row, content, []), "active": True,
        "requisition": _str(requisition, 120), "description": _str(content, 600),
        "eligibility": _extract(_ELIG_LABEL, content), "start": _extract(_START_LABEL, content),
    }

def _smartrecruiters_posting_id(row):
    if not isinstance(row, dict):
        raise DiscoveryError("SmartRecruiters 返回了异常岗位条目，原记录未更新。")
    posting_id = row.get("id")
    if isinstance(posting_id, int) and not isinstance(posting_id, bool):
        posting_id = str(posting_id)
    if posting_id in (None, ""):
        posting_id = row.get("uuid")
    if not isinstance(posting_id, str) or not _JOB_ID.fullmatch(posting_id):
        raise DiscoveryError("SmartRecruiters 缺少有效岗位编号，原记录未更新。")
    return posting_id.lower()

def _smartrecruiters_posting_url(row, source):
    # Job detail links are not guaranteed in list responses. Never guess the
    # job URL slug or issue N+1 detail fetches merely to supply a link.
    for key in ("postingUrl", "applyUrl"):
        url = _public_url(row.get(key))
        if not url:
            continue
        parsed = urlsplit(url)
        parts = parsed.path.strip("/").split("/")
        if (parsed.hostname in {"jobs.smartrecruiters.com", "www.smartrecruiters.com"}
                and len(parts) == 2 and parts[0].casefold() == source["board"]
                and _JOB_ID.fullmatch(parts[1])):
            return parsed._replace(query="", fragment="").geturl()
    return board_url(source)

def _smartrecruiters_normalize(source, row):
    posting_id = _smartrecruiters_posting_id(row)
    company = row.get("company") or {}
    if not isinstance(company, dict) or (company.get("identifier") and
            _key(company.get("identifier")) != source["board"]):
        raise DiscoveryError("SmartRecruiters 岗位不属于已配置的公司，原记录未更新。")
    title = _required(row.get("name"), "岗位标题", 240)
    loc = row.get("location") or {}
    if not isinstance(loc, dict):
        raise DiscoveryError("SmartRecruiters 岗位地点格式异常，原记录未更新。")
    location = _show_locations(loc.get("city"), loc.get("region"), loc.get("country"))
    _, region = _ashby_address(location, {"addressCountry": loc.get("country")})
    employment = row.get("typeOfEmployment") or {}
    if not isinstance(employment, dict):
        raise DiscoveryError("SmartRecruiters 用工类型字段异常，原记录未更新。")
    experience = row.get("experienceLevel") or {}
    if not isinstance(experience, dict):
        raise DiscoveryError("SmartRecruiters 经验字段异常，原记录未更新。")
    cues = " ".join(_str(item).replace("_", " ") for item in (
        employment.get("label"), employment.get("id"), experience.get("label"), experience.get("id")
    ))
    custom = row.get("customField") or []
    if isinstance(custom, dict):
        custom = [custom]
    metadata = [
        (_str(item.get("fieldLabel")), _str(item.get("valueLabel")))
        for item in custom if isinstance(item, dict)
    ] if isinstance(custom, list) else []
    content = _text(row.get("description"))
    job_ad = row.get("jobAd")
    sections = job_ad.get("sections") if isinstance(job_ad, dict) else None
    if isinstance(sections, dict):
        content += "\n" + "\n".join(
            _text(sections.get(key, {}).get("text")) for key in ("jobDescription", "qualifications", "additionalInformation")
            if isinstance(sections.get(key), dict)
        )
    requisition = row.get("refNumber")
    if isinstance(requisition, int) and not isinstance(requisition, bool):
        requisition = str(requisition)
    return {
        "source_id": f"smartrecruiters:{source['board']}:{posting_id}",
        "company": source["company"], "title": title, "location": location,
        "region": region, "career_type": classify_career(title, cues),
        "url": _smartrecruiters_posting_url(row, source),
        "deadline": _deadline(row, content, metadata), "active": True,
        "requisition": _str(requisition, 120), "description": _str(content, 600),
        "eligibility": next((val for label, val in metadata if re.fullmatch(_ELIG_LABEL, label, re.I)), "") or _extract(_ELIG_LABEL, content),
        "start": next((val for label, val in metadata if re.fullmatch(_START_LABEL, label, re.I)), "") or _extract(_START_LABEL, content),
    }

def _smartrecruiters_snapshot(base, source, page):
    endpoint = f"{base}/v1/companies/{source['board']}/postings"
    rows = []
    seen = set()
    expected = None
    while True:
        offset = len(rows)
        query = urlencode({"destination": "PUBLIC", "limit": SMARTRECRUITERS_PAGE_SIZE, "offset": offset})
        data = page(f"{endpoint}?{query}")
        if not isinstance(data, dict) or not isinstance(data.get("content"), list):
            raise DiscoveryError("SmartRecruiters 返回格式异常，原记录未更新。")
        limit, total, actual = data.get("limit"), data.get("totalFound"), data.get("offset")
        if (type(limit) is not int or not 1 <= limit <= SMARTRECRUITERS_PAGE_SIZE
                or type(total) is not int or not 0 <= total <= MAX_ROWS
                or type(actual) is not int or actual != offset):
            raise DiscoveryError("SmartRecruiters 返回分页信息异常或岗位过多，原记录未更新。")
        if expected is None:
            expected = total
        if total != expected:
            raise DiscoveryError("SmartRecruiters 招聘板在检查中发生变化，请稍后重试。")
        items = data["content"]
        if len(items) > min(limit, total - offset) or (not items and offset < total):
            raise DiscoveryError("SmartRecruiters 返回不完整快照，原记录未更新。")
        for row in items:
            key = _smartrecruiters_posting_id(row)
            if key in seen:
                raise DiscoveryError("SmartRecruiters 分页中出现重复岗位，原记录未更新。")
            seen.add(key)
        rows.extend(items)
        if len(rows) == total:
            return rows

def _normalize(source, row):
    if not isinstance(row, dict):
        raise DiscoveryError("招聘板返回了异常岗位条目，未更新原记录。")
    job_id = row.get("id")
    if isinstance(job_id, int) and not isinstance(job_id, bool):
        job_id = str(job_id)
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise DiscoveryError("招聘板缺少有效岗位编号，未更新原记录。")
    provider = source["provider"]
    if provider.startswith("greenhouse"):
        title = _required(row.get("title"), "岗位标题", 240)
        location_data = row.get("location") or {}
        if not isinstance(location_data, dict):
            raise DiscoveryError("招聘板岗位地点格式异常，未更新原记录。")
        offices = row.get("offices") or []
        if not isinstance(offices, list):
            raise DiscoveryError("招聘板办公室字段异常，未更新原记录。")
        location = _show_locations(location_data.get("name"), [
            office.get("location") or office.get("name") for office in offices if isinstance(office, dict)
        ])
        requisition = row.get("requisition_id")
        url = _public_url(row.get("absolute_url")) or f"{board_url(source)}/jobs/{job_id}"
        content = _text(row.get("content"))
        props = row.get("metadata")
        metadata = [
            (_str(item.get("name")), _str(item.get("value"))) for item in props if isinstance(item, dict)
        ] if isinstance(props, list) else []
        commitment = next((val for label, val in metadata if _key(label) in {"employment type", "commitment", "职位类型", "職位類型"}), "")
    else:
        title = _required(row.get("text"), "岗位标题", 240)
        categories = row.get("categories") or {}
        if not isinstance(categories, dict):
            raise DiscoveryError("招聘板岗位分类格式异常，未更新原记录。")
        location = _show_locations(categories.get("location"), categories.get("allLocations") or [])
        requisition = row.get("requisition_id") or row.get("requisitionId")
        url = _public_url(row.get("hostedUrl"), official_only=True) or f"{board_url(source)}/{job_id}"
        content = "\n".join(_text(row.get(p)) for p in ("descriptionPlain", "additionalPlain"))
        if not content.strip():
            content = "\n".join(_text(row.get(p)) for p in ("description", "additional"))
        lists = row.get("lists")
        if isinstance(lists, list):
            content += "\n" + "\n".join(
                "\n".join((_str(part.get("text")), _text(part.get("content"))))
                for part in lists[:40] if isinstance(part, dict)
            )
        metadata = []
        commitment = categories.get("commitment")
    if isinstance(requisition, int) and not isinstance(requisition, bool):
        requisition = str(requisition)
    deadline = _deadline(row, content, metadata)
    region = classify_region(location)
    if provider.startswith("lever") and region in {"other", "unknown"}:
        region = {"hk": "hong_kong", "cn": "mainland"}.get(_key(row.get("country")), region)
    eligibility = next((val for label, val in metadata if re.fullmatch(_ELIG_LABEL, label, re.I)), "") or _extract(_ELIG_LABEL, content)
    start = next((val for label, val in metadata if re.fullmatch(_START_LABEL, label, re.I)), "") or _extract(_START_LABEL, content)
    return {
        "source_id": f"{provider}:{source['board']}:{job_id}",
        "company": source["company"], "title": title, "location": location,
        "region": region, "career_type": classify_career(title, commitment),
        "url": url, "deadline": deadline, "active": True,
        "requisition": _str(requisition, 120), "description": _str(content, 600),
        "eligibility": eligibility, "start": start,
    }

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # No redirect target is fetched, including cross-domain redirects.
        raise HTTPError(req.full_url, code, msg, headers, fp)

def _read_json(url, timeout):
    endpoint = urlsplit(url)
    if endpoint.scheme != "https" or endpoint.netloc not in set(_API_HOSTS.values()):
        raise DiscoveryError("来源不是支持的 ATS 公共 API。")
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "JobWorkbench/1.1"})
    end = time.monotonic() + timeout
    try:
        with build_opener(_NoRedirect()).open(req, timeout=timeout) as response:
            mime = response.headers.get_content_type()
            if mime != "application/json" and not mime.endswith("+json"):
                raise DiscoveryError("招聘板未返回 JSON，原记录未更新。")
            chunks = bytearray()
            # read1 keeps the total elapsed-time check meaningful for slow servers.
            read_chunk = getattr(response, "read1", response.read)
            while len(chunks) <= MAX_BYTES:
                if time.monotonic() > end:
                    raise DiscoveryError("招聘板响应超时，原记录未更新。")
                chunk = read_chunk(min(65536, MAX_BYTES + 1 - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
            if len(chunks) > MAX_BYTES:
                raise DiscoveryError("招聘板返回的数据过大，原记录未更新。")
            return json.loads(chunks)
    except HTTPError as exc:
        exc.close()
        if exc.code == 404:
            raise DiscoveryError("招聘板不存在或未通过公共 API 发布（HTTP 404）。请核对代号。") from exc
        if exc.code == 429:
            raise DiscoveryError("招聘平台限流（HTTP 429）。请延后再检查。") from exc
        if 300 <= exc.code < 400:
            raise DiscoveryError(f"招聘板返回了重定向（HTTP {exc.code}），未自动跟随。") from exc
        raise DiscoveryError(f"招聘板访问失败（HTTP {exc.code}），原记录未更新。") from exc
    except (URLError, OSError, TimeoutError, socket.timeout) as exc:
        raise DiscoveryError("暂时无法连接招聘平台的公共 API，原记录未更新。") from exc
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, DiscoveryError):
            raise
        raise DiscoveryError("招聘板返回数据异常，原记录未更新。") from exc

def fetch_jobs(source, *, timeout=30, transport=None):
    """Fetch a complete published snapshot. transport(url, timeout) may inject fixture JSON."""
    source = validate_source(source)
    provider = source["provider"]
    if provider == "demo":
        return demo_jobs(source)
    read = transport or _read_json
    try:
        timeout = min(max(float(timeout), 0.2), 60.0)
        ends = time.monotonic() + timeout
        def page(url):
            remaining = ends - time.monotonic()
            if remaining <= 0:
                raise DiscoveryError("招聘板检查超时，原记录未更新。")
            return read(url, remaining)

        base = f"https://{_API_HOSTS[provider]}"
        rows = []
        if provider.startswith("greenhouse"):
            data = page(f"{base}/v1/boards/{source['board']}/jobs?content=true")
            if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
                raise DiscoveryError("Greenhouse 返回格式异常，原记录未更新。")
            rows = data["jobs"]
            meta = data.get("meta")
            expected = meta.get("total") if isinstance(meta, dict) else None
            if expected is not None and (type(expected) is not int or expected != len(rows)):
                raise DiscoveryError("Greenhouse 返回了不完整的招聘板，原记录未更新。")
        elif provider == "ashby":
            data = page(f"{base}/posting-api/job-board/{source['board']}")
            if not isinstance(data, dict) or data.get("apiVersion") != "1" or not isinstance(data.get("jobs"), list):
                raise DiscoveryError("Ashby 返回格式或版本异常，原记录未更新。")
            rows = data["jobs"]
        elif provider == "smartrecruiters":
            rows = _smartrecruiters_snapshot(base, source, page)
        else:
            endpoint = f"{base}/v0/postings/{source['board']}"
            seen = set()
            while True:
                params = urlencode({"mode": "json", "skip": len(rows), "limit": LEVER_PAGE_SIZE})
                items = page(f"{endpoint}?{params}")
                if not isinstance(items, list) or len(items) > LEVER_PAGE_SIZE:
                    raise DiscoveryError("Lever 返回格式或分页异常，原记录未更新。")
                for row in items:
                    key = row.get("id") if isinstance(row, dict) else None
                    if not isinstance(key, str) or key in seen:
                        raise DiscoveryError("Lever 分页中出现异常或重复条目，原记录未更新。")
                    seen.add(key)
                rows.extend(items)
                if len(rows) > MAX_ROWS:
                    raise DiscoveryError("招聘板条目过多，原记录未更新。")
                if not items:
                    break
        if len(rows) > MAX_ROWS:
            raise DiscoveryError("招聘板条目过多，原记录未更新。")
        normalize = {"ashby": _ashby_normalize, "smartrecruiters": _smartrecruiters_normalize}.get(provider, _normalize)
        normalized = [item for row in rows if (item := normalize(source, row)) is not None]
        if len({row["source_id"] for row in normalized}) != len(normalized):
            raise DiscoveryError("招聘板返回重复岗位编号，原记录未更新。")
        return normalized
    except DiscoveryError:
        raise
    except (OSError, TimeoutError, ValueError, TypeError, RecursionError) as exc:
        raise DiscoveryError("招聘板响应无法解析，原记录未更新。") from exc

def detect_changes(previous, current, *, initialized):
    """Return new/reopened/closed rows plus the merged snapshot. Call only on full fetch."""
    old = {row["source_id"]: row for row in previous}
    result = {"jobs": [], "new": [], "reopened": [], "closed": [], "baseline": not initialized}
    fresh = set()
    for row in current:
        key = row["source_id"]
        if key in fresh:
            raise DiscoveryError("当前快照有重复岗位编号。")
        fresh.add(key)
        item = {**row, "active": True}
        result["jobs"].append(item)
        if not initialized:
            continue
        if key not in old:
            result["new"].append(item)
        elif not old[key].get("active", True):
            result["reopened"].append(item)
    if initialized:
        for key, row in old.items():
            if key not in fresh:
                item = {**row, "active": False}
                result["jobs"].append(item)
                if row.get("active", True):
                    result["closed"].append(item)
    return result

def demo_jobs(source, phase=0):
    """Deterministic public-data-free fixtures: baseline, changed, reopened."""
    source = validate_source(source)
    rows = {
        "qa-01": ("软件测试实习生", "香港", "QA-01"),
        "ai-02": ("AI 应用工程师（校招）", "深圳", "AI-02"),
        "agent-03": ("Agent 应用开发实习生", "Hong Kong", "AGENT-03"),
    }
    ids = {0: ["qa-01", "ai-02"], 1: ["ai-02", "agent-03"], 2: ["qa-01", "ai-02", "agent-03"]}.get(phase)
    if source["provider"] != "demo" or ids is None:
        raise DiscoveryError("演示来源或阶段无效。")
    return [{
        "source_id": f"demo:{source['board']}:{job_id}",
        "company": source["company"], "title": rows[job_id][0], "location": rows[job_id][1],
        "region": classify_region(rows[job_id][1]), "career_type": classify_career(rows[job_id][0]),
        "url": "", "deadline": "", "active": True, "requisition": rows[job_id][2],
        "description": "离线模拟岗位，仅用于演示流程。",
        "eligibility": "在读硕士可申请" if job_id == "agent-03" else "",
        "start": "",
    } for job_id in ids]
