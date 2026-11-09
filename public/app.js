const sampleList = document.querySelector("#sample-list");
const sampleHint = document.querySelector("#sample-hint");
const preview = document.querySelector("#preview");
const analyzeButton = document.querySelector("#analyze");
const live = document.querySelector("#live");
const stages = document.querySelector("#stages");
const diffRegion = document.querySelector("#diff-region");
const blocks = document.querySelector("#blocks");
const exportHint = document.querySelector("#export-hint");
const downloadLink = document.querySelector("#download");
const notice = document.querySelector("#data-notice");
const langSwitch = document.querySelector("#lang-switch");

const I18N = window.PATCHPILOT_I18N;
const LANG_KEY = "patchpilot.lang";

let lang = "en";
let samples = [];
let selectedId = null;
let requestSerial = 0;
let blobUrl = null;
let phase = "idle";
let analyzeMode = "run";
let inputsLocked = false;
let lastPayload = null;
let lastError = null;
let noticeText = "";

// URL의 lang이 우선이고, 없으면 저장된 언어, 그것도 없으면 영어를 고른다.
function resolveLang() {
  const fromUrl = new URLSearchParams(window.location.search).get("lang");
  if (fromUrl === "ko" || fromUrl === "en") {
    storeLang(fromUrl);
    return fromUrl;
  }
  const stored = readLang();
  return stored || "en";
}

// localStorage에서 ko 또는 en만 읽는다.
function readLang() {
  try {
    const value = localStorage.getItem(LANG_KEY);
    if (value === "ko" || value === "en") return value;
  } catch (_error) {
    return null;
  }
  return null;
}

// 선택한 언어를 localStorage에 남긴다.
function storeLang(value) {
  try {
    localStorage.setItem(LANG_KEY, value);
  } catch (_error) {
    return;
  }
}

// 현재 언어 사전에서 문구를 꺼낸다. 없으면 영어 문구를 쓴다.
function t(key) {
  const pack = I18N[lang] || I18N.en;
  if (Object.prototype.hasOwnProperty.call(pack, key)) return pack[key];
  return I18N.en[key];
}

// 자리 표시가 있는 문구에 상태 값을 그대로 넣는다.
function fill(template, values) {
  return String(template).replace(/\{(\w+)\}/g, (_match, key) => String(values[key]));
}

// 샘플 id에 해당하는 화면 라벨을 고른다. 모르는 id는 API 문구를 유지한다.
function sampleLabel(sample) {
  const labels = t("sampleLabels") || {};
  if (Object.prototype.hasOwnProperty.call(labels, sample.id)) return labels[sample.id];
  return String(sample.label);
}

// 고정 HTML 문구, 문서 언어, 토글 상태를 현재 언어로 맞춘다.
function applyStatic() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.getAttribute("data-i18n"));
  });
  document.title = t("title");
  if (langSwitch) langSwitch.setAttribute("aria-label", t("langGroup"));
  document.querySelectorAll("[data-set-lang]").forEach((button) => {
    button.setAttribute("aria-pressed", button.getAttribute("data-set-lang") === lang ? "true" : "false");
  });
  notice.textContent = noticeText;
  syncAnalyzeButton();
}

// 분석 버튼 문구와 활성 상태를 현재 단계에 맞춘다.
function syncAnalyzeButton() {
  const keys = { run: "analyzeRun", running: "analyzeRunning", again: "analyzeAgain" };
  analyzeButton.textContent = t(keys[analyzeMode] || "analyzeRun");
  analyzeButton.disabled = phase === "running" || !selectedId;
}

// 언어를 바꾸고 주소와 저장소에 남긴 뒤, 현재 결과를 다시 그린다.
function setLang(next) {
  if (next !== "ko" && next !== "en") return;
  lang = next;
  storeLang(next);
  const url = new URL(window.location.href);
  url.searchParams.set("lang", next);
  history.replaceState(null, "", url);
  applyLanguage();
}

// 정적 문구와 이미 받아 둔 결과를 현재 언어로 다시 그린다.
function applyLanguage() {
  applyStatic();
  paintSamples();
  const selected = currentSample();
  if (selected) showPreview(selected);
  refreshPhase();
}

// 진행 중인 결과 문구만 현재 언어로 다시 쓴다.
function refreshPhase() {
  if (phase === "shown" && lastPayload) renderEnvelope(lastPayload);
  else if (phase === "error" && lastError) showError(lastError);
  else if (phase === "format") showFormat();
  else if (phase === "offline") live.textContent = t("liveOffline");
  else if (phase === "running") live.textContent = t("analyzeRunning");
  syncAnalyzeButton();
}

sampleList.addEventListener("change", () => {
  const selected = currentSample();
  selectedId = selected ? selected.id : null;
  if (selected) showPreview(selected);
  invalidate();
});

analyzeButton.addEventListener("click", () => {
  const selected = currentSample();
  if (!selected) return;
  runAnalysis(selected.id);
});

langSwitch.addEventListener("click", (event) => {
  const button = event.target.closest("[data-set-lang]");
  if (!button) return;
  setLang(button.getAttribute("data-set-lang"));
});

