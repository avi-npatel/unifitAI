import { drawBar, plateStrip, describePlates } from "./plates.js";
import { createPush, PushError } from "./push.js";

const $ = (selector, root = document) => root.querySelector(selector);
const form = $("#profile-form");

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const WEEKDAYS_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const GOALS = { hypertrophy: "build muscle", strength: "get stronger", fat_loss: "lose fat" };
const EQUIPMENT = { gym: "a full gym", dumbbell: "dumbbells", bodyweight: "no equipment" };
const PROFILE_KEY = "unifit.profile";

const EXAMPLE = {
  age: 21, heightFt: 5, heightIn: 10, weight: 165, sex: "male", experience: "beginner",
  goal: "hypertrophy", days: "4", minutes: 60, equipment: "gym", focus: ["arms"],
};

let plan = null;
let selectedDay = 1;
let toastTimer = null;

// ---- small helpers -------------------------------------------------------------------------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  node.append(...children.filter((c) => c != null));
  return node;
}

const storage = {
  get(key) { try { return JSON.parse(localStorage.getItem(key)); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* optional */ } },
};

function formatRest(seconds) {
  if (seconds < 120 && seconds % 60 !== 0) return `${seconds} sec`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes} min ${rest} sec` : `${minutes} min`;
}

function formatLoad(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function setStatus(node, message, tone = "") {
  node.textContent = message;
  if (tone) node.dataset.tone = tone;
  else delete node.dataset.tone;
}

function showToast(title, body) {
  const toast = $("#toast");
  toast.replaceChildren(el("strong", { text: title }), el("span", { text: body || "" }));
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 8000);
}

// ---- form ----------------------------------------------------------------------------------

function radio(name) {
  const checked = form.querySelector(`input[name="${name}"]:checked`);
  return checked ? checked.value : "";
}

function setRadio(name, value) {
  const input = form.querySelector(`input[name="${name}"][value="${value}"]`);
  if (input) input.checked = true;
}

function focusValues() {
  return [...form.querySelectorAll('input[name="focus"]:checked')].map((box) => box.value);
}

function limitFocus() {
  const boxes = [...form.querySelectorAll('input[name="focus"]')];
  const full = boxes.filter((b) => b.checked).length >= 2;
  boxes.forEach((box) => { box.disabled = full && !box.checked; });
}

function fillForm(values) {
  $("#age").value = values.age ?? "";
  $("#height-ft").value = values.heightFt ?? "";
  $("#height-in").value = values.heightIn ?? "";
  $("#weight").value = values.weight ?? "";
  if (values.sex) setRadio("sex", values.sex);
  if (values.experience) setRadio("experience", values.experience);
  setRadio("goal", values.goal || "hypertrophy");
  setRadio("days_per_week", values.days || "3");
  setRadio("equipment", values.equipment || "gym");
  $("#session").value = values.minutes || 45;
  $("#session-out").textContent = `${$("#session").value} min`;
  form.querySelectorAll('input[name="focus"]').forEach((box) => {
    box.checked = (values.focus || []).includes(box.value);
  });
  limitFocus();
}

function currentValues() {
  return {
    age: $("#age").value, heightFt: $("#height-ft").value, heightIn: $("#height-in").value,
    weight: $("#weight").value, sex: radio("sex"), experience: radio("experience"),
    goal: radio("goal"), days: radio("days_per_week"), equipment: radio("equipment"),
    minutes: $("#session").value, focus: focusValues(),
  };
}

function clearErrors() {
  form.querySelectorAll(".error").forEach((node) => { node.hidden = true; node.textContent = ""; });
  form.querySelectorAll("[data-invalid]").forEach((node) => node.removeAttribute("data-invalid"));
  form.querySelectorAll("[aria-invalid]").forEach((node) => node.removeAttribute("aria-invalid"));
}

function showError(key, message) {
  const note = $(`#err-${key}`);
  if (!note) return;
  note.textContent = message;
  note.hidden = false;
  const field = note.closest(".field");
  if (field) field.dataset.invalid = "true";
  const input = field && field.querySelector("input");
  if (input && input.type !== "radio") input.setAttribute("aria-invalid", "true");
}

