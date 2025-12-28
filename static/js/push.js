// Reminder opt-in. With Firebase configured on the server this registers a real FCM web push
// token. Without it, the same flow runs against a placeholder token and the server records what
// it would have sent, so the feature can be demonstrated end to end.

const STORAGE_KEY = "unifit.push";

export class PushError extends Error {}

function readSaved() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}

function writeSaved(value) {
  try {
    if (value) localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable (private mode); reminders still work for this visit.
  }
}

async function call(method, path, body) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new PushError("Couldn't reach the server. Check that it's running and try again.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.fields ? Object.values(data.fields).join(" ") : "";
    throw new PushError([data.error, detail].filter(Boolean).join(" ") || "The server rejected that request.");
  }
  return data;
}

function placeholderToken() {
  const id = (globalThis.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Math.random()).slice(2);
  return `preview-${id}`;
}

function browserSupportsPush() {
  return "Notification" in window && "serviceWorker" in navigator && "PushManager" in window;
}

export function createPush({ onForeground }) {
  let config = { enabled: false, mode: "dry-run" };
  let saved = readSaved();
  let listening = false;

  async function init() {
    try {
      config = await (await fetch("/api/firebase-config")).json();
    } catch {
      config = { enabled: false, mode: "dry-run" };
    }
    return { webPush: config.enabled, mode: config.mode };
  }

  async function realToken() {
    if (!browserSupportsPush()) {
      throw new PushError("This browser can't receive web push. Try Chrome, Edge or Firefox.");
    }
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      throw new PushError("Notifications are blocked. Allow them in your browser's site settings, then try again.");
    }
    const registration = await navigator.serviceWorker.register("/firebase-messaging-sw.js");
    await navigator.serviceWorker.ready;

    const base = `https://www.gstatic.com/firebasejs/${config.sdkVersion}`;
    const { initializeApp, getApps } = await import(`${base}/firebase-app.js`);
    const { getMessaging, getToken, onMessage } = await import(`${base}/firebase-messaging.js`);
    const app = getApps()[0] || initializeApp(config.config);
    const messaging = getMessaging(app);

    const token = await getToken(messaging, {
      vapidKey: config.vapidKey,
      serviceWorkerRegistration: registration,
    });
    if (!token) throw new PushError("Firebase didn't return a push token. Try again in a moment.");

    if (!listening) {
      listening = true;
      onMessage(messaging, (payload) => onForeground && onForeground(payload.notification || {}));
    }
    return token;
  }

  async function register(token, settings, schedule) {
    return call("POST", "/api/notifications/register", {
      token,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      reminder_time: settings.reminderTime,
      motivation: settings.motivation,
      weekdays: schedule.weekdays,
      day_names: schedule.dayNames,
    });
  }

  return {
    init,
    get saved() { return saved; },
    get webPush() { return config.enabled; },

    async enable(settings, schedule) {
      const token = config.enabled
        ? await realToken()
        : (saved && saved.token.startsWith("preview-") ? saved.token : placeholderToken());
      const result = await register(token, settings, schedule);
      saved = { token, ...settings };
      writeSaved(saved);
      return result;
    },

    /** Re-send the schedule after the plan changes, so reminders name the right workouts. */
    async sync(schedule) {
      if (!saved) return null;
      try {
        return await register(saved.token, saved, schedule);
      } catch {
        return null;
      }
    },

    async disable() {
      if (!saved) return;
      try {
        await call("DELETE", "/api/notifications/register", { token: saved.token });
      } finally {
        saved = null;
        writeSaved(null);
      }
    },

    async test() {
      if (!saved) throw new PushError("Turn on reminders first.");
      return call("POST", "/api/notifications/test", { token: saved.token });
    },
  };
}
