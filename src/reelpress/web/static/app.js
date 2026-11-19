const STATUS = {
  queued: "排队",
  running: "生成中",
  succeeded: "已完成",
  failed: "失败",
  scheduled: "待发布",
  publishing: "发布中",
  published: "已发布",
  publish_failed: "发布失败",
};

const STAGE_ORDER = ["script", "audio", "subtitle", "materials", "compose", "done"];
const STAGE_LABEL = {
  script: "文案",
  audio: "配音",
  subtitle: "字幕",
  materials: "画面",
  compose: "合成",
  done: "完成",
  publish: "发布",
  pending: "等待",
  failed: "失败",
};

const PLATFORMS = [
  ["youtube", "YouTube"],
  ["douyin", "抖音"],
  ["kuaishou", "快手"],
  ["xiaohongshu", "小红书"],
  ["bilibili", "哔哩哔哩"],
];

const state = {
  view: "studio",
  jobs: [],
  selected: null,
  settings: null,
  platforms: [],
  polling: null,
  loginTimer: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let data = {};
  if (text) {
    try { data = JSON.parse(text); } catch { data = { detail: text }; }
  }
  if (!response.ok) {
    const detail = data.detail || data.message || "请求失败";
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => node.classList.add("hidden"), 4200);
}

function showView(name) {
  state.view = name;
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === name);
  });
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view.id === `view-${name}`);
  });
  if (name === "jobs") renderDetail();
  if (name === "accounts") loadPlatforms();
  if (name === "settings") fillSettings();
}

function selectedPlatforms(root) {
  return [...root.querySelectorAll("input[data-platform]:checked")].map((node) => node.dataset.platform);
}

function platformChecks(container, inputName) {
  container.innerHTML = PLATFORMS.map(([name, label]) => `
    <label class="chip"><input type="checkbox" data-platform="${name}" name="${inputName}" /> ${label}</label>
  `).join("");
}

function jobButton(job, active) {
  const badge = STATUS[job.status] || job.status;
  return `
    <button type="button" class="job ${active ? "active-job" : ""}" data-id="${job.id}">
      <div class="job-top">
        <strong>${escapeHtml(job.topic || "未命名")}</strong>
        <span class="badge ${job.status}">${badge}</span>
      </div>
      <small>${job.progress || 0}% · ${STAGE_LABEL[job.stage] || job.stage} · ${formatTime(job.created_at)}</small>
    </button>
  `;
}

function renderJobs() {
  const recent = $("recent-jobs");
  const all = $("all-jobs");
  if (!state.jobs.length) {
    const empty = `<div class="empty">还没有成片。写一个主题，或者先跑一条离线演示。</div>`;
    recent.innerHTML = empty;
    all.innerHTML = empty;
    return;
  }
  recent.innerHTML = state.jobs.slice(0, 6).map((job) => jobButton(job, job.id === state.selected)).join("");
  all.innerHTML = state.jobs.map((job) => jobButton(job, job.id === state.selected)).join("");
}

function jobSignature(job) {
  if (!job) return "";
  return [job.id, job.status, job.stage, job.progress, job.updated_at, job.error].join("|");
}