/** Mirrors the server's rules so most mistakes are caught before a request is sent. */
function buildPayload() {
  const values = currentValues();
  const errors = {};
  const age = Number(values.age);
  const weight = Number(values.weight);
  const feet = Number(values.heightFt);
  const inches = Number(values.heightIn || 0);
  const height = feet * 12 + inches;

  if (values.age === "") errors.age = "Enter your age.";
  else if (!Number.isInteger(age) || age < 14 || age > 90) errors.age = "Your age should be a whole number from 14 to 90.";

  if (values.heightFt === "") errors.height_in = "Enter your height in feet and inches.";
  else if (!(height >= 48 && height <= 84) || inches < 0 || inches >= 12) errors.height_in = "Your height should be between 4 ft 0 in and 7 ft 0 in.";

  if (values.weight === "") errors.weight_lb = "Enter your weight in pounds.";
  else if (!(weight >= 70 && weight <= 500)) errors.weight_lb = "Your weight should be between 70 and 500 pounds.";

  if (!values.sex) errors.sex = "Choose an option.";
  if (!values.experience) errors.experience = "Choose your experience level.";

  const payload = {
    age, height_in: height, weight_lb: weight, sex: values.sex, experience: values.experience,
    goal: values.goal, days_per_week: Number(values.days), equipment: values.equipment,
    session_minutes: Number(values.minutes), focus: values.focus,
  };
  return { payload, errors, values };
}

async function onSubmit(event) {
  event.preventDefault();
  clearErrors();
  const status = $("#form-status");
  setStatus(status, "");

  const { payload, errors, values } = buildPayload();
  if (Object.keys(errors).length) {
    Object.entries(errors).forEach(([key, message]) => showError(key, message));
    const first = form.querySelector("[data-invalid] input");
    if (first) first.focus();
    setStatus(status, "Fix the highlighted answers and try again.", "error");
    return;
  }

  const button = $("#build");
  button.disabled = true;
  button.textContent = "Building";
  try {
    const response = await fetch("/api/routine", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      Object.entries(data.fields || {}).forEach(([key, message]) => showError(key, message));
      setStatus(status, data.error || "The server couldn't build a plan.", "error");
      return;
    }
    storage.set(PROFILE_KEY, values);
    plan = data;
    renderPlan();
    await syncReminders();
    $("#plan").scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    $("#plan").focus({ preventScroll: true });
  } catch {
    setStatus(status, "Couldn't reach the server. Check that it's running and try again.", "error");
  } finally {
    button.disabled = false;
    button.textContent = "Build my plan";
  }
}

// ---- plan ----------------------------------------------------------------------------------

function trainingDays() {
  return plan.week.filter((slot) => slot.day !== null);
}

function renderPlan() {
  $("#plan-empty").hidden = true;
  $("#plan-result").hidden = false;

  const { summary, profile } = plan;
  $("#summary").textContent =
    `${summary.days_per_week} days a week, ${summary.split.toLowerCase()}, for someone aiming to ${GOALS[summary.goal]} ` +
    `with ${EQUIPMENT[summary.equipment]}. About ${profile.session_minutes} minutes a session.`;

  const week = $("#week");
  week.replaceChildren();
  plan.week.forEach((slot) => {
    if (slot.day === null) {
      week.append(el("div", { class: "cell" }, el("strong", { text: WEEKDAYS[slot.weekday] }), "Rest"));
      return;
    }
    const tab = el("button", {
      class: "cell", type: "button", role: "tab", id: `tab-${slot.day}`,
      "aria-controls": "day-panel", "aria-label": `${WEEKDAYS_LONG[slot.weekday]}, day ${slot.day}`,
    }, el("strong", { text: WEEKDAYS[slot.weekday] }), `Day ${slot.day}`);
    tab.dataset.day = String(slot.day);
    tab.addEventListener("click", () => selectDay(slot.day));
    tab.addEventListener("keydown", onTabKey);
    week.append(tab);
  });

  const notes = $("#notes");
  notes.replaceChildren(...plan.tips.map((tip) => el("p", { text: tip })));

  selectDay(1, { animate: true });
}

function onTabKey(event) {
  const days = trainingDays().map((slot) => slot.day);
  const index = days.indexOf(selectedDay);
  let next = null;
  if (event.key === "ArrowRight") next = days[(index + 1) % days.length];
  else if (event.key === "ArrowLeft") next = days[(index - 1 + days.length) % days.length];
  else if (event.key === "Home") next = days[0];
  else if (event.key === "End") next = days[days.length - 1];
  if (next === null) return;
  event.preventDefault();
  selectDay(next);
  $(`#tab-${next}`).focus();
}

