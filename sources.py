"""Read current opportunities from the radar's public sources."""

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import unescape
from html.parser import HTMLParser
import json
import re
import subprocess
import unicodedata
from urllib.parse import urlencode, urljoin, urlsplit


BOGOTA = timezone(timedelta(hours=-5))
SECOP_HOME = "https://www.datos.gov.co/Gastos-Gubernamentales/SECOP-II-Procesos-de-Contrataci-n/p6dx-8zbt"
SECOP_API = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
INEXMODA_HOME = "https://inexmoda.org.co/"
HIMALAYAS_HOME = "https://himalayas.app/"
REFORMATION_HOME = "https://job-boards.greenhouse.io/reformation"
REFORMATION_API = "https://api.greenhouse.io/v1/boards/reformation/jobs"
MULBERRY_HOME = "https://jobs.lever.co/mulberry"
MULBERRY_API = "https://api.lever.co/v0/postings/mulberry"


def fetch_json(url, params=None):
    if params:
        url += "?" + urlencode(params)
    result = subprocess.run(
        [
            "curl", "--fail", "--silent", "--show-error", "--location",
            "--compressed", "--proto", "=https", "--proto-redir", "=https",
            "--connect-timeout", "7", "--max-time", "20",
            "--header", "Accept: application/json", "--url", url,
        ],
        capture_output=True,
        timeout=22,
    )
    if result.returncode:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(error or f"Error de consulta ({result.returncode})")
    return json.loads(result.stdout)


def _records(payload):
    if not isinstance(payload, list) or any(not isinstance(record, dict) for record in payload):
        raise ValueError("La fuente devolvió un listado con formato inesperado")
    return payload


def _iso_date(value, default_zone=timezone.utc):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=default_zone)


