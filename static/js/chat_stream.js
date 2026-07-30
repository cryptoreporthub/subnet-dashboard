/** §17.F5 — streaming SimiVision chat (textContent only, XSS-safe) */
(function () {
  "use strict";

  var log = document.getElementById("chatLog");
  var input = document.getElementById("chatInput");
  var btn = document.getElementById("chatSend");
  var meta = document.getElementById("chatMeta");
  if (!log || !input || !btn) return;

  var PARTIAL_MSG =
    "Partial context — council data loaded, live feeds still warming. Try again shortly.";
  var chatReady = false;

  function setChatReady(ready) {
    chatReady = !!ready;
    btn.disabled = !chatReady;
    if (meta && chatReady) meta.textContent = "LLM: ready";
  }

  function warmChatContext() {
    setChatReady(false);
    if (meta) meta.textContent = "LLM: warming…";
    var probe = window.apiFetchJson
      ? window.apiFetchJson("/api/daily-pick", 8000)
      : fetch("/api/daily-pick", { headers: { Accept: "application/json" } }).then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        });
    probe
      .then(function () {
        setChatReady(true);
      })
      .catch(function () {
        setChatReady(true);
        if (meta) meta.textContent = "LLM: partial context";
      });
  }

  function appendMsg(who) {
    var row = document.createElement("div");
    row.className = "chat-msg " + (who === "user" ? "user" : "bot");
    var label = document.createElement("div");
    label.className = "who";
    label.textContent = who === "user" ? "YOU" : "SIMIVISION";
    var body = document.createElement("div");
    body.className = "chat-text";
    row.appendChild(label);
    row.appendChild(body);
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
    return body;
  }

  function parseBlock(block) {
    if (!block || !block.trim()) return null;
    var ev = "message";
    var data = "";
    block.split("\n").forEach(function (line) {
      if (line.indexOf("event:") === 0) ev = line.slice(6).trim();
      else if (line.indexOf("data:") === 0) data += line.slice(5).trim();
    });
    return data ? { event: ev, data: data } : null;
  }

  function consumeSSE(buffer, onEvent) {
    var parts = buffer.split("\n\n");
    var rest = parts.pop() || "";
    parts.forEach(function (part) {
      var ev = parseBlock(part);
      if (ev) onEvent(ev);
    });
    return rest;
  }

  function formatChatMeta(model, status) {
    if (status === "partial") return "LLM: partial context";
    if (status === "timeout") return "LLM: partial context";
    if (status === "error") return "LLM: partial context";
    if (model === "local-fallback" || status === "local-fallback") return "LLM: local fallback";
    if (model) return "LLM: " + model;
    return "LLM: ok";
  }

  function isPartialChatStatus(status) {
    return status === "partial" || status === "timeout" || status === "error" || status === "offline";
  }

  function applyJsonReply(botBody, j) {
    var status = j.status || (j.data && j.data.status);
    if (isPartialChatStatus(status)) {
      botBody.textContent = PARTIAL_MSG;
      if (meta) meta.textContent = formatChatMeta(j.model || (j.data && j.data.model), status);
      setChatReady(false);
      return;
    }
    botBody.textContent = j.reply || (j.data && j.data.reply) || "No response.";
    if (meta) meta.textContent = formatChatMeta(j.model || (j.data && j.data.model), status);
    setChatReady(true);
  }

  async function readStream(resp, botBody) {
    var full = "";
    var reader = resp.body.getReader();
    var decoder = new TextDecoder();
    var buf = "";
    while (true) {
      var chunk = await reader.read();
      if (chunk.done) break;
      buf += decoder.decode(chunk.value, { stream: true });
      buf = consumeSSE(buf, function (ev) {
        if (ev.event === "meta") {
          try {
            var m = JSON.parse(ev.data);
            if (meta) meta.textContent = formatChatMeta(m.model, m.status);
            if (isPartialChatStatus(m.status)) setChatReady(false);
          } catch (e) {
            /* ignore */
          }
        } else if (ev.event === "chunk") {
          try {
            var c = JSON.parse(ev.data);
            if (c.text) {
              full += c.text;
              botBody.textContent = full;
              log.scrollTop = log.scrollHeight;
            }
          } catch (e) {
            /* ignore */
          }
        }
      });
    }
    if (buf.trim()) {
      consumeSSE(buf + "\n\n", function (ev) {
        if (ev.event === "chunk") {
          try {
            var c = JSON.parse(ev.data);
            if (c.text) {
              full += c.text;
              botBody.textContent = full;
            }
          } catch (e) {
            /* ignore */
          }
        }
      });
    }
    if (!full) botBody.textContent = "No response.";
    return full;
  }

  async function deliverChat(msg, botBody, useStream) {
    var url = useStream ? "/api/simivision/chat?stream=1" : "/api/simivision/chat";
    var body = useStream
      ? JSON.stringify({ message: msg, stream: true })
      : JSON.stringify({ message: msg });
    var resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body,
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);

    var ct = resp.headers.get("content-type") || "";
    if (ct.indexOf("text/event-stream") < 0) {
      applyJsonReply(botBody, await resp.json());
      return;
    }
    if (!resp.body || !resp.body.getReader) throw new Error("no stream");
    await readStream(resp, botBody);
    if (botBody.textContent !== PARTIAL_MSG) setChatReady(true);
    else setChatReady(false);
  }

  async function send() {
    var msg = (input.value || "").trim();
    if (!msg || !chatReady) return;
    appendMsg("user").textContent = msg;
    input.value = "";
    btn.disabled = true;
    if (meta) meta.textContent = "LLM: thinking…";

    var botBody = appendMsg("bot");

    try {
      try {
        await deliverChat(msg, botBody, true);
      } catch (streamErr) {
        if (meta) meta.textContent = "LLM: retrying…";
        await deliverChat(msg, botBody, false);
      }
    } catch (e) {
      botBody.textContent = PARTIAL_MSG;
      if (meta) meta.textContent = "LLM: partial context";
      setChatReady(false);
    } finally {
      if (chatReady) btn.disabled = false;
      input.focus();
    }
  }

  btn.addEventListener("click", send);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") send();
  });

  warmChatContext();

  var presets = document.getElementById("chatPresets");
  if (presets) {
    presets.addEventListener("click", function (e) {
      var btnEl = e.target.closest(".chat-preset");
      if (!btnEl) return;
      var prompt = btnEl.getAttribute("data-prompt") || "";
      if (!prompt) return;
      input.value = prompt;
      send();
    });
  }
})();