lang = resolveLang();
applyStatic();
loadSamples();

// 샘플 목록을 받아 고지 문장과 선택 목록을 채운다.
async function loadSamples() {
  const mine = ++requestSerial;
  try {
    const response = await fetch("/api/v1/samples", { headers: { Accept: "application/json" }, cache: "no-store" });
    const text = await response.text();
    if (mine !== requestSerial) return;
    const payload = parseJson(text);
    if (!payload || !Array.isArray(payload.samples)) {
      showFormat();
      return;
    }
    samples = payload.samples;
    noticeText = typeof payload.data_notice === "string" ? payload.data_notice : "";
    notice.textContent = noticeText;
    paintSamples();
  } catch (_error) {
    if (mine !== requestSerial) return;
    phase = "offline";
    live.textContent = t("liveOffline");
  }
}

// 샘플 라디오를 다시 그리고, 고른 샘플과 잠금 상태를 유지한다.
function paintSamples() {
  sampleList.replaceChildren();
  samples.forEach((sample) => {
    const label = document.createElement("label");
    label.className = "choice";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "sample_id";
    input.value = String(sample.id);
    input.checked = sample.id === selectedId;
    input.disabled = inputsLocked;
    const text = document.createElement("span");
    text.textContent = " " + sampleLabel(sample) + " ";
    const kind = document.createElement("span");
    kind.className = "kind";
    kind.textContent = String(sample.kind);
    label.append(input, text, kind);
    sampleList.append(label);
  });
}

// 현재 선택된 샘플 객체를 찾는다.
function currentSample() {
  const selected = sampleList.querySelector("input:checked");
  if (!selected) return null;
  return samples.find((sample) => sample.id === selected.value) || null;
}

// 읽기 전용 미리보기 본문을 보여 준다.
function showPreview(sample) {
  const body = sample.preview || {};
  document.querySelector("#preview-old").textContent = body.spec_old || "";
  document.querySelector("#preview-new").textContent = body.spec_new || "";
  document.querySelector("#preview-mapping").textContent = body.mapping || "";
  document.querySelector("#preview-source").textContent = body.source || "";
  preview.hidden = false;
  sampleHint.hidden = true;
  syncAnalyzeButton();
}

// 샘플이 바뀌면 이전 분석 결과와 다운로드를 지운다.
function invalidate() {
  requestSerial += 1;
  phase = "idle";
  analyzeMode = "run";
  lastPayload = null;
  lastError = null;
  clearResult();
  clearDownload();
  live.textContent = "";
  syncAnalyzeButton();
  setLocked(false);
}

// 고른 샘플만 같은 origin 분석 API로 보내고 응답을 그린다.
async function runAnalysis(sampleId) {
  const mine = ++requestSerial;
  phase = "running";
  analyzeMode = "running";
  lastPayload = null;
  lastError = null;
  clearResult();
  clearDownload();
  live.textContent = t("analyzeRunning");
  syncAnalyzeButton();
  setLocked(true);
  try {
    const response = await fetch("/api/v1/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ sample_id: sampleId }),
      cache: "no-store",
    });
    const text = await response.text();
    if (mine !== requestSerial) return;
    const payload = parseJson(text);
    if (!payload) {
      showFormat();
      return;
    }
    if (payload.ok === false && payload.error) {
      showError(payload.error);
      return;
    }
    if (!consistentEnvelope(payload)) {
      showFormat();
      return;
    }
    renderEnvelope(payload);
    if (payload.downloadable === true) armDownload(text);
  } catch (_error) {
    if (mine !== requestSerial) return;
    phase = "offline";
    live.textContent = t("liveOffline");
  } finally {
    if (mine === requestSerial) {
      setLocked(false);
      if (analyzeMode === "running") analyzeMode = "again";
      syncAnalyzeButton();
    }
  }
}

