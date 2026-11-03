const MAX_SECONDS = 60;
const talk = document.getElementById("talk");
const stop = document.getElementById("stop");
const cancel = document.getElementById("cancel");
const speak = document.getElementById("speak");
const voiceStatus = document.getElementById("voice-status");
const question = document.getElementById("question");

let mediaStream = null;
let recorder = null;
let recognition = null;
let timer = null;
let abortTurn = null;
let chunks = [];

function setVoiceStatus(text) {
  voiceStatus.textContent = text;
}

function stopRecognition() {
  if (recognition) {
    recognition.onresult = null;
    recognition.onerror = null;
    try {
      recognition.stop();
    } catch (_error) {
      /* already stopped */
    }
    recognition = null;
  }
}

function stopTimer() {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
}

function stopRecorder() {
  stopTimer();
  stopRecognition();
  if (recorder && recorder.state !== "inactive") {
    recorder.stop();
  }
  recorder = null;
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }
  document.body.classList.remove("recording");
  talk.hidden = false;
  stop.hidden = true;
}

function startDeviceSpeech() {
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Speech) {
    setVoiceStatus(
      "Recording locally only. Muse Transcribe is closed. Device speech is unavailable here — edit the typed question."
    );
    return;
  }
  recognition = new Speech();
  recognition.lang = "en-US";
  recognition.interimResults = true;
  recognition.continuous = true;
  recognition.onresult = (event) => {
    const parts = [];
    for (const result of event.results) {
      parts.push(result[0].transcript);
    }
    question.value = parts.join(" ").trim();
    setVoiceStatus("Device speech — not Muse Transcribe. Edit before Ask.");
  };
  recognition.onerror = () => {
    setVoiceStatus("Device speech failed. Muse Transcribe is closed. Type the question instead.");
  };
  recognition.start();
}

async function startTalk() {
  try {
    const timeout = new Promise((_, reject) => {
      setTimeout(() => reject(new Error("mic-timeout")), 4000);
    });
    mediaStream = await Promise.race([
      navigator.mediaDevices.getUserMedia({ audio: true }),
      timeout,
    ]);
  } catch (_error) {
    setVoiceStatus("Mic denied or unavailable. Type the question instead. Muse Transcribe stays closed.");
    question.focus();
    return;
  }
  chunks = [];
  recorder = new MediaRecorder(mediaStream);
  recorder.ondataavailable = (event) => {
    if (event.data && event.data.size) {
      chunks.push(event.data);
    }
  };
  recorder.start();
  document.body.classList.add("recording");
  talk.hidden = true;
  stop.hidden = false;
  cancel.hidden = false;
  if (window.museVoiceReady) {
    setVoiceStatus(`Listening up to ${MAX_SECONDS}s. Audio stays on this machine until Stop, then the server calls Muse Transcribe.`);
  } else {
    setVoiceStatus(`Listening up to ${MAX_SECONDS}s. Browser speech is not Muse and may use the browser vendor’s servers. Use typing to avoid speech transmission.`);
    startDeviceSpeech();
  }
  timer = setTimeout(stopTalk, MAX_SECONDS * 1000);
}

function collectClip() {
  const type = recorder && recorder.mimeType ? recorder.mimeType : "audio/webm";
  return new Promise((resolve) => {
    if (!recorder || recorder.state === "inactive") {
      resolve({ pending: chunks.slice(), type });
      return;
    }
    recorder.onstop = () => resolve({ pending: chunks.slice(), type });
    recorder.stop();
  });
}

async function stopTalk() {
  const { pending, type } = await collectClip();
  stopRecorder();
  if (window.museVoiceReady && pending.length) {
    setVoiceStatus("Sending the clip to local /transcribe. Edit before Ask.");
    const blob = new Blob(pending, { type });
    const body = new FormData();
    body.append("audio", blob, type.includes("wav") ? "clip.wav" : "clip.webm");
    try {
      const response = await fetch("/transcribe", { method: "POST", body });
      const data = await response.json();
      if (!response.ok) {
        setVoiceStatus(data.detail || "Muse Transcribe failed. Type instead.");
        question.focus();
        return;
      }
      if (data.transcript) {
        question.value = data.transcript;
      }
      setVoiceStatus("Muse Transcribe returned text. Edit before Ask.");
    } catch (_error) {
      setVoiceStatus("Muse Transcribe could not run. Type instead.");
    }
    question.focus();
    return;
  }
  chunks = [];
  setVoiceStatus("Stopped. Edit the transcript, then Ask. Muse Transcribe is still closed.");
  question.focus();
}

function cancelTurn() {
  stopRecorder();
  if (abortTurn) {
    abortTurn.abort();
    abortTurn = null;
  }
  cancel.hidden = true;
  setVoiceStatus("Turn cancelled. Late results will be ignored. Type or Talk again.");
}

function readAloud(text) {
  if (!window.speechSynthesis || !text) {
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "en-US";
  window.speechSynthesis.speak(utterance);
  setVoiceStatus("Read-aloud is device speech, not Muse.");
}

talk.addEventListener("click", startTalk);
stop.addEventListener("click", stopTalk);
cancel.addEventListener("click", cancelTurn);
speak.addEventListener("click", () => {
  const answer = document.getElementById("summary");
  readAloud(answer ? answer.textContent : "");
});

export function newTurnSignal() {
  if (abortTurn) {
    abortTurn.abort();
  }
  abortTurn = new AbortController();
  cancel.hidden = false;
  return abortTurn.signal;
}

export function turnFinished() {
  abortTurn = null;
  cancel.hidden = true;
  speak.hidden = false;
}

export { cancelTurn };
