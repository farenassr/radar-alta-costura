"use strict";

const byId = (id) => document.getElementById(id);
const filters = byId("filters");
const type = byId("type");
const modality = byId("modality");
const reset = byId("reset-filters");
const resultCount = byId("result-count");
const results = byId("results");
const template = byId("opportunity-template");
const dateTimeFormat = new Intl.DateTimeFormat("es-CO", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "America/Bogota",
});
const calendarFormat = new Intl.DateTimeFormat("es-CO", {
  dateStyle: "medium",
  timeZone: "UTC",
});
const numberFormat = new Intl.NumberFormat("es-CO");
const twelveHours = 12 * 60 * 60 * 1000;
const dateOnly = /^\d{4}-\d{2}-\d{2}$/;
const types = { empleo: "Empleo", consultoria: "Consultoría", proyecto: "Proyecto" };
const modalities = {
  presencial: "Presencial",
  remoto: "Remota",
  hibrido: "Híbrida",
  "sin-confirmar": "Modalidad por confirmar",
};
const groups = [
  ["colombia", "Colombia y remoto", "Colombia y trabajo remoto abierto al país"],
  ["internacional", "Internacional", "La elegibilidad para trabajar desde Colombia depende de cada publicación."],
];
let radar;
let renderedCounts;

function node(tag, value, className) {
  const element = document.createElement(tag);
  if (value !== undefined) element.textContent = value;
  if (className) element.className = className;
  return element;
}

function publicLink(value) {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol === "https:" && !url.username && !url.password) return value;
  } catch {
    // A malformed upstream URL is shown as plain text.
  }
  return null;
}

