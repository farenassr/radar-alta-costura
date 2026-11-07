import argparse
import json
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit


DIRECT = re.compile(
    r"\b(?:alta costura|haute couture|couture|confeccion a medida|sastreria a medida|"
    r"vestid[oa]s? a medida|bespoke (?:tailoring|garments?|dress(?:es)?)|made.to.measure|sur mesure)\b"
)
SPECIALTY = re.compile(
    r"\b(?:patron(?:ista|aje|niste|nage)|modeliste|patternmak(?:er|ing)|pattern maker|"
    r"couturiere?|tailleur|dressmak(?:er|ing)|premiere main|bordad\w*|broderie|embroidery|"
    r"confeccion\w*|garment construction|moda de autor|bridal(?:wear)?|vestidos? de novia|"
    r"robe de mariee|technical design(?:er)?|diseno tecnico|direction artistique|"
    r"direccion creativa|creative director|taller(?:es)? de (?:moda|confeccion)|"
    r"fashion design(?:er)?|diseno de moda|designer de mode|textile design(?:er)?|"
    r"diseno textil|(?:rtw|knitwear|apparel) designer|designer rtw|garment manufactur\w*)\b"
)
CRAFT = re.compile(
    r"\b(?:patron(?:ista|aje|niste|nage)|modeliste|pattern[ -]?mak(?:er|ing)|"
    r"couturiere?|modista|dressmak(?:er|ing)|premiere main|moda de autor|"
    r"bridalwear|vestidos? de novia|robe de mariee)\b"
)
FASHION = re.compile(
    r"\b(?:moda|fashion|mode|apparel|garments?|prendas?|collections? de mode|"
    r"textil(?:es|e)?|vestuar\w*|vestidos?|vetements?|pret.a.porter|ready.to.wear|bridal(?:wear)?)\b"
)
ROLE = re.compile(
    r"\b(?:disen\w*|design\w*|consult\w*|asesor\w*|strateg\w*|estrateg\w*|produccion|"
    r"production|coleccion\w*|collection\w*|sourcing|merchandis\w*|producto|product development|"
    r"negocio\w*|business development|direction|marketing|convocatoria|atelier|taller\w*)\b"
)
IRRELEVANT_TITLE = re.compile(
    r"\b(?:sales associate|store manager|cashier|retail associate|vendedor\w*|cajer\w*|"
    r"conseiller de vente|compra de uniformes|adquisicion de (?:uniformes|dotacion)|"
    r"dotacion de uniformes|software (?:engineer|developer)|developpeur logiciel|"
    r"software development|general (?:design )?application)\b"
)
FEE = re.compile(
    r"(?<!no )(?<!never )\b(?:debes? pagar|debera[n]? pagar|requier[eoa] (?:el )?pago de|must pay)\b"
    r".{0,40}\b(?:inscripcion|postulacion|application|registration|candidature|cuota)\b"
    r"|\b(?:mandatory|non.refundable) (?:application|registration) fee\b"
    r"|\b(?:cuota|tarifa|pago) (?:de )?(?:inscripcion|postulacion) obligatori[oa]\b"
    r"|\bfrais de candidature obligatoires\b"
    r"|\b(?:inscripcion|postulacion) tiene un costo de\s*(?:[$€]|(?:cop|usd|eur)\s*)[1-9]"
    r"|\brequiere (?:una? )?(?:cuota|tarifa) de (?:inscripcion|postulacion)\b"
    r"|\b(?:application|registration) fee (?:is|of)\s*(?:[$€]|(?:cop|usd|eur)\s*)[1-9]"
    r"|\bpay (?:an? |the )?(?:[$€]|(?:cop|usd|eur)\s*)[1-9][\d,.]* (?:application|registration) fee\b"
)
KEEP_PENDING = timedelta(hours=48)
PUBLIC_FIELDS = (
    "id", "title", "organization", "type", "modality", "location", "section",
    "deadline", "publishedAt", "compensation", "url", "sourceUrl",
)


def normalize(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in value if not unicodedata.combining(char)).split())


def instant(value):
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return date if date.tzinfo is not None else None


def timestamp(date):
    return date.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def is_https(value):
    try:
        parts = urlsplit(value or "")
        return parts.scheme == "https" and bool(parts.hostname) and parts.username is None
    except ValueError:
        return False


def expired(row, now):
    deadline = row.get("deadline")
    if not deadline:
        return False
    close = instant(deadline)
    return close is None or close <= now


def relevance(title, description):
    if DIRECT.search(title) or (DIRECT.search(description) and (SPECIALTY.search(title) or ROLE.search(title))):
        return 55, "Vínculo directo con alta costura o confección a medida"
    text = f"{title} {description}"
    if CRAFT.search(title) or (SPECIALTY.search(title) and FASHION.search(text)):
        return 42, "Especialidad de diseño, taller o confección vinculada con moda"
    if ROLE.search(title) and FASHION.search(text) and (SPECIALTY.search(description) or CRAFT.search(description)):
        return 30, "Actividad vinculada con diseño, producción o negocio de moda"
    return 0, ""


