const textInput = document.getElementById("text-input");
const fileInput = document.getElementById("file-input");
const voiceSelect = document.getElementById("voice-select");
const generateBtn = document.getElementById("generate-btn");
const durationEstimate = document.getElementById("duration-estimate");
const lengthWarning = document.getElementById("length-warning");
const errorMessage = document.getElementById("error-message");
const resultEl = document.getElementById("result");
const player = document.getElementById("player");
const downloadLink = document.getElementById("download-link");
const progressContainer = document.getElementById("progress-container");
const progressFill = document.getElementById("progress-fill");
const progressLabel = document.getElementById("progress-label");
const cancelBtn = document.getElementById("cancel-btn");
const cancelledMessage = document.getElementById("cancelled-message");
const previewBtn = document.getElementById("preview-btn");
const previewPlayer = document.getElementById("preview-player");

const WORDS_PER_MINUTE = 140;
const WARNING_THRESHOLD_MINUTES = 6;
const POLL_INTERVAL_MS = 500;
const CUSTOM_VOICE_PREFIX = "custom:";

let currentJobId = null;
let pollTimer = null;

function formatDuration(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds % 60);
  if (minutes === 0) {
    return `~${seconds}s`;
  }
  return `~${minutes} min ${seconds}s`;
}

function updateEstimate() {
  const text = textInput.value.trim();
  const wordCount = text ? text.split(/\s+/).filter(Boolean).length : 0;
  const totalSeconds = (wordCount / WORDS_PER_MINUTE) * 60;

  if (wordCount === 0) {
    durationEstimate.textContent = "";
    lengthWarning.hidden = true;
    return;
  }

  durationEstimate.textContent = `${wordCount} words — estimated audio length: ${formatDuration(totalSeconds)}`;

  if (totalSeconds / 60 > WARNING_THRESHOLD_MINUTES) {
    lengthWarning.hidden = false;
    lengthWarning.textContent =
      `This is fairly long (${formatDuration(totalSeconds)}) — generation may take a little while. ` +
      "Consider trimming if you wanted something closer to 5 minutes.";
  } else {
    lengthWarning.hidden = true;
  }
}

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".txt")) {
    showError("Please upload a .txt file.");
    fileInput.value = "";
    return;
  }
  const reader = new FileReader();
  reader.onload = (e) => {
    textInput.value = e.target.result;
    updateEstimate();
  };
  reader.readAsText(file);
});

textInput.addEventListener("input", updateEstimate);

function showError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = false;
}

