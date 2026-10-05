// assets/nextek-widget.js
(function () {
  const currentScript = document.currentScript;
  let activeRoot = null;
  let activeLauncher = null;

  function asegurarEstilos() {
    if (!document.getElementById("nx-widget-css")) {
      const link = document.createElement("link");
      link.id = "nx-widget-css";
      link.rel = "stylesheet";
      link.href = "/assets/nextek-widget.css";
      document.head.appendChild(link);
    }
  }

  function habilitarArrastre(elemento, manija) {
    let arrastrando = false;
    let offsetStartX = 0;
    let offsetStartY = 0;
    let posInicialLeft = 0;
    let posInicialTop = 0;

    manija.addEventListener("mousedown", (e) => {
      if (e.target.closest(".nx-btn-action")) return;

      arrastrando = true;
      const rect = elemento.getBoundingClientRect();

      elemento.style.bottom = "auto";
      elemento.style.right = "auto";
      elemento.style.left = `${rect.left}px`;
      elemento.style.top = `${rect.top}px`;

      offsetStartX = e.clientX;
      offsetStartY = e.clientY;
      posInicialLeft = rect.left;
      posInicialTop = rect.top;

      const alMoverMouse = (eventoMov) => {
        if (!arrastrando) return;
        const deltaX = eventoMov.clientX - offsetStartX;
        const deltaY = eventoMov.clientY - offsetStartY;

        const maxLeft = window.innerWidth - rect.width - 10;
        const maxTop = window.innerHeight - rect.height - 10;

        const nuevoLeft = Math.max(10, Math.min(maxLeft, posInicialLeft + deltaX));
        const nuevoTop = Math.max(10, Math.min(maxTop, posInicialTop + deltaY));

        elemento.style.left = `${nuevoLeft}px`;
        elemento.style.top = `${nuevoTop}px`;
      };

      const alSoltarMouse = () => {
        arrastrando = false;
        document.removeEventListener("mousemove", alMoverMouse);
        document.removeEventListener("mouseup", alSoltarMouse);
      };

      document.addEventListener("mousemove", alMoverMouse);
      document.addEventListener("mouseup", alSoltarMouse);
    });
  }

  const NexTekWidget = {
    init: function (opciones = {}) {
      this.destroy();
      asegurarEstilos();

      const API_URL = opciones.api ?? (currentScript?.getAttribute("data-api") || "");
      let rawMode = (opciones.mode ?? (currentScript?.getAttribute("data-mode") || "fab")).toLowerCase();
      if (rawMode === "inline") rawMode = "fullscreen";
      if (rawMode === "floating") rawMode = "fab";
      const MODE = rawMode;

      const TARGET_ID = opciones.target ?? (currentScript?.getAttribute("data-target") || "nextek-chat-target");
      const PRIMARY_COLOR = opciones.color ?? (currentScript?.getAttribute("data-color") || "#0084ff");

      // Sección fija de preguntas sugeridas habilitada para todos los modos
      const barraSugerenciasHTML = `
        <div class="nx-suggestions-bar" id="nxSuggestionsBar">
          <button class="nx-chip" type="button">Cuanto tiempo para devolver un smartphone?</button>
          <button class="nx-chip" type="button">El envio es gratis?</button>
          <button class="nx-chip" type="button">Que metodos de pago aceptan?</button>
          <button class="nx-chip" type="button">Como funciona NexTek+?</button>
        </div>
      `;

      const root = document.createElement("div");
      root.className = `nx-chat-root mode-${MODE}`;
      root.id = "nxChatRoot";

      root.innerHTML = `
        <div class="nx-header" id="nxHeader" style="background:${PRIMARY_COLOR};">
          <div class="nx-header-info">
            <div class="nx-avatar">Nx</div>
            <div>
              <div class="nx-title">NexTek AI</div>
              <div class="nx-status">En línea</div>
            </div>
          </div>
          <div class="nx-actions">
            ${MODE === "messenger" ? `<button class="nx-btn-action" id="nxMinBtn" title="Minimizar">—</button>` : ""}
            ${MODE !== "fullscreen" ? `<button class="nx-btn-action" id="nxCloseBtn" title="Cerrar">✕</button>` : ""}
          </div>
        </div>
        <div class="nx-messages" id="nxMessages">
          <div class="nx-msg bot">Hola, soy el asistente inteligente de NexTek. ¿En qué puedo ayudarte?</div>
        </div>
        ${barraSugerenciasHTML}
        <form class="nx-footer" id="nxForm">
          <input class="nx-input" id="nxInput" type="text" placeholder="Escribe tu pregunta..." autocomplete="off" />
          <button class="nx-btn-send" style="background:${PRIMARY_COLOR};" type="submit">➤</button>
        </form>
      `;

      const messages = root.querySelector("#nxMessages");
      const form = root.querySelector("#nxForm");
      const input = root.querySelector("#nxInput");
      const header = root.querySelector("#nxHeader");
      const suggestionsBar = root.querySelector("#nxSuggestionsBar");

      const hacerScroll = () => { messages.scrollTop = messages.scrollHeight; };

      if (MODE === "fab") {
        habilitarArrastre(root, header);
      }

      form.onsubmit = async (e) => {
        e.preventDefault();
        const query = input.value.trim();
        if (!query) return;

        // Ocultar preguntas predeterminadas tras iniciar la conversación
        if (suggestionsBar) suggestionsBar.style.display = "none";

        const userBubble = document.createElement("div");
        userBubble.className = "nx-msg user";
        userBubble.style.background = PRIMARY_COLOR;
        userBubble.textContent = query;
        messages.appendChild(userBubble);
        input.value = "";
        hacerScroll();

        const loadId = "load-" + Date.now();
        const typingBox = document.createElement("div");
        typingBox.className = "nx-msg bot nx-typing";
        typingBox.id = loadId;
        typingBox.innerHTML = `<span></span><span></span><span></span>`;
        messages.appendChild(typingBox);
        hacerScroll();

        try {
          const res = await fetch(`${API_URL}/preguntar`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ pregunta: query })
          });

          const data = await res.json().catch(() => ({}));
          document.getElementById(loadId)?.remove();

          if (!res.ok) {
            const errText = data.detail || data.respuesta || "Error al procesar consulta.";
            const errBubble = document.createElement("div");
            errBubble.className = "nx-msg bot error";
            errBubble.textContent = `⚠️ ${errText}`;
            messages.appendChild(errBubble);
            hacerScroll();
            return;
          }

          const botBubble = document.createElement("div");
          botBubble.className = "nx-msg bot";
          botBubble.textContent = data.respuesta || "Sin respuesta del servidor.";

          if (Array.isArray(data.sources) && data.sources.length > 0) {
            const sourcesContainer = document.createElement("div");
            sourcesContainer.className = "nx-sources";
            data.sources.forEach((fuente) => {
              const tag = document.createElement("span");
              tag.className = "nx-source-tag";
              tag.textContent = fuente;
              sourcesContainer.appendChild(tag);
            });
            botBubble.appendChild(sourcesContainer);
          }

          messages.appendChild(botBubble);
        } catch (err) {
          document.getElementById(loadId)?.remove();
          const errBubble = document.createElement("div");
          errBubble.className = "nx-msg bot error";
          errBubble.textContent = "⚠️ Error de conexión con el servidor.";
          messages.appendChild(errBubble);
        }

        hacerScroll();
      };

      // Manejador de clics para los chips en cualquier modo
      if (suggestionsBar) {
        suggestionsBar.addEventListener("click", (e) => {
          const chip = e.target.closest(".nx-chip");
          if (!chip) return;

          input.value = chip.textContent.trim();
          suggestionsBar.style.display = "none";

          if (typeof form.requestSubmit === "function") {
            form.requestSubmit();
          } else {
            form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
          }
        });
      }

      if (MODE === "fullscreen") {
        const targetContainer = document.getElementById(TARGET_ID) || document.body;
        targetContainer.appendChild(root);
      } else {
        document.body.appendChild(root);

        const launcher = document.createElement("button");
        launcher.className = "nx-launcher-btn";
        launcher.style.background = PRIMARY_COLOR;
        launcher.innerHTML = "💬";
        document.body.appendChild(launcher);
        activeLauncher = launcher;

        launcher.onclick = () => {
          root.style.display = "flex";
          root.classList.remove("minimized");
          launcher.style.display = "none";
        };

        const closeBtn = root.querySelector("#nxCloseBtn");
        if (closeBtn) {
          closeBtn.onclick = (e) => {
            e.stopPropagation();
            root.style.display = "none";
            launcher.style.display = "flex";
          };
        }

        if (MODE === "messenger") {
          const minBtn = root.querySelector("#nxMinBtn");
          const alternarMin = (e) => {
            e.stopPropagation();
            root.classList.toggle("minimized");
          };
          if (minBtn) minBtn.onclick = alternarMin;
          header.onclick = alternarMin;
        }
      }

      activeRoot = root;
    },

    destroy: function () {
      if (activeRoot) {
        activeRoot.remove();
        activeRoot = null;
      }
      if (activeLauncher) {
        activeLauncher.remove();
        activeLauncher = null;
      }
    }
  };

  window.NexTekWidget = NexTekWidget;

  if (currentScript && currentScript.hasAttribute("data-mode")) {
    const start = () => NexTekWidget.init();
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", start);
    } else {
      start();
    }
  }
})();
