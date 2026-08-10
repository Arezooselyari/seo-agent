(function () {
  var scriptEl = document.currentScript;
  var scriptUrl = new URL(scriptEl.src);
  var apiBase = scriptUrl.origin;
  var siteKey = scriptUrl.searchParams.get("site") || "";

  if (!siteKey) {
    console.error("[chatbot-widget] پارامتر site در src اسکریپت لازم است.");
    return;
  }

  var storageKey = "chatbot_widget_session_" + siteKey;
  var sessionId = localStorage.getItem(storageKey);
  if (!sessionId) {
    sessionId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());
    localStorage.setItem(storageKey, sessionId);
  }

  // ── استایل پایه (بدون وابستگی به CSS سایت میزبان) ──
  var style = document.createElement("style");
  style.textContent = [
    "#cbw-bubble{position:fixed;bottom:20px;left:20px;width:56px;height:56px;border-radius:50%;",
    "background:#2563eb;color:#fff;display:flex;align-items:center;justify-content:center;",
    "cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.2);font-family:Tahoma,sans-serif;z-index:999999;font-size:26px;}",
    "#cbw-panel{position:fixed;bottom:88px;left:20px;width:320px;max-height:440px;background:#fff;",
    "border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.25);display:none;flex-direction:column;",
    "overflow:hidden;font-family:Tahoma,sans-serif;direction:rtl;z-index:999999;}",
    "#cbw-panel.open{display:flex;}",
    "#cbw-header{background:#1f2937;color:#fff;padding:10px 14px;font-size:14px;}",
    "#cbw-messages{flex:1;overflow-y:auto;padding:10px;display:flex;flex-direction:column;gap:8px;max-height:320px;}",
    "#cbw-messages .m{max-width:85%;padding:8px 10px;border-radius:10px;font-size:13px;line-height:1.6;white-space:pre-wrap;}",
    "#cbw-messages .m.user{align-self:flex-end;background:#2563eb;color:#fff;}",
    "#cbw-messages .m.model{align-self:flex-start;background:#f1f5f9;color:#111;}",
    "#cbw-inputrow{display:flex;border-top:1px solid #e5e7eb;}",
    "#cbw-input{flex:1;border:none;padding:10px;font-family:inherit;font-size:13px;outline:none;}",
    "#cbw-send{border:none;background:#2563eb;color:#fff;padding:0 14px;cursor:pointer;}",
  ].join("");
  document.head.appendChild(style);

  var bubble = document.createElement("div");
  bubble.id = "cbw-bubble";
  bubble.textContent = "💬";

  var panel = document.createElement("div");
  panel.id = "cbw-panel";
  panel.innerHTML =
    '<div id="cbw-header">دستیار آنلاین</div>' +
    '<div id="cbw-messages"></div>' +
    '<div id="cbw-inputrow">' +
    '<input id="cbw-input" type="text" placeholder="پیام بنویس..." />' +
    '<button id="cbw-send">ارسال</button>' +
    "</div>";

  document.body.appendChild(panel);
  document.body.appendChild(bubble);

  var messagesEl = panel.querySelector("#cbw-messages");
  var inputEl = panel.querySelector("#cbw-input");
  var sendBtn = panel.querySelector("#cbw-send");

  bubble.addEventListener("click", function () {
    panel.classList.toggle("open");
  });

  function appendMessage(role, text) {
    var div = document.createElement("div");
    div.className = "m " + role;
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function send() {
    var text = inputEl.value.trim();
    if (!text) return;
    appendMessage("user", text);
    inputEl.value = "";
    sendBtn.disabled = true;

    fetch(apiBase + "/api/widget/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, site_key: siteKey, message: text }),
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error("request failed");
        return resp.json();
      })
      .then(function (data) {
        appendMessage("model", data.reply);
      })
      .catch(function () {
        appendMessage("model", "متأسفم، ارتباط برقرار نشد.");
      })
      .finally(function () {
        sendBtn.disabled = false;
      });
  }

  sendBtn.addEventListener("click", send);
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter") send();
  });
})();