function hideError() {
  errorMessage.hidden = true;
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function resetToIdle() {
  stopPolling();
  currentJobId = null;
  progressContainer.hidden = true;
  progressFill.style.width = "0%";
  generateBtn.hidden = false;
  generateBtn.disabled = false;
  generateBtn.textContent = "Generate";
}

async function pollStatus() {
  if (!currentJobId) return;

  let data;
  try {
    const response = await fetch(`/status/${currentJobId}`);
    data = await response.json();
  } catch (err) {
    resetToIdle();
    showError("Lost connection to the server while generating — check your connection and try again.");
    return;
  }

  if (data.status === "running" || data.status === "cancelling") {
    progressFill.style.width = `${data.progress}%`;
    progressLabel.textContent =
      data.status === "cancelling" ? "Cancelling..." : `Generating... ${data.progress}%`;
    if (data.status === "cancelling") {
      cancelBtn.disabled = true;
    }
    pollTimer = setTimeout(pollStatus, POLL_INTERVAL_MS);
    return;
  }

  if (data.status === "done") {
    resetToIdle();
    player.src = data.audio_url;
    downloadLink.href = data.audio_url;
    resultEl.hidden = false;
    return;
  }

  if (data.status === "cancelled") {
    resetToIdle();
    cancelledMessage.hidden = false;
    return;
  }

  if (data.status === "error") {
    resetToIdle();
    showError(data.error || "Something went wrong — please try again.");
    return;
  }
}

generateBtn.addEventListener("click", async () => {
  hideError();
  cancelledMessage.hidden = true;
  resultEl.hidden = true;

  const text = textInput.value.trim();
  if (!text) {
    showError("Please enter some text first.");
    return;
  }

  const formData = new FormData();
  formData.append("text", text);
  formData.append("voice", voiceSelect.value);

  generateBtn.hidden = true;
  progressContainer.hidden = false;
  progressFill.style.width = "0%";
  progressLabel.textContent = "Generating... 0%";
  cancelBtn.disabled = false;

  try {
    const response = await fetch("/synthesize", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();

    if (!response.ok) {
      resetToIdle();
      showError(data.error || "Something went wrong — please try again.");
      return;
    }

    currentJobId = data.job_id;
    pollStatus();
  } catch (err) {
    resetToIdle();
    showError("Couldn't reach the server — check your connection and try again.");
  }
});

function resetPreviewButton() {
  previewBtn.textContent = "▶ Preview";
  previewBtn.disabled = false;
}

function sampleUrlForVoice(voiceValue) {
  if (voiceValue.startsWith(CUSTOM_VOICE_PREFIX)) {
    return `/custom-voice/sample/${voiceValue.slice(CUSTOM_VOICE_PREFIX.length)}`;
  }
  return `/static/voice_samples/${voiceValue}.mp3`;
}

previewBtn.addEventListener("click", () => {
  const isPlayingThisVoice =
    !previewPlayer.paused && previewPlayer.dataset.voice === voiceSelect.value;

  if (isPlayingThisVoice) {
    previewPlayer.pause();
    resetPreviewButton();
    return;
  }

  previewPlayer.pause();
  previewPlayer.dataset.voice = voiceSelect.value;
  previewPlayer.src = sampleUrlForVoice(voiceSelect.value);
  previewBtn.textContent = "⏸ Playing...";
  previewPlayer.play().catch(() => {
    resetPreviewButton();
    showError("Couldn't play the preview for this voice.");
  });
});

previewPlayer.addEventListener("ended", resetPreviewButton);
previewPlayer.addEventListener("error", () => {
  if (previewPlayer.dataset.voice) {
    resetPreviewButton();
    showError("Preview sample not found for this voice.");
  }
});

voiceSelect.addEventListener("change", () => {
  previewPlayer.pause();
  resetPreviewButton();
});

cancelBtn.addEventListener("click", async () => {
  if (!currentJobId) return;

  const confirmed = window.confirm(
    "Cancel generation? The audio generated so far will be discarded — you'll need to generate again."
  );
  if (!confirmed) return;

  cancelBtn.disabled = true;
  progressLabel.textContent = "Cancelling...";

  try {
    await fetch(`/cancel/${currentJobId}`, { method: "POST" });
  } catch (err) {
    // Polling will keep running and surface any resulting state; nothing else to do here.
  }
});

// --- Custom voice cloning ---

const customVoiceNameInput = document.getElementById("custom-voice-name");
const customVoiceFileInput = document.getElementById("custom-voice-file");
const recordBtn = document.getElementById("record-btn");
const recordStatus = document.getElementById("record-status");
const saveVoiceBtn = document.getElementById("save-voice-btn");
const customVoiceErrorEl = document.getElementById("custom-voice-error");
const customVoiceListEl = document.getElementById("custom-voice-list");
const customVoiceGroup = document.getElementById("custom-voice-group");

let recordedBlob = null;
let mediaRecorder = null;
let mediaChunks = [];

function showCustomVoiceError(message) {
  customVoiceErrorEl.textContent = message;
  customVoiceErrorEl.hidden = false;
}

function hideCustomVoiceError() {
  customVoiceErrorEl.hidden = true;
}

function updateSaveVoiceEnabled() {
  const hasName = customVoiceNameInput.value.trim().length > 0;
  const hasSample = Boolean(recordedBlob || customVoiceFileInput.files[0]);
  saveVoiceBtn.disabled = !(hasName && hasSample);
}

customVoiceNameInput.addEventListener("input", updateSaveVoiceEnabled);
customVoiceFileInput.addEventListener("change", () => {
  if (customVoiceFileInput.files[0]) {
    recordedBlob = null;
    recordStatus.hidden = true;
  }
  updateSaveVoiceEnabled();
});

recordBtn.addEventListener("click", async () => {
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    return;
  }

  hideCustomVoiceError();
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) mediaChunks.push(e.data);
    };
    mediaRecorder.onstop = () => {
      recordedBlob = new Blob(mediaChunks, { type: "audio/webm" });
      customVoiceFileInput.value = "";
      stream.getTracks().forEach((track) => track.stop());
      recordBtn.textContent = "🎙 Record";
      recordStatus.hidden = false;
      recordStatus.textContent = "Recorded — ready to save.";
      updateSaveVoiceEnabled();
    };
    mediaRecorder.start();
    recordBtn.textContent = "⏹ Stop";
    recordStatus.hidden = false;
    recordStatus.textContent = "Recording... speak clearly for 10-30 seconds, then click Stop.";
  } catch (err) {
    showCustomVoiceError(
      "Couldn't access your microphone — check browser permissions, or upload a file instead."
    );
  }
});

