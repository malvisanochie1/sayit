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
const cloneAudioInput = document.getElementById("clone-audio-input");
const cloneTextInput = document.getElementById("clone-text-input");
const cloneStyleSelect = document.getElementById("clone-style-select");
const cloneConsent = document.getElementById("clone-consent");
const cloneGenerateBtn = document.getElementById("clone-generate-btn");
const cloneTextEstimate = document.getElementById("clone-text-estimate");
const cloneProgressContainer = document.getElementById("clone-progress-container");
const cloneProgressFill = document.getElementById("clone-progress-fill");
const cloneProgressLabel = document.getElementById("clone-progress-label");
const cloneErrorMessage = document.getElementById("clone-error-message");
const cloneRetryBtn = document.getElementById("clone-retry-btn");
const cloneResultEl = document.getElementById("clone-result");
const clonePlayer = document.getElementById("clone-player");
const cloneDownloadLink = document.getElementById("clone-download-link");

const WORDS_PER_MINUTE = 140;
const WARNING_THRESHOLD_MINUTES = 6;
const POLL_INTERVAL_MS = 500;
const CLONE_POLL_INTERVAL_MS = 1000;
const CLONE_MAX_WORDS = 50;

let currentJobId = null;
let pollTimer = null;
let currentCloneJobId = null;
let clonePollTimer = null;

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

function updateCloneEstimate() {
  const text = cloneTextInput.value.trim();
  const wordCount = text ? text.split(/\s+/).filter(Boolean).length : 0;

  if (wordCount === 0) {
    cloneTextEstimate.textContent = "";
    return;
  }

  cloneTextEstimate.textContent = `${wordCount}/${CLONE_MAX_WORDS} words`;
  if (wordCount > CLONE_MAX_WORDS) {
    cloneTextEstimate.textContent += " - shorten this before cloning.";
  }
}

cloneTextInput.addEventListener("input", updateCloneEstimate);

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
  previewPlayer.src = `/static/voice_samples/${voiceSelect.value}.mp3`;
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


function showCloneError(message, allowRetry = true) {
  cloneErrorMessage.textContent = message;
  cloneErrorMessage.hidden = false;
  cloneRetryBtn.hidden = !allowRetry;
}

function hideCloneError() {
  cloneErrorMessage.hidden = true;
  cloneRetryBtn.hidden = true;
}

function stopClonePolling() {
  if (clonePollTimer) {
    clearTimeout(clonePollTimer);
    clonePollTimer = null;
  }
}

function resetCloneToIdle() {
  stopClonePolling();
  currentCloneJobId = null;
  cloneProgressContainer.hidden = true;
  cloneProgressFill.style.width = "0%";
  cloneGenerateBtn.hidden = false;
  cloneGenerateBtn.disabled = false;
  cloneGenerateBtn.textContent = "Generate cloned voice";
}

function getCloneWordCount() {
  const text = cloneTextInput.value.trim();
  return text ? text.split(/\s+/).filter(Boolean).length : 0;
}

function validateCloneInputs() {
  if (!cloneAudioInput.files.length) {
    showCloneError("Please upload a short voice sample first.", false);
    return false;
  }

  if (!cloneConsent.checked) {
    showCloneError("Please confirm you have permission to use this voice sample.", false);
    return false;
  }

  if (!cloneTextInput.value.trim()) {
    showCloneError("Please enter the text you want to hear in the cloned voice.", false);
    return false;
  }

  if (getCloneWordCount() > CLONE_MAX_WORDS) {
    showCloneError("Please keep cloned-voice text to 50 words or fewer.", false);
    return false;
  }

  return true;
}

async function pollCloneStatus() {
  if (!currentCloneJobId) return;

  let data;
  try {
    const response = await fetch(`/clone-status/${currentCloneJobId}`);
    data = await response.json();
  } catch (err) {
    resetCloneToIdle();
    showCloneError("Lost connection while cloning. Something went wrong, tap to retry.");
    return;
  }

  if (data.status === "running") {
    cloneProgressFill.style.width = `${data.progress || 5}%`;
    cloneProgressLabel.textContent =
      data.message || "Cloning your voice... this can take up to a couple of minutes";
    clonePollTimer = setTimeout(pollCloneStatus, CLONE_POLL_INTERVAL_MS);
    return;
  }

  if (data.status === "done") {
    resetCloneToIdle();
    clonePlayer.src = data.audio_url;
    cloneDownloadLink.href = data.audio_url;
    cloneResultEl.hidden = false;
    return;
  }

  if (data.status === "error") {
    resetCloneToIdle();
    showCloneError(data.error || "Something went wrong, tap to retry.");
  }
}

async function startCloneJob() {
  hideCloneError();
  cloneResultEl.hidden = true;
  updateCloneEstimate();

  if (!validateCloneInputs()) {
    return;
  }

  const formData = new FormData();
  formData.append("audio", cloneAudioInput.files[0]);
  formData.append("text", cloneTextInput.value.trim());
  formData.append("style", cloneStyleSelect.value);
  formData.append("consent", "true");

  cloneGenerateBtn.hidden = true;
  cloneProgressContainer.hidden = false;
  cloneProgressFill.style.width = "5%";
  cloneProgressLabel.textContent =
    "Cloning your voice... this can take up to a couple of minutes";

  try {
    const response = await fetch("/clone-voice", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();

    if (!response.ok) {
      resetCloneToIdle();
      showCloneError(data.error || "Something went wrong, tap to retry.", response.status >= 500);
      return;
    }

    currentCloneJobId = data.job_id;
    pollCloneStatus();
  } catch (err) {
    resetCloneToIdle();
    showCloneError("Couldn't reach the server. Something went wrong, tap to retry.");
  }
}

cloneGenerateBtn.addEventListener("click", startCloneJob);
cloneRetryBtn.addEventListener("click", startCloneJob);
