const $ = id => document.getElementById(id);
let config, source, profiles = [], currentProfile = null, activeJob = null, polling = null, toastTimer;
const fmt = seconds => `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${Math.floor(seconds % 60).toString().padStart(2, "0")}`;
function toast(message, error = false) {
  $("toast").textContent = message;
  $("toast").className = `toast${error ? " error" : ""}`;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("toast").hidden = true, error ? 11000 : 5000);
}
async function api(path, options = {}) {
  const headers = { "X-Studio-Token": config?.token ?? "", ...options.headers };
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? response.statusText));
  }
  return response.json();
}
function guarded(id, callback) {
  $(id).addEventListener("click", async () => {
    $(id).disabled = true;
    try { await callback(); } catch (error) { toast(error.message, true); }
    finally { $(id).disabled = !!activeJob && ["generate", "transcribe", "releaseModel"].includes(id); }
  });
}
async function loadSource(key) {
  $("sourceMeta").textContent = "正在分析音频…";
  source = await api(`/api/sources/${key}`);
  $("sourceName").textContent = source.name;
  $("sourceMeta").textContent = `${fmt(source.duration)} · ${(source.sample_rate / 1000).toFixed(1)} kHz · ${source.channels === 1 ? "单声道" : "双声道"}`;
  $("sourcePlayer").src = source.url;
  $("waveEnd").textContent = fmt(source.duration);
  if (source.duration < 32) {
    $("clipStart").value = "0";
    $("clipEnd").value = Math.min(source.duration, 12).toFixed(1);
  }
  $("clipStart").max = source.duration;
  $("clipEnd").max = source.duration;
  drawWave();
}
function drawWave() {
  const canvas = $("waveform"), dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth, height = canvas.clientHeight;
  canvas.width = width * dpr; canvas.height = height * dpr;
  const ctx = canvas.getContext("2d"); ctx.scale(dpr, dpr);
  if (!source) return;
  const start = Number($("clipStart").value) / source.duration * width;
  const end = Number($("clipEnd").value) / source.duration * width;
  ctx.fillStyle = "#b6d58322"; ctx.fillRect(start, 0, Math.max(end - start, 2), height);
  const peaks = source.waveform, stride = Math.max(1, Math.ceil(peaks.length / (width / 3)));
  for (let i = 0; i < peaks.length; i += stride) {
    const x = i / peaks.length * width;
    const h = Math.max(2, Math.pow(Math.min(peaks[i], 1), .55) * height * .9);
    ctx.fillStyle = x >= start && x <= end ? "#d8f8a4" : "#657951";
    ctx.fillRect(x, (height - h) / 2, 1.5, h);
  }
  ctx.strokeStyle = "#d8f8a4"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(start, 0); ctx.lineTo(start, height); ctx.moveTo(end, 0); ctx.lineTo(end, height); ctx.stroke();
}
async function refreshProfiles(selected) {
  profiles = await api("/api/profiles");
  $("profileCount").textContent = profiles.length;
  $("profiles").replaceChildren();
  if (!profiles.length) $("profiles").add(new Option("尚未建立音色", ""));
  for (const p of profiles) $("profiles").add(new Option(`${p.name} · ${p.duration.toFixed(1)}s`, p.id));
  if (selected) $("profiles").value = selected;
  await selectProfile($("profiles").value);
}
async function selectProfile(key) {
  currentProfile = profiles.find(p => p.id === key) || null;
  $("referencePreview").hidden = !currentProfile;
  $("selectedVoice").textContent = currentProfile?.name || "未选择音色";
  if (currentProfile) {
    $("profileName").value = currentProfile.name;
    $("transcript").value = currentProfile.transcript;
    $("referencePlayer").src = currentProfile.url;
    $("clipMeta").textContent = `${currentProfile.duration.toFixed(1)} 秒 · 24kHz`;
    if (source?.id !== currentProfile.source_id) {
      try { await loadSource(currentProfile.source_id); }
      catch (error) { toast(`原素材不可用，但已保存的参考片段仍可配音。${error.message}`, true); }
    }
    if (source?.id === currentProfile.source_id) {
      $("clipStart").value = currentProfile.start.toFixed(2);
      $("clipEnd").value = currentProfile.end.toFixed(2);
      drawWave();
    }
  }
}
async function saveCurrentProfile() {
  if (!currentProfile) throw new Error("请先截取并保存参考音色。");
  const updated = await api(`/api/profiles/${currentProfile.id}`, {
    method: "PUT", body: {name: $("profileName").value.trim(), transcript: $("transcript").value.trim()}
  });
  profiles = profiles.map(p => p.id === updated.id ? updated : p);
  currentProfile = updated;
  $("selectedVoice").textContent = updated.name;
}
function showResult(job) {
  $("resultPanel").hidden = false;
  const result = job.result;
  $("resultMeta").textContent = `${job.params.mode === "icl" ? "完整克隆" : "快速试音"} · ${result.duration.toFixed(1)} 秒 · ${result.segments} 个片段 · 耗时 ${result.elapsed_seconds.toFixed(0)} 秒`;
  $("resultPlayer").src = result.files.wav;
  $("downloads").replaceChildren();
  for (const [key, label] of [["wav", "WAV 音频"], ["mp3", "MP3 音频"], ["srt", "SRT 字幕"], ["zip", "工程 ZIP"]]) {
    const link = document.createElement("a"); link.href = result.files[key]; link.download = ""; link.textContent = `↓ ${label}`;
    $("downloads").append(link);
  }
}
async function refreshHistory() {
  const jobs = await api("/api/jobs");
  const generations = jobs.filter(j => j.kind === "generate").slice(0, 10);
  const container = $("historyList"); container.replaceChildren();
  if (!generations.length) { const p = document.createElement("p"); p.className = "empty"; p.textContent = "生成的声音，会在这里留下记录。"; container.append(p); }
  const labels = {complete:"已完成", failed:"失败", running:"生成中", queued:"排队中", cancelled:"已取消"};
  for (const job of generations) {
    const row = document.createElement("div"); row.className = "history-item";
    const text = document.createElement("div"), title = document.createElement("strong"), meta = document.createElement("small");
    title.textContent = job.params.text;
    meta.textContent = `${new Date(job.created_at).toLocaleString("zh-CN")} · ${job.params.mode === "icl" ? "完整克隆" : "快速试音"} · ${labels[job.status]}${job.status === "failed" ? ` · ${job.message}` : ""}`;
    text.append(title, meta); row.append(text);
    if (job.status === "complete") {
      const button = document.createElement("button"); button.className = "text-button"; button.textContent = "试听与导出 ↗";
      button.onclick = () => {showResult(job); $("resultPanel").scrollIntoView({behavior:"smooth", block:"center"});}; row.append(button);
    }
    container.append(row);
  }
  return jobs;
}
function setBusy(busy) {
  for (const id of ["generate", "transcribe", "releaseModel"]) $(id).disabled = busy;
}
async function watchJob(id) {
  activeJob = id;
  $("progressPanel").hidden = false;
  $("cancel").disabled = false;
  setBusy(true);
  clearTimeout(polling);
  async function tick() {
    try {
      const job = await api(`/api/jobs/${id}`);
      $("jobMessage").textContent = job.message;
      $("jobProgress").value = job.progress;
      if (job.status === "complete" || job.status === "failed" || job.status === "cancelled") {
        activeJob = null; setBusy(false); $("cancel").disabled = true;
        if (job.status === "failed") toast(job.message, true);
        if (job.status === "complete" && job.kind === "generate") {showResult(job); toast("配音已生成，可以试听和导出了。");}
        if (job.status === "complete" && job.kind === "transcribe") {
          if (currentProfile?.id === job.params.profile_id) {
            $("transcript").value = job.result.text;
            toast("已填入识别草稿，请试听校对后保存。");
          } else toast("原参考片段转写完成；请切回该音色后重新识别。");
        }
        await refreshHistory();
        return;
      }
      polling = setTimeout(tick, 1800);
    } catch (error) {
      $("jobMessage").textContent = "连接暂时中断，正在重新连接…";
      polling = setTimeout(tick, 4000);
    }
  }
  await tick();
}
$("upload").addEventListener("change", async event => {
  const file = event.target.files[0]; if (!file) return;
  try {
    if (file.size > 200 * 1024 * 1024) throw new Error("文件不能超过 200MB。");
    const form = new FormData(); form.append("file", file);
    toast("正在导入本地音频…");
    const result = await api("/api/sources", {method:"POST", body:form});
    await loadSource(result.id);
  } catch (error) {toast(error.message, true);}
  finally {event.target.value = "";}
});
guarded("createProfile", async () => {
  if (!source) throw new Error("请先导入参考音频。");
  const result = await api("/api/profiles", {method:"POST", body:{
    source_id:source.id, start:Number($("clipStart").value), end:Number($("clipEnd").value),
    name:$("profileName").value.trim()
  }});
  await refreshProfiles(result.id);
  toast(result.warnings.length ? result.warnings.join(" ") : "参考音色已保存。建议先试听片段，再开始生成。");
});
guarded("saveProfile", async () => {await saveCurrentProfile(); await refreshProfiles(currentProfile.id); toast("音色信息已保存。");});
guarded("transcribe", async () => {
  if (!currentProfile) throw new Error("请先选择参考音色。");
  if (!config.asr_ready) throw new Error("未安装转写模型。请运行 .venv\\Scripts\\python scripts\\download_models.py --asr，或手动填写原文。");
  const job = await api(`/api/profiles/${currentProfile.id}/transcribe`, {method:"POST"});
  await watchJob(job.id);
  $("transcribe").disabled = !!activeJob;
});
guarded("generate", async () => {
  if (!currentProfile) throw new Error("请先在左侧截取或选择参考音色。");
  if (!$("acknowledged").checked) throw new Error("请先勾选音色授权与 AI 合成标识提醒。");
  await saveCurrentProfile();
  const job = await api("/api/generate", {method:"POST", body:{
    profile_id:currentProfile.id, text:$("script").value, mode:$("mode").value,
    language:$("language").value, speed:Number($("speed").value), gap:Number($("gap").value),
    seed:42, acknowledged:true
  }});
  $("resultPanel").hidden = true;
  await watchJob(job.id);
});
guarded("cancel", async () => {if (activeJob) {await api(`/api/jobs/${activeJob}/cancel`, {method:"POST"}); toast("已请求取消，等待当前处理步骤结束。");}});
guarded("releaseModel", async () => {await api("/api/model/unload", {method:"POST"}); toast("模型已释放，不会关闭其他程序。");});
$("usePosition").onclick = () => {
  if (!source) return;
  const start = Math.max(0, Math.min($("sourcePlayer").currentTime, source.duration - 3));
  $("clipStart").value = start.toFixed(1); $("clipEnd").value = Math.min(start + 12, source.duration).toFixed(1); drawWave();
};
$("waveform").onclick = event => {
  if (!source) return;
  const box = event.target.getBoundingClientRect();
  $("sourcePlayer").currentTime = (event.clientX - box.left) / box.width * source.duration;
};
for (const id of ["clipStart", "clipEnd"]) $(id).addEventListener("input", drawWave);
$("profiles").onchange = () => selectProfile($("profiles").value).catch(error => toast(error.message, true));
$("speed").oninput = () => $("speedValue").textContent = `${Number($("speed").value).toFixed(2)}×`;
$("gap").oninput = () => $("gapValue").textContent = `${Number($("gap").value).toFixed(2)} 秒`;
$("script").oninput = () => $("charCount").textContent = $("script").value.length;
$("sampleScript").onclick = () => {
  $("script").value = "这是一段由人工智能合成的配音测试，不是本人录音。\n每一个值得分享的故事，都需要一个有温度的声音。现在，让我们开始今天的内容。";
  $("script").oninput();
};
$("mode").onchange = () => $("modeNote").textContent = $("mode").value === "quick"
  ? "快速模式只提取说话人特征，适合先验证音色。相似度需要你试听判断。"
  : "完整模式同时利用音色与参考语音内容。请确保左侧原文与录音逐字一致；错误原文可能影响发音。";
window.addEventListener("resize", drawWave);
(async function init() {
  try {
    config = await api("/api/config");
    $("modelStatus").textContent = config.model_ready ? "● 本地模型已就绪" : "○ 模型待下载";
    $("script").oninput();
    if (config.sample_available) await loadSource("sample");
    await refreshProfiles();
    const jobs = await refreshHistory();
    const active = jobs.find(j => ["queued","running"].includes(j.status));
    if (active) await watchJob(active.id);
    else {const last = jobs.find(j => j.kind === "generate" && j.status === "complete"); if (last) showResult(last);}
  } catch (error) {toast(error.message, true); $("modelStatus").textContent = "连接失败";}
})();