saveVoiceBtn.addEventListener("click", async () => {
  hideCustomVoiceError();
  const name = customVoiceNameInput.value.trim();
  const file = customVoiceFileInput.files[0] || recordedBlob;
  if (!name || !file) return;

  const formData = new FormData();
  formData.append("name", name);
  formData.append("sample", file, file.name || "sample.webm");

  saveVoiceBtn.disabled = true;
  saveVoiceBtn.textContent = "Saving...";

  try {
    const response = await fetch("/custom-voice/add", { method: "POST", body: formData });
    const data = await response.json();

    if (!response.ok) {
      showCustomVoiceError(data.error || "Couldn't save that voice.");
      return;
    }

    customVoiceNameInput.value = "";
    customVoiceFileInput.value = "";
    recordedBlob = null;
    recordStatus.hidden = true;
    await loadCustomVoices();
  } catch (err) {
    showCustomVoiceError("Couldn't reach the server — check your connection and try again.");
  } finally {
    saveVoiceBtn.textContent = "Save Voice";
    updateSaveVoiceEnabled();
  }
});

function renderCustomVoiceOptions(voices) {
  customVoiceGroup.innerHTML = "";
  customVoiceGroup.hidden = voices.length === 0;
  for (const voice of voices) {
    const option = document.createElement("option");
    option.value = `${CUSTOM_VOICE_PREFIX}${voice.id}`;
    option.textContent = voice.name;
    customVoiceGroup.appendChild(option);
  }
}

function renderCustomVoiceList(voices) {
  customVoiceListEl.innerHTML = "";

  if (voices.length === 0) {
    const empty = document.createElement("li");
    empty.className = "custom-voice-empty";
    empty.textContent = "No custom voices saved yet.";
    customVoiceListEl.appendChild(empty);
    return;
  }

  for (const voice of voices) {
    const item = document.createElement("li");
    item.className = "custom-voice-item";

    const nameSpan = document.createElement("span");
    nameSpan.className = "custom-voice-name";
    nameSpan.textContent = voice.name;

    const previewVoiceBtn = document.createElement("button");
    previewVoiceBtn.type = "button";
    previewVoiceBtn.className = "custom-voice-btn";
    previewVoiceBtn.textContent = "▶ Preview";
    previewVoiceBtn.addEventListener("click", () => {
      previewPlayer.pause();
      previewPlayer.dataset.voice = `${CUSTOM_VOICE_PREFIX}${voice.id}`;
      previewPlayer.src = `/custom-voice/sample/${voice.id}`;
      previewPlayer.play().catch(() => {
        showError("Couldn't play this voice sample.");
      });
    });

    const deleteVoiceBtn = document.createElement("button");
    deleteVoiceBtn.type = "button";
    deleteVoiceBtn.className = "custom-voice-btn custom-voice-delete";
    deleteVoiceBtn.textContent = "Delete";
    deleteVoiceBtn.addEventListener("click", async () => {
      const confirmed = window.confirm(`Delete the voice "${voice.name}"? This can't be undone.`);
      if (!confirmed) return;
      try {
        await fetch(`/custom-voice/delete/${voice.id}`, { method: "POST" });
        await loadCustomVoices();
      } catch (err) {
        showCustomVoiceError("Couldn't delete that voice — check your connection and try again.");
      }
    });

    item.appendChild(nameSpan);
    item.appendChild(previewVoiceBtn);
    item.appendChild(deleteVoiceBtn);
    customVoiceListEl.appendChild(item);
  }
}

async function loadCustomVoices() {
  try {
    const response = await fetch("/custom-voice/list");
    const data = await response.json();
    if (!response.ok) {
      showCustomVoiceError(data.error || "Couldn't load your saved voices.");
      return;
    }
    renderCustomVoiceOptions(data.voices);
    renderCustomVoiceList(data.voices);
  } catch (err) {
    showCustomVoiceError("Couldn't load your saved voices — check your connection.");
  }
}

loadCustomVoices();