def rank(row, now):
    if not is_https(row.get("url")) or expired(row, now):
        return None
    title = normalize(row["title"])
    description = normalize(row.get("description") or "")
    if IRRELEVANT_TITLE.search(title) or FEE.search(f"{title} {description}"):
        return None

    score, reason = relevance(title, description)
    if not score:
        return None

    reasons = [reason]
    if row["section"] == "colombia":
        score += 25
        reasons.append("Elegible desde Colombia")
    published = instant(row.get("publishedAt"))
    age = now - published if published else None
    if age is not None and timedelta() <= age <= timedelta(days=7):
        score += 10
        reasons.append("Publicada o actualizada en los últimos 7 días")
    elif age is not None and timedelta() <= age <= timedelta(days=30):
        score += 5
        reasons.append("Publicada o actualizada en los últimos 30 días")
    if row.get("clearApplication"):
        score += 10
        reasons.append("Enlace y condiciones de postulación identificados")
    ranked = {field: row.get(field) for field in PUBLIC_FIELDS}
    ranked.update(score=score, reasons=reasons)
    if not is_https(ranked["sourceUrl"]):
        ranked["sourceUrl"] = None
    return ranked


def canonical_url(url):
    parts = urlsplit(url)
    tracking = {"fbclid", "gclid", "ref", "source", "gh_src"}
    query = sorted((k, v) for k, v in parse_qsl(parts.query)
                   if not k.lower().startswith("utm_") and k.lower() not in tracking)
    return parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query)


def order_key(row):
    published = instant(row.get("publishedAt"))
    return row["section"], -row["score"], -(published.timestamp() if published else 0), row["id"]


def deduplicate(rows):
    result = []
    urls, identities, ids = set(), set(), set()
    for row in sorted(rows, key=lambda item: (item["pending"], order_key(item))):
        url = canonical_url(row["url"])
        identity = tuple(normalize(row[field]) for field in ("title", "organization", "location"))
        if row["id"] in ids or url in urls or identity in identities:
            continue
        ids.add(row["id"])
        urls.add(url)
        identities.add(identity)
        result.append(row)
    return sorted(result, key=order_key)


def collect(sources, previous, now):
    checked = timestamp(now)
    prior_rows = defaultdict(list)
    for row in previous.get("opportunities", []):
        prior_rows[row["sourceId"]].append(row)
    prior_status = {item["id"]: item for item in previous.get("sources", [])}
    status, opportunities = [], []

    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = {key: pool.submit(callback, now) for key, (_, _, callback) in sources.items()}
        for key, (name, url, _) in sources.items():
            prior_success = prior_status.get(key, {}).get("lastSuccessAt")
            prior_first_seen = {row["id"]: row["firstSeenAt"] for row in prior_rows[key]}
            try:
                candidates = tasks[key].result()
                rows = [row for candidate in candidates if (row := rank(candidate, now))]
            except Exception as error:
                logging.warning("%s: %s", name, error)
                last_good = instant(prior_success)
                rows = []
                if last_good and now - last_good <= KEEP_PENDING:
                    rows = [dict(row, pending=True) for row in prior_rows[key] if not expired(row, now)]
                state = "error"
            else:
                for row in rows:
                    row.update(
                        source=name, sourceId=key, pending=False,
                        firstSeenAt=prior_first_seen.get(row["id"], checked),
                    )
                state = "ok"
            status.append({
                "id": key, "name": name, "url": url, "status": state,
                "lastSuccessAt": checked if state == "ok" else prior_success,
            })
            opportunities.extend(rows)

    ranked = deduplicate(opportunities)
    counts = Counter(row["sourceId"] for row in ranked)
    for item in status:
        item["count"] = counts[item["id"]]
    return {
        "checkedAt": checked,
        "lastSuccessAt": checked if any(item["status"] == "ok" for item in status)
        else previous.get("lastSuccessAt"),
        "sources": status,
        "opportunities": ranked,
    }


def main():
    from sources import SOURCES

    parser = argparse.ArgumentParser(description="Actualiza el radar de alta costura.")
    parser.add_argument("--output", type=Path, default=Path("site/data.json"))
    args = parser.parse_args()
    previous = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else {}
    result = collect(SOURCES, previous, datetime.now(timezone.utc))
    staging = args.output.with_suffix(".tmp")
    staging.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    staging.replace(args.output)
    print(f"{len(result['opportunities'])} oportunidades en {args.output}")
    for source in result["sources"]:
        print(f"{source['id']}: {source['status']} ({source['count']})")


if __name__ == "__main__":
    main()
