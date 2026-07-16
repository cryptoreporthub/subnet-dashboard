/** §17.F5 — streaming SimiVision chat (textContent only, XSS-safe) */
(function () {
  "use strict";

  var log = document.getElementById("chatLog");
  var input = document.getElementById("chatInput");
  var btn = document.getElementById("chatSend");
  var meta = document.getElementById("chatMeta");
  if (!log || !input || !btn) return;

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

  async function send() {
    var msg = (input.value || "").trim();
    if (!msg) return;
    appendMsg("user").textContent = msg;
    input.value = "";
    btn.disabled = true;
    if (meta) meta.textContent = "LLM: thinking…";

    var botBody = appendMsg("bot");
    var full = "";

    try {
      var resp = await fetch("/api/simivision/chat?stream=1", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, stream: true }),
      });
      if (!resp.ok) throw new Error("HTTP " + resp.status);

      var ct = resp.headers.get("content-type") || "";
      if (ct.indexOf("text/event-stream") < 0) {
        var j = await resp.json();
        botBody.textContent = j.reply || (j.data && j.data.reply) || "No response.";
        if (meta) meta.textContent = "LLM: " + (j.model || "ok");
        return;
      }

      if (!resp.body || !resp.body.getReader) throw new Error("no stream");

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
              if (meta && m.model) meta.textContent = "LLM: " + m.model;
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
    } catch (e) {
      botBody.textContent = "Connection error — intelligence layer unreachable.";
      if (meta) meta.textContent = "LLM: error";
    } finally {
      btn.disabled = false;
      input.focus();
    }
  }

  btn.addEventListener("click", send);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") send();
  });

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