function dateValue(value) {
  if (typeof value !== "string") return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function timeElement(value, deadline = false) {
  const date = dateValue(value);
  if (!date) return document.createTextNode("Sin fecha informada");
  const calendarDate = deadline && dateOnly.test(value);
  const label = calendarDate ? calendarFormat.format(date) : `${dateTimeFormat.format(date)} (Colombia)`;
  const time = node("time", label);
  time.dateTime = value;
  return time;
}

function opportunityCard(item) {
  const card = template.content.cloneNode(true);
  const field = (name) => card.querySelector(`.${name}`);
  field("item-type").textContent = types[item.type];
  field("item-modality").textContent = modalities[item.modality];
  field("item-pending").hidden = !item.pending;
  field("item-title").textContent = item.title;
  field("item-organization").textContent = item.organization || "Organización sin informar";
  field("item-location").textContent = item.location || "Sin ubicación informada";
  field("item-deadline").append(timeElement(item.deadline, true));
  if (item.compensation) {
    field("item-pay-row").hidden = false;
    field("item-pay").textContent = item.compensation;
  }

  const apply = field("apply-link");
  const applyUrl = publicLink(item.url);
  if (applyUrl) {
    apply.href = applyUrl;
    apply.setAttribute("aria-label", `Ver publicación de ${item.title}`);
  } else {
    apply.replaceWith(node("span", "Enlace de publicación sin confirmar", "apply-link"));
  }
  if (item.source) {
    const source = field("item-source");
    const sourceUrl = publicLink(item.sourceUrl);
    if (sourceUrl) {
      const link = node("a", item.source);
      link.href = sourceUrl;
      source.append("Fuente ", link);
    } else {
      source.textContent = `Fuente ${item.source}`;
    }
  }

  field("score-number").textContent = Number.isFinite(item.score) ? numberFormat.format(item.score) : "—";
  const reasons = item.reasons.length ? item.reasons : ["Sin motivos de afinidad informados."];
  for (const reason of reasons) field("score-reasons").append(node("li", reason));
  return card;
}

function resultSection(group, items) {
  const [id, title, description] = group;
  const section = node("section", undefined, "result-section");
  const header = node("header", undefined, "group-header");
  const heading = node("h3", title);
  heading.id = `grupo-${id}`;
  section.setAttribute("aria-labelledby", heading.id);
  header.append(heading, node("p", description));
  const list = node("ol", undefined, "opportunities");
  list.setAttribute("role", "list");
  for (const item of items) list.append(opportunityCard(item));
  section.append(header, list);
  return section;
}

function emptyState(title, description, actionLabel, action) {
  const panel = node("div", undefined, "empty-state");
  const mark = node("span", "✧", "empty-mark");
  mark.setAttribute("aria-hidden", "true");
  const body = node("div");
  body.append(node("h3", title), node("p", description));
  if (action) {
    const button = node("button", actionLabel, "text-button");
    button.type = "button";
    button.addEventListener("click", action);
    body.append(button);
  }
  panel.append(mark, body);
  return panel;
}

function clearFilters() {
  filters.reset();
  type.focus();
  renderResults();
}

function matchingOpportunities() {
  const now = Date.now();
  const sourceChecks = new Map(radar.sources.map((source) => [source.name, dateValue(source.lastSuccessAt)]));
  const available = radar.opportunities.filter(({ deadline, pending, source }) => {
    const lastSourceCheck = sourceChecks.get(source);
    if (pending && (!lastSourceCheck || now - lastSourceCheck.getTime() > 4 * twelveHours)) return false;
    if (!deadline) return true;
    const cutoff = dateOnly.test(deadline) ? `${deadline}T23:59:59.999-05:00` : deadline;
    const closing = dateValue(cutoff);
    return !closing || closing.getTime() > now;
  });
  const matches = available.filter((item) =>
    (!type.value || item.type === type.value) && (!modality.value || item.modality === modality.value)
  );
  return { available, matches };
}

function renderResults() {
  if (!radar) return;
  const { available, matches } = matchingOpportunities();
  renderedCounts = { available: available.length, matches: matches.length };
  reset.disabled = !(type.value || modality.value);
  resultCount.textContent = matches.length === 1
    ? "1 oportunidad"
    : `${numberFormat.format(matches.length)} oportunidades`;
  results.replaceChildren();
  if (!matches.length) {
    if (available.length) {
      results.append(emptyState(
        "Sin coincidencias",
        "Prueba con otro tipo de oportunidad o modalidad para ampliar la búsqueda.",
        "Mostrar todas",
        clearFilters,
      ));
    } else if (!dateValue(radar.lastSuccessAt)) {
      results.append(emptyState(
        "El radar aún no tiene resultados",
        "Consulta el estado de las fuentes para conocer el resultado de la última revisión.",
      ));
    } else {
      results.append(emptyState(
        "Sin oportunidades vigentes registradas",
        "Consulta el estado de las fuentes al final de la página para ver el resultado de la última revisión.",
      ));
    }
    return;
  }
  for (const group of groups) {
    const items = matches.filter((item) => item.section === group[0]);
    if (items.length) results.append(resultSection(group, items));
  }
}

function renderFreshness() {
  if (!radar) return;
  const checked = dateValue(radar.checkedAt);
  const lastSuccess = dateValue(radar.lastSuccessAt);
  const notice = byId("freshness");
  let message = "";
  if (!lastSuccess) {
    message = "El radar aún no registra una revisión exitosa. Consulta el estado de las fuentes.";
  } else if (Date.now() - lastSuccess.getTime() > twelveHours) {
    message = "Han pasado más de 12 horas desde la última revisión exitosa. Verifica la vigencia en la publicación original.";
  } else if (!checked || Date.now() - checked.getTime() > twelveHours) {
    message = "Han pasado más de 12 horas desde la última revisión registrada. Verifica la vigencia en la publicación original.";
  }
  notice.hidden = !message;
  if (notice.textContent !== message) notice.textContent = message;
  byId("health-link").dataset.health = message || radar.sources.some((source) => source.status === "error")
    ? "warning"
    : "ok";
}

function updateRadarStatus() {
  if (!radar) return;
  renderFreshness();
  const { available, matches } = matchingOpportunities();
  if (matches.length !== renderedCounts.matches || (!matches.length && Boolean(available.length) !== Boolean(renderedCounts.available))) {
    renderResults();
  }
}

function renderSources() {
  const review = byId("review");
  review.replaceChildren(timeElement(radar.checkedAt));
  const list = byId("source-list");
  const summary = byId("source-summary");
  const successes = radar.sources.filter((source) => source.status === "ok").length;
  if (!radar.sources.length) {
    summary.textContent = "Sin fuentes registradas para esta revisión.";
  } else {
    summary.textContent = `${numberFormat.format(successes)} de ${numberFormat.format(radar.sources.length)} fuentes consultadas correctamente.`;
  }
  list.replaceChildren();
  for (const source of radar.sources) {
    const item = node("li");
    const url = publicLink(source.url);
    const name = node(url ? "a" : "strong", source.name);
    if (url) name.href = url;
    const status = source.status === "ok"
      ? node("p", source.count === 1 ? "Consulta correcta · 1 resultado" : `Consulta correcta · ${numberFormat.format(source.count)} resultados`)
      : node("p", "No se pudo consultar", "source-error");
    const date = node("p");
    const successDate = dateValue(source.lastSuccessAt);
    if (successDate) date.append("Última consulta exitosa ", timeElement(source.lastSuccessAt));
    else date.textContent = "Sin consultas exitosas registradas.";
    item.append(name, status, date);
    list.append(item);
  }
  renderFreshness();
}

async function loadRadar() {
  results.setAttribute("aria-busy", "true");
  resultCount.textContent = "Cargando oportunidades…";
  results.replaceChildren();
  try {
    const response = await fetch("./data.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!Array.isArray(data?.opportunities) || !Array.isArray(data?.sources)) {
      throw new Error("Formato de datos inválido");
    }
    radar = data;
    renderResults();
    renderSources();
  } catch {
    radar = undefined;
    resultCount.textContent = "Datos no disponibles";
    byId("review").textContent = "Sin datos";
    byId("health-link").dataset.health = "warning";
    byId("source-summary").textContent = "No fue posible cargar el estado de las fuentes.";
    results.replaceChildren(emptyState(
      "El radar no está disponible",
      "No se pudieron cargar los datos de la última revisión. Intenta consultarlos de nuevo.",
      "Volver a intentar",
      loadRadar,
    ));
  } finally {
    results.setAttribute("aria-busy", "false");
  }
}

filters.addEventListener("submit", (event) => event.preventDefault());
filters.addEventListener("change", renderResults);
reset.addEventListener("click", clearFilters);
window.addEventListener("focus", updateRadarStatus);
window.setInterval(updateRadarStatus, 60_000);
loadRadar();
