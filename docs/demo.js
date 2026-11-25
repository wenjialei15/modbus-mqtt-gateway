"use strict";

const MAX_SAMPLES = 45;
const samples = [];
const chart = document.getElementById("chart");
const context = chart.getContext("2d");
const status = document.getElementById("state");
const pipeline = document.querySelector(".pipeline");
const messages = document.getElementById("messages");
const connection = document.getElementById("connection");
const pause = document.getElementById("pause");
const copy = document.getElementById("copy");
const metricValues = ["voltage", "current", "power", "energy"].map((id) => document.getElementById(id));
const metricDigits = [1, 2, 0, 3];
let online = true;
let running = true;
let tick = 0;
let copyTimeout;

function meterReading(seconds) {
  const voltage = Math.round(2300 + 24 * Math.sin(seconds / 4));
  const current = Math.round(440 + 125 * Math.sin(seconds / 6));
  const power = Math.round(voltage * current * 0.001 * 0.94);
  const energy = 125800 + Math.floor(seconds / 3.6);
  const words = [voltage, current, power, energy >>> 16, energy & 0xffff];
  const signedPower = words[2] >= 0x8000 ? words[2] - 0x10000 : words[2];
  return [words[0] / 10, words[1] / 100, signedPower, (words[3] * 65536 + words[4]) / 1000];
}

function addMessage(type, detail, fault = false) {
  const entry = document.createElement("li");
  const time = document.createElement("time");
  const label = document.createElement("code");
  const body = document.createElement("span");
  const now = new Date();
  time.dateTime = now.toISOString();
  time.textContent = now.toTimeString().slice(0, 8);
  label.textContent = type;
  label.className = "message-type";
  body.textContent = detail;
  entry.classList.toggle("offline", fault);
  entry.append(time, label, body);
  messages.prepend(entry);
  if (messages.children.length > 8) messages.lastElementChild.remove();
}

function showConnection() {
  const stateText = online ? (running ? "在线" : "已暂停") : "电表离线";
  if (status.textContent !== stateText) status.textContent = stateText;
  status.dataset.mode = online ? (running ? "online" : "paused") : "offline";
  pipeline.classList.toggle("is-offline", !online);
  connection.textContent = online ? "断开电表" : "恢复连接";
  connection.classList.toggle("warning", online);
  connection.classList.toggle("repair", !online);
  pause.textContent = running ? "暂停" : "继续";
}

function renderMetrics(reading) {
  metricValues.forEach((element, index) => {
    element.textContent = reading ? reading[index].toFixed(metricDigits[index]) : "—";
  });
}

function addSample() {
  const reading = online ? meterReading(tick) : null;
  tick += 1;
  samples.push(reading ? reading[2] : null);
  if (samples.length > MAX_SAMPLES) samples.shift();
  renderMetrics(reading);
  if (reading) {
    addMessage("telemetry", `${reading[0].toFixed(1)} V · ${reading[1].toFixed(2)} A · ${reading[2]} W`);
  }
  drawChart();
}

function drawChart() {
  if (!context) return;
  const width = chart.clientWidth;
  const height = chart.clientHeight;
  if (width === 0 || height === 0) return;
  const ratio = window.devicePixelRatio || 1;
  chart.width = Math.round(width * ratio);
  chart.height = Math.round(height * ratio);
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  const plot = { left: 43, right: width - 16, top: 18, bottom: height - 35 };
  const x = (index) => plot.left + index * (plot.right - plot.left) / (MAX_SAMPLES - 1);
  const y = (power) => plot.bottom - (power - 550) * (plot.bottom - plot.top) / 800;

  context.font = "11px monospace";
  context.fillStyle = "#55676c";
  context.strokeStyle = "#e2ebe7";
  context.lineWidth = 1;
  for (const value of [550, 750, 950, 1150, 1350]) {
    const lineY = y(value);
    context.beginPath();
    context.moveTo(plot.left, lineY);
    context.lineTo(plot.right, lineY);
    context.stroke();
    context.fillText(String(value), 10, lineY + 4);
  }
  context.textAlign = "left";
  context.fillText("较早", plot.left, height - 12);
  context.textAlign = "right";
  context.fillText("最新", plot.right, height - 12);

  context.strokeStyle = "#087b61";
  context.fillStyle = "#087b61";
  context.lineWidth = 2;
  context.lineJoin = "round";
  context.beginPath();
  let connected = false;
  samples.forEach((power, index) => {
    if (power === null) {
      connected = false;
      return;
    }
    const lineX = x(MAX_SAMPLES - samples.length + index);
    if (connected) context.lineTo(lineX, y(power));
    else context.moveTo(lineX, y(power));
    connected = true;
  });
  context.stroke();
  const newest = samples.at(-1);
  if (newest !== null && newest !== undefined) {
    context.beginPath();
    context.arc(plot.right, y(newest), 3.5, 0, 2 * Math.PI);
    context.fill();
  }
}

function resetDemo() {
  samples.splice(0, samples.length, ...Array.from({ length: 30 }, (_, second) => meterReading(second)[2]));
  messages.replaceChildren();
  online = true;
  running = true;
  tick = 30;
  showConnection();
  addMessage("status", "online · 电表已连接");
  addSample();
}

connection.addEventListener("click", () => {
  online = !online;
  showConnection();
  addMessage("status", online ? "online · 电表已恢复" : "offline · Modbus 连接中断", !online);
  if (running || !online) addSample();
});

pause.addEventListener("click", () => {
  running = !running;
  showConnection();
  if (running) addSample();
});

document.getElementById("reset").addEventListener("click", resetDemo);
copy.addEventListener("click", async () => {
  const command = document.getElementById("command-text");
  try {
    await navigator.clipboard.writeText(command.textContent);
    copy.textContent = "已复制";
  } catch {
    const range = document.createRange();
    range.selectNodeContents(command);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    copy.textContent = "已选中";
  }
  window.clearTimeout(copyTimeout);
  copyTimeout = window.setTimeout(() => { copy.textContent = "复制命令"; }, 1800);
});

new ResizeObserver(drawChart).observe(chart);
resetDemo();
window.setInterval(() => { if (running) addSample(); }, 1000);