function selectDay(dayNumber, { animate = true } = {}) {
  selectedDay = dayNumber;
  const day = plan.days[dayNumber - 1];

  $("#week").querySelectorAll("button.cell").forEach((tab) => {
    const active = Number(tab.dataset.day) === dayNumber;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  });

  const panel = $("#day-panel");
  panel.setAttribute("aria-labelledby", `tab-${dayNumber}`);
  const slot = plan.week.find((s) => s.day === dayNumber);
  panel.replaceChildren(
    el("div", { class: "day-head" },
      el("h3", { text: day.name }),
      el("p", { text: `${WEEKDAYS_LONG[slot.weekday]}. About ${day.estimated_minutes} minutes: ${day.muscles.join(", ")}.` }),
    ),
    el("ol", { class: "lifts" }, ...day.exercises.map(liftRow)),
  );

  loadBar(day, animate);
}

function setsLine(exercise) {
  const rest = `rest ${formatRest(exercise.rest_seconds)}`;
  if (exercise.kind === "weighted") return `${exercise.sets} sets of ${exercise.reps} reps, ${rest}`;
  const unit = exercise.unit === "sec" ? "seconds" : "reps";
  return `${exercise.sets} sets of ${exercise.reps} ${unit}, ${rest}`;
}

function liftRow(exercise, index) {
  const load = el("div", { class: "lift__load" });
  if (exercise.kind === "weighted") {
    load.append(
      el("span", { class: "lift__num", text: formatLoad(exercise.load_lb) }),
      el("span", { class: "lift__unit", text: "lb" }),
      el("span", { class: "lift__note", text: exercise.load_note }),
    );
  } else {
    load.append(
      el("span", { class: "lift__num", text: exercise.reps }),
      el("span", { class: "lift__unit", text: exercise.unit === "sec" ? "sec" : "reps" }),
      el("span", { class: "lift__note", text: "no weight needed" }),
    );
  }

  const body = el("div", {},
    el("p", { class: "lift__name", text: exercise.name }),
    el("p", { class: "lift__plan", text: setsLine(exercise) }),
    el("p", { class: "lift__cue", text: exercise.cue }),
  );
  if (exercise.plates_per_side) body.append(plateStrip(exercise.plates_per_side));

  return el("li", { class: "lift" }, el("span", { class: "lift__order", text: String(index + 1) }), body, load);
}

/** Shows the first barbell lift of the day on the bar at the top of the page. */
function loadBar(day, animate) {
  const bar = $("#bar");
  const lift = day.exercises.find((e) => e.load_style === "barbell");
  if (!lift) {
    drawBar(bar, [], { animate: false });
    bar.setAttribute("aria-label", "An empty barbell");
    $("#bar-num").textContent = "45";
    $("#bar-unit").textContent = "lb, empty bar";
    const anyWeights = day.exercises.some((e) => e.kind === "weighted");
    $("#bar-lift").textContent = anyWeights
      ? `No barbell lift in ${day.name}. Each exercise lists its own weight below.`
      : `${day.name} needs no weights. Your targets are listed below.`;
    return;
  }
  drawBar(bar, lift.plates_per_side, { animate });
  bar.setAttribute("aria-label", `${lift.name}: ${describePlates(lift.plates_per_side)}`);
  $("#bar-num").textContent = formatLoad(lift.load_lb);
  $("#bar-unit").textContent = "lb on the bar";
  $("#bar-lift").textContent = `${lift.name}: 45 lb bar plus ${formatLoad((lift.load_lb - 45) / 2)} lb each side.`;
}

// ---- reminders -----------------------------------------------------------------------------

const push = createPush({
  onForeground: (n) => showToast(n.title || "UniFit", n.body || ""),
});

function schedule() {
  const days = trainingDays();
  return {
    weekdays: days.map((slot) => slot.weekday),
    dayNames: days.map((slot) => plan.days[slot.day - 1].name),
  };
}