def _unix_date(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _iso(value):
    return value.isoformat(timespec="seconds") if value else None


def _https(value):
    if not isinstance(value, str) or value != value.strip():
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    return None


def _fold(value):
    return "".join(
        letter for letter in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(letter)
    )


class _Content(HTMLParser):
    def __init__(self, value):
        super().__init__()
        self.parts = []
        self.links = []
        self.active_link = None
        self.ignored = None
        self.feed(value)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored = tag
        if tag == "a":
            self.active_link = (dict(attrs).get("href") or "", [])

    def handle_endtag(self, tag):
        if tag == self.ignored:
            self.ignored = None
        if tag == "a" and self.active_link:
            url, parts = self.active_link
            self.links.append((url, " ".join(parts)))
            self.active_link = None

    def handle_data(self, data):
        if self.ignored:
            return
        self.parts.append(data)
        if self.active_link:
            self.active_link[1].append(data)

    @property
    def text(self):
        return " ".join(" ".join(self.parts).split())


def _plain(value):
    return _Content(unescape(value)).text if isinstance(value, str) else ""


def _amount(value):
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    if amount.is_finite() and amount > 0:
        return f"{amount:,.2f}".rstrip("0").rstrip(".").translate(str.maketrans(",.", ".,"))
    return None


SECOP_PHASES = (
    "Presentación de oferta", "Fase de Selección (Presentación de ofertas)",
    "Fase de ofertas", "Proceso de ofertas",
)
SECOP_TERMS = (
    "alta costura", "patronaje", "sastrería", "sastreria", "modistería",
    "modisteria", "vestuario", "confección", "confeccion", "industria de la moda",
    "diseño de moda", "diseño de prendas", "colección de moda", "moldería",
)
SECOP_EXCLUSIONS = re.compile(
    r"\b(?:uniformes?|dotaci(?:on|ones) (?:de (?:ropa|vestuario|calzado)|"
    r"(?:para |de )?(?:funcionarios|empleados|servidores))|"
    r"(?:bonos|valeras) canjeables)\b"
)


def secop(now):
    cutoff = now.astimezone(BOGOTA).replace(tzinfo=None).isoformat(timespec="seconds")
    phases = ", ".join(f"'{phase}'" for phase in SECOP_PHASES)
    keyword_filter = " OR ".join(
        f"lower({field}) like '%{term}%'"
        for term in SECOP_TERMS
        for field in ("nombre_del_procedimiento", "descripci_n_del_procedimiento")
    )
    rows = _records(fetch_json(SECOP_API, {
        "$where": (
            f"fecha_de_recepcion_de > '{cutoff}' "
            "AND estado_del_procedimiento = 'Publicado' "
            "AND estado_de_apertura_del_proceso = 'Abierto' AND adjudicado = 'No' "
            f"AND estado_resumen in ({phases}) AND ({keyword_filter})"
        ),
        "$select": (
            "id_del_proceso,nombre_del_procedimiento,descripci_n_del_procedimiento,"
            "fecha_de_recepcion_de,fecha_de_publicacion_del,estado_del_procedimiento,"
            "estado_de_apertura_del_proceso,estado_resumen,adjudicado,entidad,"
            "ciudad_entidad,departamento_entidad,precio_base,urlproceso"
        ),
        "$order": "fecha_de_recepcion_de ASC,id_del_proceso ASC",
        "$limit": 150,
    }))
    opportunities = []
    for row in rows:
        deadline = _iso_date(row.get("fecha_de_recepcion_de"), BOGOTA)
        if (
            not deadline or deadline <= now or row.get("estado_resumen") not in SECOP_PHASES
            or row.get("estado_del_procedimiento") != "Publicado"
            or row.get("estado_de_apertura_del_proceso") != "Abierto"
            or row.get("adjudicado") != "No"
        ):
            continue
        title = _plain(row.get("nombre_del_procedimiento"))
        description = _plain(row.get("descripci_n_del_procedimiento"))
        if SECOP_EXCLUSIONS.search(_fold(f"{title} {description}")):
            continue
        url = _https((row.get("urlproceso") or {}).get("url"))
        external_id = row.get("id_del_proceso")
        organization = _plain(row.get("entidad"))
        if not all((url, external_id, title, organization)):
            continue
        price = _amount(row.get("precio_base"))
        locations = (_plain(row.get("ciudad_entidad")), _plain(row.get("departamento_entidad")))
        location = next((name for name in locations if name and name != "No Definido"), "Colombia")
        opportunities.append({
            "id": f"secop:{external_id}",
            "title": title,
            "organization": organization,
            "type": "consultoria" if "consultoria" in _fold(title) else "proyecto",
            "modality": "sin-confirmar",
            "location": location,
            "section": "colombia",
            "deadline": _iso(deadline),
            "publishedAt": _iso(_iso_date(row.get("fecha_de_publicacion_del"), BOGOTA)),
            "compensation": f"Presupuesto base COP {price}" if price else None,
            "url": url,
            "sourceUrl": url,
            "description": description,
            "clearApplication": True,
        })
    return opportunities


MONTHS = (
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre"
).split()
CALL_DATE = re.compile(
    r"\b(?:"
    r"(?:inscripciones|postulaciones|convocatoria abierta|recepcion de propuestas)"
    r"\s+(?:(?:abiertas?|estaran abiertas?)\s+)?hasta(?:\s+el)?|"
    r"(?:fecha\s+(?:limite|de cierre)|cierre(?:\s+de\s+(?:la convocatoria|inscripciones|postulaciones))?)\s*:?"
    r")\s*(\d{1,2})\s+de\s+(" + "|".join(MONTHS) + r")\s+de(?:l)?\s+(20\d{2})\b"
)
CALL_CLOSED = re.compile(
    r"\b(?:convocatoria|inscripciones|postulaciones)\s+(?:(?:ya\s+)?(?:se encuentra|esta[n]?)\s+)?cerrad[ao]s?\b"
)
CALL_OPEN = re.compile(
    r"\b(?:convocatoria abierta|abre (?:la |una )?convocatoria|"
    r"inscripciones (?:abiertas|hasta)|postulaciones (?:abiertas|hasta))\b"
)
APPLY = re.compile(
    r"\b(?:postulat[ei]|aplica(?:r|\s+aqui)?|inscribet[ei]|inscribirse|"
    r"registrate|(?:formulario|enlace) de (?:inscripcion|postulacion))\b"
)


def _call_deadline(value):
    dates = set()
    for day, month, year in CALL_DATE.findall(value):
        try:
            dates.add(datetime(int(year), MONTHS.index(month) + 1, int(day), tzinfo=BOGOTA).date())
        except ValueError:
            continue
    if len(dates) == 1:
        return datetime.combine(dates.pop(), time.max, BOGOTA)
    return None


def inexmoda(now):
    rows = _records(fetch_json(INEXMODA_HOME + "wp-json/wp/v2/posts", {
        "search": "convocatoria",
        "per_page": 25,
        "after": (now.astimezone(BOGOTA) - timedelta(days=180)).replace(tzinfo=None).isoformat(timespec="seconds"),
        "_fields": "id,title,content,date_gmt,link",
    }))
    opportunities = []
    for row in rows:
        source_url = _https(row.get("link"))
        title = _plain((row.get("title") or {}).get("rendered"))
        published = _iso_date(row.get("date_gmt"))
        external_id = row.get("id")
        if not all((source_url, title, published, external_id)) or published > now:
            continue
        content = _Content((row.get("content") or {}).get("rendered") or "")
        article = _fold(f"{title} {content.text}")
        deadline = _call_deadline(article)
        if not deadline or deadline <= now or CALL_CLOSED.search(article) or not CALL_OPEN.search(article):
            continue
        application = None
        for href, label in content.links:
            if not href or href.startswith("#") or not APPLY.search(_fold(label)):
                continue
            application = _https(urljoin(source_url, href))
            if application and application.rstrip("/") != source_url.rstrip("/"):
                break
            application = None
        if not application:
            continue
        opportunities.append({
            "id": f"inexmoda:{external_id}",
            "title": title,
            "organization": "Inexmoda",
            "type": "proyecto",
            "modality": "sin-confirmar",
            "location": "Colombia",
            "section": "colombia",
            "deadline": _iso(deadline),
            "publishedAt": _iso(published),
            "compensation": None,
            "url": application,
            "sourceUrl": source_url,
            "description": content.text,
            "clearApplication": True,
        })
    return opportunities


SALARY_PERIODS = {
    "hourly": "por hora", "weekly": "por semana", "fortnightly": "por quincena",
    "monthly": "por mes", "annual": "por año",
}


def _himalayas_salary(job):
    lower = _amount(job.get("minSalary"))
    upper = _amount(job.get("maxSalary"))
    currency = job.get("currency") or ""
    if not re.fullmatch(r"[A-Z]{3}", currency) or not (lower or upper):
        return None
    amount = f"{lower}–{upper}" if lower and upper and lower != upper else lower or upper
    period = SALARY_PERIODS.get(job.get("salaryPeriod") or "annual", "")
    return f"{currency} {amount} {period}".strip()


def _includes_colombia(countries):
    for country in countries:
        if isinstance(country, dict) and country.get("alpha2") == "CO":
            return True
        if isinstance(country, str) and _fold(country.strip()) in {"co", "colombia"}:
            return True
    return False


def himalayas(now):
    opportunities = {}
    for keyword in ("couture", "fashion", "patternmaking", "garment", "apparel"):
        payload = fetch_json(HIMALAYAS_HOME + "jobs/api/search", {"q": keyword, "country": "CO"})
        for job in _records(payload["jobs"]):
            deadline = _unix_date(job.get("expiryDate"))
            if not deadline or deadline <= now:
                continue
            countries = job.get("locationRestrictions")
            offsets = job.get("timezoneRestrictions")
            if not isinstance(countries, list) or not isinstance(offsets, list):
                continue
            if countries and not _includes_colombia(countries):
                continue
            if offsets and not any(str(offset) in {"-5", "-5.0", "UTC-5", "UTC-05:00", "UTC-5:00"} for offset in offsets):
                continue
            application = _https(job.get("applicationLink"))
            source_url = _https(job.get("guid"))
            organization = _plain(job.get("companyName"))
            title = _plain(job.get("title"))
            if not all((application, source_url, organization, title)):
                continue
            source_path = urlsplit(source_url)
            if source_path.hostname != "himalayas.app" or not re.fullmatch(r"/companies/[^/]+/jobs/[^/]+/?", source_path.path):
                continue
            external_id = source_path.path.removeprefix("/companies/").rstrip("/")
            if job.get("employmentType") == "Volunteer":
                continue
            opportunities[external_id] = {
                "id": f"himalayas:{external_id}",
                "title": title,
                "organization": organization,
                "type": "consultoria" if job.get("employmentType") == "Contractor" else "empleo",
                "modality": "remoto",
                "location": "Remoto · admite postulaciones desde Colombia",
                "section": "colombia",
                "deadline": _iso(deadline),
                "publishedAt": _iso(_unix_date(job.get("pubDate"))),
                "compensation": _himalayas_salary(job),
                "url": application,
                "sourceUrl": source_url,
                "description": _plain(job.get("description") or job.get("excerpt")),
                "clearApplication": True,
            }
    return list(opportunities.values())


REFORMATION_ROLES = re.compile(
    r"\b(?:design(?:er)?|production|product development|pattern\s*mak\w*|"
    r"sewing|tailor\w*|garment\w*|atelier|fabric|quality assurance|technical fit|"
    r"alterations?|sample maker|draping)\b", re.I,
)
REFORMATION_EXCLUSIONS = re.compile(
    r"\b(?:general (?:\w+ )?applications?|future opportunities|retail|store|sales|"
    r"operations associate|template|graphic design\w*|brand design\w*|web design\w*|digital design\w*|"
    r"ux design\w*|ui design\w*)\b", re.I,
)
REFORMATION_SALARY = re.compile(
    r"\b(?:base salary|salary|pay|compensation)(?: range)?\s*(?:is|:)?\s*"
    r"(\$[\d,]+(?:\.\d{2})?)(/hr| per hour)?"
    r"(?:\s*(?:[-–—]|to)\s*(\$[\d,]+(?:\.\d{2})?)(/hr| per hour)?)?",
    re.I,
)


def _reformation_salary(description):
    match = REFORMATION_SALARY.search(description)
    if not match:
        return None
    lower, lower_hourly, upper, upper_hourly = match.groups()
    amount = f"{lower}–{upper}" if upper else lower
    return f"{amount} por hora" if lower_hourly or upper_hourly else amount


def reformation(now):
    opportunities = []
    for job in _records(fetch_json(REFORMATION_API)["jobs"]):
        title = _plain(job.get("title"))
        external_id = job.get("id")
        deadline = _iso_date(job.get("application_deadline"))
        if (
            not isinstance(external_id, int) or not job.get("internal_job_id")
            or not REFORMATION_ROLES.search(title) or REFORMATION_EXCLUSIONS.search(title)
            or (deadline and deadline <= now)
        ):
            continue
        detail = fetch_json(f"{REFORMATION_API}/{external_id}")
        deadline = _iso_date(detail.get("application_deadline")) or deadline
        if deadline and deadline <= now:
            continue
        url = _https(detail.get("absolute_url") or job.get("absolute_url"))
        description = _plain(detail.get("content"))
        location = _plain((detail.get("location") or job.get("location") or {}).get("name"))
        if not url or not location or not description:
            continue
        if re.search(r"\bhybrid\b", f"{location} {description}", re.I):
            modality = "hibrido"
        elif re.search(r"\b(?:on-site|onsite|in-office|in-person)\b", description, re.I):
            modality = "presencial"
        else:
            modality = "sin-confirmar"
        opportunities.append({
            "id": f"reformation:{external_id}",
            "title": title,
            "organization": "Reformation",
            "type": "empleo",
            "modality": modality,
            "location": location,
            "section": "internacional",
            "deadline": _iso(deadline),
            "publishedAt": _iso(_iso_date(detail.get("first_published") or job.get("first_published"))),
            "compensation": _reformation_salary(description),
            "url": url,
            "sourceUrl": url,
            "description": description,
            "clearApplication": True,
        })
    return opportunities


def mulberry(now):
    opportunities = []
    for job in _records(fetch_json(MULBERRY_API, {"mode": "json"})):
        categories = job.get("categories") or {}
        if categories.get("team") != "Ready-to-Wear":
            continue
        title = _plain(job.get("text"))
        location = _plain(categories.get("location"))
        application = _https(job.get("applyUrl"))
        source_url = _https(job.get("hostedUrl"))
        external_id = job.get("id")
        modality = {"on-site": "presencial", "hybrid": "hibrido"}.get(job.get("workplaceType"))
        if not all((title, location, application, source_url, external_id, modality)):
            continue
        created_ms = job.get("createdAt")
        created = _unix_date(created_ms / 1000) if isinstance(created_ms, (int, float)) else None
        description = " ".join(
            _plain(job.get(field)) for field in ("description", "additional")
        )
        opportunities.append({
            "id": f"mulberry:{external_id}",
            "title": title,
            "organization": "Mulberry",
            "type": "empleo",
            "modality": modality,
            "location": location,
            "section": "internacional",
            "deadline": None,
            "publishedAt": _iso(created),
            "compensation": _plain(job.get("salaryDescriptionPlain")) or None,
            "url": application,
            "sourceUrl": source_url,
            "description": f"{categories['team']} {description}",
            "clearApplication": True,
        })
    return opportunities


SOURCES = {
    "secop": ("SECOP II", SECOP_HOME, secop),
    "inexmoda": ("Inexmoda", INEXMODA_HOME, inexmoda),
    "himalayas": ("Himalayas", HIMALAYAS_HOME, himalayas),
    "reformation": ("Reformation", REFORMATION_HOME, reformation),
    "mulberry": ("Mulberry", MULBERRY_HOME, mulberry),
}