function renderDetail() {
  const host = $("job-detail");
  const job = state.jobs.find((item) => item.id === state.selected);
  const signature = jobSignature(job);
  if (host.dataset.signature === signature && host.dataset.job === (state.selected || "")) return;
  host.dataset.signature = signature;
  host.dataset.job = state.selected || "";
  if (!job) {
    host.innerHTML = `<div class="empty-detail"><h2>选一条任务</h2><p>这里会放成片预览、文案，以及补发到各平台的按钮。</p></div>`;
    return;
  }
  const result = job.result || {};
  const stageIndex = STAGE_ORDER.indexOf(job.stage === "publish" ? "done" : job.stage);
  const steps = STAGE_ORDER.map((stage, index) => {
    let cls = "step";
    if (job.status === "failed" && stage === job.stage) cls += " on";
    else if (stageIndex > index || job.status === "succeeded" || job.status === "published" || job.status === "scheduled") cls += " done";
    else if (stageIndex === index) cls += " on";
    return `<span class="${cls}">${STAGE_LABEL[stage]}</span>`;
  }).join("");
  const warnings = (result.warnings || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const uploads = (result.uploads || []).map((item) => `<li>${escapeHtml(item.platform)}：${escapeHtml(item.message || (item.success ? "成功" : "失败"))}</li>`).join("");
  const video = result.video_path
    ? `<video controls src="/api/jobs/${job.id}/video?ts=${encodeURIComponent(job.updated_at || "")}"></video>`
    : `<p class="hint">成片还在准备。当前阶段：${STAGE_LABEL[job.stage] || job.stage}。</p>`;
  const error = job.error ? `<p class="hint" style="color:var(--bad)">${escapeHtml(job.error)}</p>` : "";
  host.innerHTML = `
    <div class="panel-head">
      <h2>${escapeHtml(result.title || job.topic)}</h2>
      <span class="badge ${job.status}">${STATUS[job.status] || job.status}</span>
    </div>
    <div class="steps">${steps}</div>
    ${error}
    ${video}
    <p>${escapeHtml(result.description || "")}</p>
    <p class="hint">${(result.hashtags || []).map(escapeHtml).join(" ")}</p>
    ${warnings ? `<ul class="warn-list">${warnings}</ul>` : ""}
    ${result.script ? `<h3>口播</h3><div class="script-block">${escapeHtml(result.script)}</div>` : ""}
    ${uploads ? `<h3>发布结果</h3><ul class="warn-list">${uploads}</ul>` : ""}
    <h3>发布这条成片</h3>
    <div class="platform-picks" id="detail-platforms"></div>
    <div class="split">
      <label class="field"><span>账号名</span><input id="detail-account" value="${escapeHtml(job.params?.account || "default")}" /></label>
      <label class="field"><span>定时（可空）</span><input id="detail-at" type="datetime-local" /></label>
    </div>
    <label class="inline"><input id="detail-native" type="checkbox" /> 交给平台定时</label>
    <div class="actions">
      <button type="button" class="btn primary" id="detail-publish">发布</button>
      <button type="button" class="btn ghost" id="detail-delete">删除任务</button>
    </div>
  `;
  platformChecks($("detail-platforms"), "detail-platform");
  $("detail-publish").onclick = () => publishJob(job.id);
  $("detail-delete").onclick = () => deleteJob(job.id);
}

async function loadJobs() {
  const data = await api("/api/jobs");
  state.jobs = data.jobs || [];
  if (state.selected && !state.jobs.some((job) => job.id === state.selected)) state.selected = null;
  renderJobs();
  if (state.view === "jobs") renderDetail();
  const busy = state.jobs.some((job) => ["queued", "running", "publishing"].includes(job.status));
  if (busy && !state.polling) {
    state.polling = setInterval(() => loadJobs().catch((error) => toast(error.message)), 1500);
  }
  if (!busy && state.polling) {
    clearInterval(state.polling);
    state.polling = null;
  }
}

function formPayload(mock) {
  const publish = $("publish").checked && !mock;
  return {
    topic: $("topic").value.trim() || (mock ? "清晨的街道" : ""),
    script: $("script").value.trim(),
    aspect: document.querySelector("input[name=aspect]:checked").value,
    voice: $("voice").value,
    stock_provider: mock ? "placeholder" : $("stock").value,
    bgm: $("bgm").checked,
    burn_subtitles: $("burn").checked,
    publish,
    platforms: publish ? selectedPlatforms($("platform-picks")) : [],
    account: $("account").value.trim() || "default",
    publish_at: publish ? ($("publish-at").value || null) : null,
    native_schedule: publish && $("native-schedule").checked,
    mock,
  };
}

async function createJob(mock) {
  const payload = formPayload(mock);
  if (!payload.topic && !payload.script && !mock) {
    toast("先写主题，或贴一段口播。");
    return;
  }
  if (payload.publish && !payload.platforms.length) {
    toast("勾选了发布，但还没有选平台。");
    return;
  }
  $("submit-btn").disabled = true;
  $("demo-btn").disabled = true;
  $("form-hint").textContent = mock ? "正在做一条离线演示，大约需要十几秒。" : "已进入队列。配音和素材下载取决于网络。";
  try {
    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    state.selected = job.id;
    toast(mock ? "离线演示已开始。" : "任务已排队。");
    showView("jobs");
    await loadJobs();
  } catch (error) {
    toast(error.message);
  } finally {
    $("submit-btn").disabled = false;
    $("demo-btn").disabled = false;
  }
}

async function publishJob(jobId) {
  const platforms = selectedPlatforms($("detail-platforms"));
  if (!platforms.length) {
    toast("先选择要发布的平台。");
    return;
  }
  try {
    await api(`/api/jobs/${jobId}/publish`, {
      method: "POST",
      body: JSON.stringify({
        platforms,
        account: $("detail-account").value.trim() || "default",
        publish_at: $("detail-at").value || null,
        native_schedule: $("detail-native").checked,
      }),
    });
    toast("发布请求已提交。");
    await loadJobs();
  } catch (error) {
    toast(error.message);
  }
}

async function deleteJob(jobId) {
  if (!confirm("删除这条任务和它的成片文件？")) return;
  try {
    await api(`/api/jobs/${jobId}`, { method: "DELETE" });
    if (state.selected === jobId) state.selected = null;
    await loadJobs();
    renderDetail();
  } catch (error) {
    toast(error.message);
  }
}

async function loadPlatforms() {
  const account = $("account-name").value.trim() || "default";
  try {
    const data = await api(`/api/platforms?account=${encodeURIComponent(account)}`);
    state.platforms = data.platforms || [];
  } catch (error) {
    toast(error.message);
    return;
  }
  $("account-cards").innerHTML = state.platforms.map((item) => {
    const action = item.name === "youtube"
      ? `<a class="btn primary" href="/api/oauth/youtube/start?account=${encodeURIComponent(account)}">前往 Google 授权</a>`
      : `<button type="button" class="btn primary" data-login="${item.name}">扫码登录</button>`;
    return `
      <article class="card">
        <h3>${escapeHtml(item.label)}</h3>
        <p>${item.logged_in ? "本机已有登录态" : "尚未登录"} · ${item.method === "youtube-data-api" ? "官方接口" : "浏览器"}</p>
        ${action}
        <button type="button" class="btn ghost" data-check="${item.name}">重新检查</button>
      </article>
    `;
  }).join("");
}

async function startLogin(platform) {
  const account = $("account-name").value.trim() || "default";
  const label = (state.platforms.find((item) => item.name === platform) || {}).label || platform;
  try {
    const session = await api(`/api/platforms/${platform}/login`, {
      method: "POST",
      body: JSON.stringify({ account }),
    });
    $("qr-title").textContent = `${label}扫码登录`;
    $("qr-text").textContent = "若二维码被 App 判定异常，请改用有头浏览器或在设置里填写 CDP 地址，附着已经打开的 Chrome。";
    $("qr-image").removeAttribute("src");
    $("qr-dialog").showModal();
    pollLogin(session.session_id);
  } catch (error) {
    toast(error.message);
  }
}

function pollLogin(sessionId) {
  clearInterval(state.loginTimer);
  const tick = async () => {
    try {
      const record = await api(`/api/platforms/login/${sessionId}`);
      $("qr-image").src = `/api/platforms/login/${sessionId}/qr?ts=${Date.now()}`;
      if (record.status === "success") {
        clearInterval(state.loginTimer);
        $("qr-dialog").close();
        toast("登录态已保存。");
        loadPlatforms();
      } else if (record.status === "error") {
        clearInterval(state.loginTimer);
        toast(record.error || "登录失败");
      }
    } catch (error) {
      if (!String(error.message).includes("二维码")) toast(error.message);
    }
  };
  tick();
  state.loginTimer = setInterval(tick, 2000);
}

function rememberField(id, value) {
  const input = $(id);
  if (!input || input.dataset.dirty === "1" || document.activeElement === input) return;
  input.value = value || "";
}

async function fillSettings() {
  const saveButton = $("settings-form").querySelector("button[type=submit]");
  try {
    state.settings = await api("/api/settings");
  } catch (error) {
    toast(error.message);
    return;
  }
  const data = state.settings;
  rememberField("llm-base", data.llm_base_url);
  rememberField("llm-model", data.llm_model);
  if ($("stock-default").dataset.dirty !== "1") $("stock-default").value = data.stock_provider || "pexels";
  rememberField("ai-base", data.visual_ai_base_url);
  rememberField("yt-id", data.youtube_client_id);
  rememberField("yt-redirect", data.youtube_redirect_uri);
  rememberField("cdp-url", data.upload_cdp_url);
  if (document.activeElement !== $("upload-headless") && $("upload-headless").dataset.dirty !== "1") {
    $("upload-headless").checked = Boolean(data.upload_headless);
  }
  hintSecret($("llm-key"), data.llm_api_key);
  hintSecret($("pexels-key"), data.pexels_api_key);
  hintSecret($("pixabay-key"), data.pixabay_api_key);
  hintSecret($("ai-key"), data.visual_ai_api_key);
  hintSecret($("yt-secret"), data.youtube_client_secret);
  const envNotes = [];
  if (data.llm_api_key?.from_env) envNotes.push("大模型密钥来自环境变量");
  $("settings-note").textContent = envNotes.join("；");
  state.settingsReady = true;
  saveButton.disabled = false;
}

function hintSecret(input, meta) {
  if (input.dataset.dirty === "1" || document.activeElement === input) return;
  input.value = "";
  input.placeholder = meta?.configured ? `已配置 ${meta.hint}，留空不修改` : "未配置";
}

function secretValue(input) {
  const value = input.value.trim();
  return value ? value : undefined;
}

async function saveSettings(event) {
  event.preventDefault();
  if (!state.settingsReady) {
    toast("设置还在读取，请稍后再保存。");
    return;
  }
  const payload = {
    llm_base_url: $("llm-base").value.trim(),
    llm_model: $("llm-model").value.trim(),
    stock_provider: $("stock-default").value,
    visual_ai_base_url: $("ai-base").value.trim(),
    youtube_client_id: $("yt-id").value.trim(),
    youtube_redirect_uri: $("yt-redirect").value.trim(),
    upload_cdp_url: $("cdp-url").value.trim(),
    upload_headless: $("upload-headless").checked,
  };
  const secrets = {
    llm_api_key: secretValue($("llm-key")),
    pexels_api_key: secretValue($("pexels-key")),
    pixabay_api_key: secretValue($("pixabay-key")),
    visual_ai_api_key: secretValue($("ai-key")),
    youtube_client_secret: secretValue($("yt-secret")),
  };
  Object.entries(secrets).forEach(([key, value]) => {
    if (value !== undefined) payload[key] = value;
  });
  try {
    state.settings = await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
    $("settings-form").querySelectorAll("[data-dirty]").forEach((node) => {
      delete node.dataset.dirty;
    });
    toast("设置已保存。");
    fillSettings();
  } catch (error) {
    toast(error.message);
  }
}

async function loadHealth() {
  try {
    const health = await api("/api/health");
    const pill = $("health-pill");
    pill.textContent = health.ffmpeg ? "ffmpeg 可用" : "缺少 ffmpeg";
    pill.classList.toggle("ok", health.ffmpeg);
    pill.classList.toggle("bad", !health.ffmpeg);
    $("version-pill").textContent = health.version || "";
  } catch {
    $("health-pill").textContent = "服务未响应";
  }
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
}

function bind() {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.onclick = () => showView(btn.dataset.view);
  });
  platformChecks($("platform-picks"), "create-platform");
  $("publish").onchange = () => $("publish-box").classList.toggle("hidden", !$("publish").checked);
  $("create-form").onsubmit = (event) => {
    event.preventDefault();
    createJob(false);
  };
  $("demo-btn").onclick = () => createJob(true);
  $("refresh-jobs").onclick = () => loadJobs().catch((error) => toast(error.message));
  $("settings-form").onsubmit = saveSettings;
  $("settings-form").querySelector("button[type=submit]").disabled = true;
  $("settings-form").querySelectorAll("input, select, textarea").forEach((node) => {
    node.addEventListener("input", () => {
      node.dataset.dirty = "1";
    });
    node.addEventListener("change", () => {
      node.dataset.dirty = "1";
    });
  });
  $("account-name").onchange = () => loadPlatforms();
  $("account-cards").onclick = (event) => {
    const login = event.target.closest("[data-login]");
    const check = event.target.closest("[data-check]");
    if (login) startLogin(login.dataset.login);
    if (check) {
      const account = $("account-name").value.trim() || "default";
      api(`/api/platforms/${check.dataset.check}/check?account=${encodeURIComponent(account)}`, { method: "POST" })
        .then((data) => {
          toast(data.logged_in ? "登录有效。" : "还没有可用的登录态。");
          loadPlatforms();
        })
        .catch((error) => toast(error.message));
    }
  };
  document.body.addEventListener("click", (event) => {
    const job = event.target.closest(".job");
    if (!job) return;
    state.selected = job.dataset.id;
    showView("jobs");
    renderJobs();
    renderDetail();
  });
  const params = new URLSearchParams(location.search);
  if (params.get("youtube") === "ok") toast("YouTube 授权已保存。");
  if (params.get("youtube") === "error") toast("YouTube 授权没有完成。");
}

bind();
loadHealth();
loadJobs().catch((error) => toast(error.message));