function formatClock(value) {
  const [h, m] = value.split(":").map(Number);
  const suffix = h >= 12 ? "PM" : "AM";
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${suffix}`;
}

function showReminderState() {
  const saved = push.saved;
  $("#push-form").hidden = Boolean(saved);
  $("#push-active").hidden = !saved;
  if (saved) {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const rest = saved.motivation ? " and a short note on rest days" : "";
    $("#push-summary").textContent = `Reminders are on for ${formatClock(saved.reminderTime)} (${zone}) on training days${rest}.`;
  }
}

async function syncReminders() {
  if (push.saved) await push.sync(schedule());
}

async function turnOn() {
  const status = $("#push-status");
  const button = $("#push-on");
  const time = $("#reminder-time").value;
  if (!time) {
    setStatus(status, "Pick a time for your reminders.", "error");
    return;
  }
  button.disabled = true;
  setStatus(status, "Setting up reminders.");
  try {
    await push.enable({ reminderTime: time, motivation: $("#rest-notes").checked }, schedule());
    setStatus(status, "");
    showReminderState();
  } catch (error) {
    setStatus(status, error instanceof PushError ? error.message : "Couldn't turn on reminders.", "error");
  } finally {
    button.disabled = false;
  }
}

async function sendTest() {
  const status = $("#push-status");
  const preview = $("#push-preview");
  setStatus(status, "Sending a test.");
  try {
    const result = await push.test();
    preview.hidden = false;
    if (result.delivered) {
      $("#push-preview-label").textContent = "Sent through Firebase. It should arrive in a moment.";
      setStatus(status, "");
    } else {
      $("#push-preview-label").textContent = "Preview only. Firebase isn't connected to this server, so nothing was delivered.";
      setStatus(status, "");
    }
    $("#push-preview-title").textContent = result.message.title;
    $("#push-preview-body").textContent = result.message.body;
  } catch (error) {
    setStatus(status, error instanceof PushError ? error.message : "Couldn't send the test.", "error");
  }
}

async function turnOff() {
  const status = $("#push-status");
  try {
    await push.disable();
    $("#push-preview").hidden = true;
    setStatus(status, "Reminders are off.", "ok");
  } catch (error) {
    setStatus(status, error instanceof PushError ? error.message : "Couldn't turn off reminders.", "error");
  }
  showReminderState();
}

async function initReminders() {
  const { webPush, mode } = await push.init();
  const notice = $("#push-notice");
  if (!webPush && mode === "dry-run") {
    notice.textContent = "Firebase isn't set up on this server, so reminders run as a preview: the schedule is saved and tests show on screen, but nothing reaches your phone.";
    notice.hidden = false;
  } else if (webPush && mode === "dry-run") {
    notice.textContent = "The browser side of Firebase is set up, but the server has no service account key, so messages are previewed instead of sent.";
    notice.hidden = false;
  }
  showReminderState();
}

// ---- model details -------------------------------------------------------------------------

async function loadModelInfo() {
  const line = $("#model-line");
  try {
    const info = await (await fetch("/api/model-info")).json();
    const pct = Math.round(info.within_10_percent * 100);
    line.textContent =
      `A random forest regressor predicts a working weight from height, weight, age, sex, experience and exercise. ` +
      `It was trained on ${info.rows_train.toLocaleString()} synthetic rows and checked on ${info.rows_test.toLocaleString()} it hadn't seen: ` +
      `R² ${info.r2.toFixed(3)}, an average miss of ${info.mae_lb.toFixed(1)} lb, and ${pct}% of predictions within 10% of the generated weight.`;
  } catch {
    line.textContent = "Model details aren't available right now.";
  }
}

// ---- wire up -------------------------------------------------------------------------------

form.addEventListener("submit", onSubmit);
$("#session").addEventListener("input", (event) => {
  $("#session-out").textContent = `${event.target.value} min`;
});
$("#focus").addEventListener("change", limitFocus);
$("#example").addEventListener("click", () => {
  clearErrors();
  fillForm(EXAMPLE);
  setStatus($("#form-status"), "Example filled in. Press Build my plan.");
});
$("#push-on").addEventListener("click", turnOn);
$("#push-test").addEventListener("click", sendTest);
$("#push-off").addEventListener("click", turnOff);

drawBar($("#bar"), [], { animate: false });
const remembered = storage.get(PROFILE_KEY);
if (remembered) fillForm(remembered);
limitFocus();
loadModelInfo();
initReminders();