// 정적 분석 envelope를 단계, diff, 차단 카드로 그린다.
function renderEnvelope(payload) {
  phase = "shown";
  lastPayload = payload;
  live.textContent = t("liveShown");
  stages.replaceChildren();
  ["classify", "scan", "patch_preview"].forEach((name) => {
    const stage = payload.static_analysis[name];
    const box = document.createElement("article");
    box.className = "stage";
    const title = document.createElement("h3");
    title.textContent = name;
    const meta = document.createElement("p");
    meta.className = "stage-meta";
    const label = statusLabel(stage.status);
    meta.textContent = fill(t("stageMeta"), {
      status: stage.status,
      label: label,
      reason: stage.reason_code,
    });
    const message = document.createElement("p");
    message.textContent = stage.user_message;
    const summary = document.createElement("p");
    summary.textContent = stage.evidence.summary;
    const refs = document.createElement("p");
    refs.textContent = stage.evidence.refs.join(", ");
    box.append(title, meta, message, summary, refs);
    stages.append(box);
  });
  diffRegion.replaceChildren();
  if (typeof payload.patch_preview.diff === "string") {
    const view = document.createElement("div");
    view.className = "diff";
    view.setAttribute("tabindex", "0");
    payload.patch_preview.diff.split("\n").forEach((line) => {
      const row = document.createElement("div");
      if (line.startsWith("+") && !line.startsWith("+++")) row.textContent = t("diffAdd") + line;
      else if (line.startsWith("-") && !line.startsWith("---")) row.textContent = t("diffDel") + line;
      else row.textContent = t("diffContext") + line;
      view.append(row);
    });
    diffRegion.append(view);
  } else {
    const empty = document.createElement("p");
    empty.textContent = t("diffEmpty");
    diffRegion.append(empty);
  }
  const runtime = payload.runtime;
  const cards = [
    [t("cardRuntime"), fill(t("runtimeMeta"), { status: runtime.status, reason: runtime.reason_code }), runtime.user_message],
    [t("cardPr"), fill(t("prMeta"), { existence: payload.pr.existence }), ""],
    [t("cardAc"), String(payload.ac24), ""],
    [t("cardCli"), String(payload.cli_manifest_claim), ""],
  ];
  blocks.replaceChildren();
  const wrap = document.createElement("div");
  wrap.className = "cards";
  cards.forEach(([title, metaText, messageText]) => {
    const card = document.createElement("article");
    card.className = "card";
    const heading = document.createElement("h3");
    heading.textContent = title;
    const meta = document.createElement("p");
    meta.textContent = metaText;
    card.append(heading, meta);
    if (messageText) {
      const message = document.createElement("p");
      message.textContent = messageText;
      card.append(message);
    }
    wrap.append(card);
  });
  blocks.append(wrap);
}

// ok, hold, error 상태 문구를 고르고 그 외 값은 코드 그대로 둔다.
function statusLabel(status) {
  if (status === "ok") return t("statusOk");
  if (status === "hold") return t("statusHold");
  if (status === "error") return t("statusError");
  return status;
}

// 안전 오류 코드와 API 문장을 그대로 보여 준다.
function showError(error) {
  clearResult();
  lastPayload = null;
  lastError = error;
  phase = "error";
  analyzeMode = "again";
  live.textContent = String(error.code) + " " + String(error.user_message);
  syncAnalyzeButton();
}

// 응답 JSON이 계약 모양이 아니면 형식 오류만 보여 준다.
function showFormat() {
  clearResult();
  lastPayload = null;
  lastError = null;
  phase = "format";
  live.textContent = t("liveFormat");
}

// envelope 필수 필드와 diff 규칙이 맞는지 확인한다.
function consistentEnvelope(payload) {
  if (!payload || payload.envelope_kind !== "pp-web-static-analysis/1") return false;
  if (typeof payload.sample_id !== "string" || typeof payload.analyzed_at !== "string") return false;
  if (payload.cli_manifest_claim !== false || typeof payload.downloadable !== "boolean") return false;
  if (!payload.runtime || typeof payload.runtime.status !== "string" || typeof payload.runtime.user_message !== "string") return false;
  if (!payload.pr || typeof payload.pr.existence !== "string" || typeof payload.ac24 !== "string") return false;
  const staticAnalysis = payload.static_analysis;
  if (!staticAnalysis) return false;
  const names = ["classify", "scan", "patch_preview"];
  if (!names.every((name) => stageShape(staticAnalysis[name]))) return false;
  const previewBody = payload.patch_preview;
  if (!previewBody || !Array.isArray(previewBody.files)) return false;
  const allOk = names.every((name) => staticAnalysis[name].status === "ok");
  const diff = previewBody.diff;
  if (allOk) return typeof diff === "string" && diff.length > 0;
  return diff === null;
}

// 단계 객체에 status, reason, 메시지, 증거가 있는지 확인한다.
function stageShape(stage) {
  return Boolean(
    stage &&
    typeof stage.status === "string" &&
    Object.prototype.hasOwnProperty.call(stage, "reason_code") &&
    typeof stage.user_message === "string" &&
    stage.evidence &&
    typeof stage.evidence.summary === "string" &&
    Array.isArray(stage.evidence.refs)
  );
}

// 분석 결과 영역을 비운다.
function clearResult() {
  stages.replaceChildren();
  diffRegion.replaceChildren();
  blocks.replaceChildren();
}

// 현재 응답 JSON을 다운로드 링크로 연결한다.
function armDownload(text) {
  clearDownload();
  blobUrl = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  downloadLink.href = blobUrl;
  downloadLink.hidden = false;
  exportHint.hidden = true;
}

// 이전 다운로드 URL을 해제하고 링크를 숨긴다.
function clearDownload() {
  if (blobUrl) URL.revokeObjectURL(blobUrl);
  blobUrl = null;
  downloadLink.hidden = true;
  downloadLink.removeAttribute("href");
  exportHint.hidden = false;
}

// 분석 중에는 샘플 선택을 잠근다.
function setLocked(locked) {
  inputsLocked = locked;
  sampleList.querySelectorAll("input").forEach((input) => {
    input.disabled = locked;
  });
}

// JSON이 아니면 null을 돌려준다.
function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch (_error) {
    return null;
  }
}
