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

const STATUS_LABEL = { ok: "정적 검사 통과", hold: "보류", error: "오류" };
let samples = [];
let requestSerial = 0;
let blobUrl = null;

sampleList.addEventListener("change", () => {
  const selected = currentSample();
  if (selected) showPreview(selected);
  invalidate();
});

analyzeButton.addEventListener("click", () => {
  const selected = currentSample();
  if (!selected) return;
  runAnalysis(selected.id);
});

loadSamples();

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
    notice.textContent = typeof payload.data_notice === "string" ? payload.data_notice : "";
    paintSamples();
  } catch (_error) {
    if (mine !== requestSerial) return;
    live.textContent = "서버 응답 없음";
  }
}

function paintSamples() {
  sampleList.replaceChildren();
  samples.forEach((sample) => {
    const label = document.createElement("label");
    label.className = "choice";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "sample_id";
    input.value = String(sample.id);
    const text = document.createElement("span");
    text.textContent = " " + sample.label + " ";
    const kind = document.createElement("span");
    kind.className = "kind";
    kind.textContent = String(sample.kind);
    label.append(input, text, kind);
    sampleList.append(label);
  });
}

function currentSample() {
  const selected = sampleList.querySelector("input:checked");
  if (!selected) return null;
  return samples.find((sample) => sample.id === selected.value) || null;
}

function showPreview(sample) {
  const body = sample.preview || {};
  document.querySelector("#preview-old").textContent = body.spec_old || "";
  document.querySelector("#preview-new").textContent = body.spec_new || "";
  document.querySelector("#preview-mapping").textContent = body.mapping || "";
  document.querySelector("#preview-source").textContent = body.source || "";
  preview.hidden = false;
  sampleHint.hidden = true;
  analyzeButton.disabled = false;
}

function invalidate() {
  requestSerial += 1;
  clearResult();
  clearDownload();
  live.textContent = "";
  analyzeButton.disabled = !currentSample();
  analyzeButton.textContent = "분석 실행";
  setLocked(false);
}

async function runAnalysis(sampleId) {
  const mine = ++requestSerial;
  clearResult();
  clearDownload();
  live.textContent = "분석 중";
  analyzeButton.disabled = true;
  analyzeButton.textContent = "분석 중";
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
    live.textContent = "서버 응답 없음";
  } finally {
    if (mine === requestSerial) {
      setLocked(false);
      analyzeButton.disabled = !currentSample();
      if (analyzeButton.textContent === "분석 중") analyzeButton.textContent = "다시 분석";
    }
  }
}

function renderEnvelope(payload) {
  live.textContent = "분석 응답을 표시했습니다. 고객 테스트나 PR 결과가 아닙니다.";
  stages.replaceChildren();
  ["classify", "scan", "patch_preview"].forEach((name) => {
    const stage = payload.static_analysis[name];
    const box = document.createElement("article");
    box.className = "stage";
    const title = document.createElement("h3");
    title.textContent = name;
    const meta = document.createElement("p");
    meta.className = "stage-meta";
    const label = STATUS_LABEL[stage.status] || stage.status;
    meta.textContent = "status " + stage.status + " (" + label + "), reason " + String(stage.reason_code);
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
      if (line.startsWith("+") && !line.startsWith("+++")) row.textContent = "추가 " + line;
      else if (line.startsWith("-") && !line.startsWith("---")) row.textContent = "삭제 " + line;
      else row.textContent = "문맥 " + line;
      view.append(row);
    });
    diffRegion.append(view);
  } else {
    const empty = document.createElement("p");
    empty.textContent = "패치 미리보기 없음";
    diffRegion.append(empty);
  }
  const runtime = payload.runtime;
  const cards = [
    ["runtime", "status " + runtime.status + ", reason " + runtime.reason_code, runtime.user_message],
    ["PR", "existence " + payload.pr.existence, ""],
    ["AC24", String(payload.ac24), ""],
    ["cli_manifest_claim", String(payload.cli_manifest_claim), ""],
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

function showError(error) {
  clearResult();
  live.textContent = String(error.code) + " " + String(error.user_message);
  analyzeButton.textContent = "다시 분석";
}

function showFormat() {
  clearResult();
  live.textContent = "응답 형식이 완전하지 않습니다.";
}

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

function clearResult() {
  stages.replaceChildren();
  diffRegion.replaceChildren();
  blocks.replaceChildren();
}

function armDownload(text) {
  clearDownload();
  blobUrl = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  downloadLink.href = blobUrl;
  downloadLink.hidden = false;
  exportHint.hidden = true;
}

function clearDownload() {
  if (blobUrl) URL.revokeObjectURL(blobUrl);
  blobUrl = null;
  downloadLink.hidden = true;
  downloadLink.removeAttribute("href");
  exportHint.hidden = false;
}

function setLocked(locked) {
  sampleList.querySelectorAll("input").forEach((input) => {
    input.disabled = locked;
  });
}

function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch (_error) {
    return null;
  }
}
