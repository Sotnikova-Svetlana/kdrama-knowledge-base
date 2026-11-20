/**
 * Контроллер пользовательского каталога дорам:
 * витрина редакции, фильтр по годам, описания на карточках,
 * интеллектуальный поиск (опечатки и раскладка) и проверка новинок.
 */

import { api } from "./api.js";
import { escapeHtml, formatStatusRu, renderPosterMarkup, showToast } from "./uiHelpers.js";

const FLAGSHIP_SLUGS = ["itaewon-class", "goblin", "the-glory", "queen-of-tears"];

export function createCatalogController({ onOpenDrama, onOpenPerson }) {
  const state = {
    navMode: "all", // 'all' | 'ongoing' | 'fresh'
    query: "",
    disableLayoutFix: false,
    genre: "",
    trope: "",
    platform: "",
    status: "",
    year: "",
    sortBy: "rating",
    autocompleteIndex: -1,
    autocompleteItems: [],
    spotlightIndex: 0,
    spotlightItems: [],
    offset: 0,
    pageSize: 48,
    totalItems: 0,
    loadedItems: [],
  };

  const els = {
    searchForm: document.getElementById("search-form"),
    searchInput: document.getElementById("search-input"),
    clearBtn: document.getElementById("btn-clear-search"),
    dropdown: document.getElementById("autocomplete-dropdown"),
    banner: document.getElementById("search-correction-banner"),
    bannerMsg: document.getElementById("correction-message"),
    rawBtn: document.getElementById("btn-search-exact-raw"),

    checkUpdatesBtn: document.getElementById("btn-check-updates"),
    progressStrip: document.getElementById("update-progress-strip"),
    progressText: document.getElementById("update-progress-text"),
    progressPct: document.getElementById("update-progress-pct"),
    progressFill: document.getElementById("update-progress-fill"),

    updatesShelf: document.getElementById("updates-highlight-shelf"),
    updatesSummary: document.getElementById("updates-shelf-summary"),
    updatesGrid: document.getElementById("updates-shelf-grid"),
    dismissShelfBtn: document.getElementById("btn-dismiss-updates-shelf"),

    spotlight: document.getElementById("hero-spotlight"),
    statusTabs: document.getElementById("status-tabs"),
    genreSelect: document.getElementById("filter-genre"),
    tropeSelect: document.getElementById("filter-trope"),
    platformSelect: document.getElementById("filter-platform"),
    sortSelect: document.getElementById("filter-sort"),
    yearsBar: document.getElementById("years-bar"),

    heading: document.getElementById("catalog-heading"),
    countLabel: document.getElementById("catalog-count-label"),
    lastUpdatedLabel: document.getElementById("catalog-last-updated"),
    resetBtn: document.getElementById("btn-reset-filters"),
    emptyResetBtn: document.getElementById("btn-empty-reset"),
    grid: document.getElementById("dramas-grid"),
    loadMoreWrap: document.getElementById("catalog-load-more"),
    loadMoreBtn: document.getElementById("btn-load-more"),
    emptyState: document.getElementById("catalog-empty"),
  };

  let debounceTimer = null;
  let activeEventSource = null;

  async function loadTaxonomyFilters() {
    try {
      const [genres, tropes, platforms, years] = await Promise.all([
        api.getGenres(),
        api.getTropes(),
        api.getPlatforms(),
        api.getYears(),
      ]);

      els.genreSelect.innerHTML =
        `<option value="">Все жанры</option>` +
        genres
          .map((g) => `<option value="${escapeHtml(g.slug)}">${escapeHtml(g.name_ru)} (${g.dramas_count})</option>`)
          .join("");

      els.tropeSelect.innerHTML =
        `<option value="">Все сюжетные мотивы</option>` +
        tropes
          .map((t) => `<option value="${escapeHtml(t.slug)}">${escapeHtml(t.name_ru)} (${t.dramas_count})</option>`)
          .join("");

      els.platformSelect.innerHTML =
        `<option value="">Все платформы</option>` +
        platforms
          .map((p) => `<option value="${escapeHtml(p.slug)}">${escapeHtml(p.name)} (${p.dramas_count})</option>`)
          .join("");

      renderYearsBar(years);

      if (state.genre) els.genreSelect.value = state.genre;
      if (state.trope) els.tropeSelect.value = state.trope;
      if (state.platform) els.platformSelect.value = state.platform;
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  function renderYearsBar(years) {
    const buttonsHtml = (years || [])
      .map(
        (y) => `
          <button type="button" class="year-btn ${String(state.year) === String(y.release_year) ? "is-active" : ""}" data-year="${y.release_year}" title="Дорам за ${y.release_year} год: ${y.dramas_count}">
            ${y.release_year}
          </button>
        `
      )
      .join("");

    els.yearsBar.innerHTML = `
      <span class="years-label">Год выхода:</span>
      <button type="button" class="year-btn ${state.year === "" ? "is-active" : ""}" data-year="">Все годы</button>
      ${buttonsHtml}
    `;
  }

  function updateYearsBarActive() {
    els.yearsBar.querySelectorAll(".year-btn").forEach((btn) => {
      btn.classList.toggle("is-active", (btn.dataset.year || "") === String(state.year || ""));
    });
  }

  async function refreshLastUpdatedLabel() {
    try {
      const overview = await api.getOverview();
      if (overview && overview.last_sync_at) {
        const dt = new Date(overview.last_sync_at.replace(" ", "T") + (overview.last_sync_at.endsWith("Z") ? "" : "Z"));
        const formatted = Number.isNaN(dt.getTime())
          ? overview.last_sync_at
          : dt.toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
        els.lastUpdatedLabel.textContent = `Обновлено: ${formatted} · всего в каталоге ${overview.dramas_count}`;
      } else if (overview) {
        els.lastUpdatedLabel.textContent = `В каталоге ${overview.dramas_count} дорам`;
      }
    } catch {
      // non-critical
    }
  }

  async function loadSpotlight() {
    if (state.spotlightItems.length) {
      renderSpotlight();
      return;
    }
    try {
      const resp = await api.getDramas({ sort_by: "popularity", limit: 48 });
      const bySlug = new Map((resp.items || []).map((d) => [d.slug, d]));
      const flagship = FLAGSHIP_SLUGS.map((slug) => bySlug.get(slug)).filter(Boolean);
      state.spotlightItems = flagship.length ? flagship : (resp.items || []).slice(0, 4);
      renderSpotlight();
    } catch {
      els.spotlight.classList.add("is-hidden");
    }
  }

  function renderSpotlight() {
    const isDefaultHome =
      state.navMode === "all" &&
      !state.query.trim() &&
      !state.genre &&
      !state.trope &&
      !state.platform &&
      !state.status &&
      !state.year;

    if (!isDefaultHome || !state.spotlightItems.length) {
      els.spotlight.classList.add("is-hidden");
      return;
    }

    els.spotlight.classList.remove("is-hidden");
    const item = state.spotlightItems[state.spotlightIndex % state.spotlightItems.length];
    const genresLine = (item.genres || []).slice(0, 3).map((g) => g.name_ru).join(" / ");
    const dotsHtml = state.spotlightItems
      .map(
        (d, idx) => `
          <button type="button" class="hero-dot-btn ${idx === state.spotlightIndex ? "is-active" : ""}" data-spotlight-idx="${idx}">
            ${escapeHtml(d.title_ru)}
          </button>
        `
      )
      .join("");

    els.spotlight.innerHTML = `
      <div class="hero-spotlight-poster">
        ${renderPosterMarkup(item)}
      </div>
      <div class="hero-spotlight-content">
        <div>
          <div class="hero-kicker">Выбор редакции</div>
          <h2 class="hero-spotlight-title">${escapeHtml(item.title_ru)}</h2>
          <p class="hero-spotlight-sub">
            <button type="button" class="year-link" data-year-pick="${escapeHtml(item.release_year)}" title="Показать все дорамы ${escapeHtml(item.release_year)} года">${escapeHtml(item.release_year)}</button>
            · ${escapeHtml(item.title_en)}${item.title_kr ? ` · ${escapeHtml(item.title_kr)}` : ""}
            · ${escapeHtml(genresLine)} · ${escapeHtml(item.episodes_count)} сер.
          </p>
        </div>

        <p class="hero-spotlight-synopsis">${escapeHtml(item.synopsis_ru || "")}</p>

        <div class="hero-spotlight-footer">
          <button type="button" class="btn btn-primary" data-spotlight-open="${item.id}">Смотреть описание и похожие</button>
          <div class="hero-switcher">${dotsHtml}</div>
        </div>
      </div>
    `;
  }

  function updateHeading() {
    if (state.query.trim()) {
      els.heading.textContent = "Результаты поиска";
      return;
    }
    const parts = [];
    if (state.navMode === "ongoing" || state.status === "Ongoing") {
      parts.push("Онгоинги");
    } else if (state.navMode === "fresh") {
      parts.push("Новинки и недавние обновления");
    } else if (state.status === "Completed") {
      parts.push("Завершённые дорамы");
    } else {
      parts.push("Все дорамы");
    }
    if (state.year) {
      parts.push(`${state.year} года`);
    }
    els.heading.textContent = parts.join(" · ");
  }

  async function refresh(append = false) {
    updateResetVisibility();
    updateHeading();
    renderSpotlight();
    try {
      if (state.query.trim()) {
        els.loadMoreWrap.classList.add("is-hidden");
        const resp = await api.searchDramas(state.query.trim(), state.disableLayoutFix);
        renderSearchResponse(resp);
      } else {
        els.banner.classList.add("is-hidden");
        const targetOffset = append ? state.loadedItems.length : 0;
        if (append) {
          els.loadMoreBtn.disabled = true;
          els.loadMoreBtn.textContent = "Загружаем...";
        }
        const resp = await api.getDramas({
          genre: state.genre,
          trope: state.trope,
          platform: state.platform,
          status: state.status,
          year: state.year || undefined,
          sort_by: state.sortBy,
          limit: state.pageSize,
          offset: targetOffset,
        });
        state.loadedItems = append ? [...state.loadedItems, ...resp.items] : resp.items;
        state.totalItems = resp.total;
        state.offset = state.loadedItems.length;
        renderCatalogCards(state.loadedItems, state.totalItems);
        updateLoadMoreButton();
      }
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      els.loadMoreBtn.disabled = false;
    }
  }

  function updateLoadMoreButton() {
    const remaining = Math.max(0, state.totalItems - state.loadedItems.length);
    if (remaining > 0 && !state.query.trim()) {
      els.loadMoreWrap.classList.remove("is-hidden");
      els.loadMoreBtn.textContent = `Показать ещё (осталось ${remaining})`;
    } else {
      els.loadMoreWrap.classList.add("is-hidden");
    }
  }

  function renderSearchResponse(resp) {
    if (resp.was_corrected && resp.banner_message) {
      els.bannerMsg.textContent = resp.banner_message;
      els.banner.classList.remove("is-hidden");
    } else {
      els.banner.classList.add("is-hidden");
    }

    const dramas = resp.results.map((hit) => hit.drama);
    const scoreMap = new Map(resp.results.map((hit) => [hit.drama.id, hit]));
    els.countLabel.textContent = `Найдено по запросу «${resp.effective_query}»: ${resp.total}`;
    renderCardsGrid(dramas, scoreMap);
  }

  function renderCatalogCards(items, total) {
    els.countLabel.textContent = `Показано ${items.length} из ${total}`;
    renderCardsGrid(items, null);
  }

  function renderCardsGrid(items, scoreMap) {
    if (!items.length) {
      els.grid.innerHTML = "";
      els.emptyState.classList.remove("is-hidden");
      return;
    }

    els.emptyState.classList.add("is-hidden");
    els.grid.innerHTML = items
      .map((drama) => {
        const genreText = (drama.genres || []).slice(0, 2).map((g) => g.name_ru).join(" / ");
        const platformText = (drama.platforms || []).slice(0, 1).map((p) => p.name).join("");
        const trailingMeta = [genreText, platformText].filter(Boolean).join(" · ");
        const tropesLine = (drama.tropes || []).slice(0, 3).map((t) => t.name_ru).join(" · ");
        const hitInfo = scoreMap ? scoreMap.get(drama.id) : null;
        const matchLine = hitInfo ? `Совпадение ${Math.round(hitInfo.score)}% · ` : "";
        const synopsis = drama.synopsis_ru || "Описание дорамы появится в ближайшем обновлении каталога.";

        return `
          <article class="drama-card" data-drama-id="${drama.id}" tabindex="0">
            ${renderPosterMarkup(drama)}
            <div class="drama-card-body">
              <h3 class="drama-card-title">${escapeHtml(drama.title_ru)}</h3>
              <div class="drama-card-meta">
                <button type="button" class="year-link" data-year-pick="${escapeHtml(drama.release_year)}" title="Показать дорамы ${escapeHtml(drama.release_year)} года">${escapeHtml(drama.release_year)}</button>
                ${trailingMeta ? `<span>·</span><span>${escapeHtml(trailingMeta)}</span>` : ""}
              </div>
              <p class="drama-card-synopsis">${escapeHtml(synopsis)}</p>
              <div class="drama-card-tropes">${escapeHtml(matchLine + tropesLine)}</div>
            </div>
          </article>
        `;
      })
      .join("");
  }

  function selectYear(year) {
    state.year = year ? String(year) : "";
    state.query = "";
    els.searchInput.value = "";
    els.clearBtn.classList.add("is-hidden");
    updateYearsBarActive();
    refresh();
    els.yearsBar.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function setNavMode(mode) {
    state.navMode = mode;
    state.query = "";
    els.searchInput.value = "";
    els.clearBtn.classList.add("is-hidden");

    if (mode === "ongoing") {
      state.status = "Ongoing";
      state.sortBy = "updated";
    } else if (mode === "fresh") {
      state.status = "";
      state.sortBy = "updated";
    } else {
      state.status = "";
      state.sortBy = "rating";
    }

    els.statusTabs.querySelectorAll(".seg-tab").forEach((btn) => {
      btn.classList.toggle("is-active", (btn.dataset.status || "") === state.status);
    });
    els.sortSelect.value = state.sortBy;
    refresh();
  }

  function checkForUpdates() {
    if (activeEventSource) {
      activeEventSource.close();
      activeEventSource = null;
    }

    els.checkUpdatesBtn.disabled = true;
    els.checkUpdatesBtn.textContent = "Проверяем...";
    els.progressStrip.classList.remove("is-hidden");
    els.progressFill.style.width = "5%";
    els.progressPct.textContent = "5%";
    els.progressText.textContent = "Подключаемся к источнику обновлений...";

    const es = api.openSyncStream("auto");
    activeEventSource = es;

    const handleProgress = (e) => {
      const data = JSON.parse(e.data);
      const pct = Math.min(100, Math.max(0, Number(data.progress || 0)));
      els.progressFill.style.width = `${pct}%`;
      els.progressPct.textContent = `${pct}%`;
      if (data.message) {
        els.progressText.textContent = data.message;
      }
    };

    es.addEventListener("start", handleProgress);
    es.addEventListener("progress", handleProgress);

    es.addEventListener("item", (e) => {
      const data = JSON.parse(e.data);
      const pct = Math.min(100, Math.max(0, Number(data.progress || 0)));
      els.progressFill.style.width = `${pct}%`;
      els.progressPct.textContent = `${pct}%`;
      if (data.item) {
        els.progressText.textContent = `Проверяем: ${data.item.title_ru}`;
      }
    });

    es.addEventListener("complete", async (e) => {
      es.close();
      activeEventSource = null;
      const data = JSON.parse(e.data);
      els.progressFill.style.width = "100%";
      els.progressPct.textContent = "100%";
      els.progressText.textContent = "Каталог обновлён!";
      els.checkUpdatesBtn.disabled = false;
      els.checkUpdatesBtn.textContent = "Проверить новинки";

      window.setTimeout(() => {
        els.progressStrip.classList.add("is-hidden");
      }, 1200);

      state.spotlightItems = [];
      await Promise.all([loadTaxonomyFilters(), loadSpotlight(), refreshLastUpdatedLabel()]);
      await refresh();
      renderUpdatesShelf(data);
    });

    es.addEventListener("error", (e) => {
      if (activeEventSource !== es) {
        return;
      }
      let msg = "Не удалось проверить обновления";
      try {
        if (e.data) {
          const d = JSON.parse(e.data);
          msg = d.message || msg;
        }
      } catch {
        // fallback message
      }
      es.close();
      activeEventSource = null;
      els.progressStrip.classList.add("is-hidden");
      els.checkUpdatesBtn.disabled = false;
      els.checkUpdatesBtn.textContent = "Проверить новинки";
      showToast(msg, "error");
    });
  }

  function renderUpdatesShelf(data) {
    const details = data.details || [];
    const added = Number(data.dramas_added || 0);
    const updated = Number(data.dramas_updated || 0);

    let summaryText = "";
    if (added > 0 && updated > 0) {
      summaryText = `Добавлено новых дорам: ${added}, обновлено статусов и рейтингов: ${updated}. Нажмите на любую карточку, чтобы прочитать описание.`;
    } else if (added > 0) {
      summaryText = `В каталог добавлено новых дорам: ${added}. Нажмите на карточку, чтобы открыть описание.`;
    } else if (updated > 0) {
      summaryText = `Обновлены серии, статусы или рейтинги у ${updated} дорам.`;
    } else {
      summaryText = `Новых поступлений пока нет — каталог полностью актуален. Ниже показаны последние проверенные тайтлы:`;
    }

    const highlighted = details.filter((d) => d.action === "added" || d.action === "updated");
    const visibleItems = (highlighted.length ? highlighted : details).slice(0, 8);

    const actionLabels = {
      added: { text: "Новинка", cls: "" },
      updated: { text: "Обновлена", cls: "is-updated" },
      unchanged: { text: "Актуально", cls: "is-updated" },
    };

    els.updatesSummary.textContent = summaryText;
    els.updatesGrid.innerHTML = visibleItems
      .map((item) => {
        const badge = actionLabels[item.action] || actionLabels.unchanged;
        return `
          <div class="update-mini-card" data-update-drama-id="${item.drama_id}" tabindex="0">
            <div class="update-mini-top">
              <span class="update-mini-title">${escapeHtml(item.title_ru)}</span>
              <span class="update-mini-kind ${badge.cls}">${badge.text}</span>
            </div>
            <div class="drama-card-meta">
              <span>${escapeHtml(formatStatusRu(item.status))}</span>
              <span>·</span>
              <span>★ ${Number(item.rating || 0).toFixed(1)}</span>
            </div>
          </div>
        `;
      })
      .join("");

    els.updatesShelf.classList.remove("is-hidden");
    showToast(
      added > 0
        ? `Каталог пополнен: +${added} новых дорам`
        : updated > 0
        ? `Обновлено дорам: ${updated}`
        : "Каталог проверен: все данные актуальны"
    );
  }

  async function fetchAutocomplete(val) {
    if (!val.trim()) {
      hideAutocomplete();
      return;
    }
    try {
      const resp = await api.autocomplete(val.trim());
      state.autocompleteItems = resp.items || [];
      state.autocompleteIndex = -1;
      renderAutocomplete(resp);
    } catch {
      hideAutocomplete();
    }
  }

  function renderAutocomplete(resp) {
    const items = resp.items || [];
    if (!items.length) {
      hideAutocomplete();
      return;
    }

    const typeLabels = {
      drama: "Дорама",
      person: "Актёр / Автор",
      trope: "Сюжет",
    };

    const hintHtml = resp.correction_hint
      ? `<div class="ac-hint-row">Исправлена раскладка · ${escapeHtml(resp.correction_hint)}</div>`
      : "";

    const rowsHtml = items
      .map(
        (item, idx) => `
          <button type="button" class="ac-item" data-ac-idx="${idx}" role="option">
            <div class="ac-main">
              <span class="ac-label">${escapeHtml(item.label)}</span>
              <span class="ac-sublabel">${escapeHtml(item.sublabel)}</span>
            </div>
            <span class="ac-type">${escapeHtml(typeLabels[item.entity_type] || item.entity_type)}</span>
          </button>
        `
      )
      .join("");

    els.dropdown.innerHTML = hintHtml + rowsHtml;
    els.dropdown.classList.remove("is-hidden");
  }

  function hideAutocomplete() {
    els.dropdown.classList.add("is-hidden");
    els.dropdown.innerHTML = "";
    state.autocompleteItems = [];
    state.autocompleteIndex = -1;
  }

  function selectAutocompleteItem(item) {
    hideAutocomplete();
    if (item.entity_type === "drama") {
      onOpenDrama(item.id);
    } else if (item.entity_type === "person") {
      onOpenPerson(item.id);
    } else if (item.entity_type === "trope") {
      applyTropeFilter(item.slug);
    }
  }

  function applyTropeFilter(tropeSlug) {
    state.query = "";
    els.searchInput.value = "";
    els.clearBtn.classList.add("is-hidden");
    state.trope = tropeSlug;
    els.tropeSelect.value = tropeSlug;
    refresh();
  }

  function resetAllFilters() {
    state.navMode = "all";
    state.query = "";
    state.disableLayoutFix = false;
    state.genre = "";
    state.trope = "";
    state.platform = "";
    state.status = "";
    state.year = "";
    state.sortBy = "rating";

    els.searchInput.value = "";
    els.clearBtn.classList.add("is-hidden");
    els.genreSelect.value = "";
    els.tropeSelect.value = "";
    els.platformSelect.value = "";
    els.sortSelect.value = "rating";
    els.statusTabs.querySelectorAll(".seg-tab").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.status === "");
    });
    updateYearsBarActive();
    hideAutocomplete();
    refresh();
  }

  function updateResetVisibility() {
    const hasActive = Boolean(
      state.query || state.genre || state.trope || state.platform || state.status || state.year
    );
    els.resetBtn.classList.toggle("is-hidden", !hasActive);
  }

  function bindEvents() {
    els.searchForm.addEventListener("submit", (e) => {
      e.preventDefault();
      hideAutocomplete();
      state.query = els.searchInput.value;
      state.disableLayoutFix = false;
      refresh();
    });

    els.searchInput.addEventListener("input", () => {
      const val = els.searchInput.value;
      els.clearBtn.classList.toggle("is-hidden", !val);
      window.clearTimeout(debounceTimer);
      if (!val.trim()) {
        hideAutocomplete();
        if (state.query) {
          state.query = "";
          refresh();
        }
        return;
      }
      debounceTimer = window.setTimeout(() => fetchAutocomplete(val), 180);
    });

    els.searchInput.addEventListener("keydown", (e) => {
      const items = state.autocompleteItems;
      if (!items.length || els.dropdown.classList.contains("is-hidden")) return;

      if (e.key === "ArrowDown") {
        e.preventDefault();
        state.autocompleteIndex = (state.autocompleteIndex + 1) % items.length;
        highlightAutocomplete();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        state.autocompleteIndex = (state.autocompleteIndex - 1 + items.length) % items.length;
        highlightAutocomplete();
      } else if (e.key === "Enter" && state.autocompleteIndex >= 0) {
        e.preventDefault();
        selectAutocompleteItem(items[state.autocompleteIndex]);
      } else if (e.key === "Escape") {
        hideAutocomplete();
      }
    });

    function highlightAutocomplete() {
      els.dropdown.querySelectorAll(".ac-item").forEach((node) => {
        node.classList.toggle("is-selected", Number(node.dataset.acIdx) === state.autocompleteIndex);
      });
    }

    els.dropdown.addEventListener("click", (e) => {
      const btn = e.target.closest(".ac-item");
      if (!btn) return;
      const idx = Number(btn.dataset.acIdx);
      const item = state.autocompleteItems[idx];
      if (item) selectAutocompleteItem(item);
    });

    document.addEventListener("click", (e) => {
      if (!e.target.closest(".search-shell")) {
        hideAutocomplete();
      }
    });

    els.clearBtn.addEventListener("click", () => {
      state.query = "";
      state.disableLayoutFix = false;
      els.searchInput.value = "";
      els.clearBtn.classList.add("is-hidden");
      hideAutocomplete();
      refresh();
    });

    els.rawBtn.addEventListener("click", () => {
      state.disableLayoutFix = true;
      refresh();
    });

    document.querySelectorAll(".quick-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const q = chip.dataset.query || "";
        els.searchInput.value = q;
        els.clearBtn.classList.remove("is-hidden");
        state.query = q;
        state.disableLayoutFix = false;
        hideAutocomplete();
        refresh();
      });
    });

    els.statusTabs.addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-tab");
      if (!btn) return;
      state.status = btn.dataset.status || "";
      els.statusTabs.querySelectorAll(".seg-tab").forEach((b) => b.classList.toggle("is-active", b === btn));
      refresh();
    });

    els.yearsBar.addEventListener("click", (e) => {
      const btn = e.target.closest(".year-btn");
      if (!btn) return;
      selectYear(btn.dataset.year || "");
    });

    els.spotlight.addEventListener("click", (e) => {
      const yearBtn = e.target.closest("[data-year-pick]");
      if (yearBtn) {
        selectYear(yearBtn.dataset.yearPick);
        return;
      }
      const openBtn = e.target.closest("[data-spotlight-open]");
      if (openBtn) {
        onOpenDrama(Number(openBtn.dataset.spotlightOpen));
        return;
      }
      const dotBtn = e.target.closest("[data-spotlight-idx]");
      if (dotBtn) {
        state.spotlightIndex = Number(dotBtn.dataset.spotlightIdx);
        renderSpotlight();
      }
    });

    els.genreSelect.addEventListener("change", () => {
      state.genre = els.genreSelect.value;
      refresh();
    });
    els.tropeSelect.addEventListener("change", () => {
      state.trope = els.tropeSelect.value;
      refresh();
    });
    els.platformSelect.addEventListener("change", () => {
      state.platform = els.platformSelect.value;
      refresh();
    });
    els.sortSelect.addEventListener("change", () => {
      state.sortBy = els.sortSelect.value;
      refresh();
    });

    els.resetBtn.addEventListener("click", resetAllFilters);
    els.emptyResetBtn.addEventListener("click", resetAllFilters);
    els.loadMoreBtn.addEventListener("click", () => refresh(true));

    els.grid.addEventListener("click", (e) => {
      const yearBtn = e.target.closest("[data-year-pick]");
      if (yearBtn) {
        e.stopPropagation();
        selectYear(yearBtn.dataset.yearPick);
        return;
      }
      const card = e.target.closest(".drama-card");
      if (card) onOpenDrama(Number(card.dataset.dramaId));
    });

    els.grid.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const yearBtn = e.target.closest("[data-year-pick]");
        if (yearBtn) {
          e.stopPropagation();
          selectYear(yearBtn.dataset.yearPick);
          return;
        }
        const card = e.target.closest(".drama-card");
        if (card) onOpenDrama(Number(card.dataset.dramaId));
      }
    });

    els.updatesGrid.addEventListener("click", (e) => {
      const mini = e.target.closest("[data-update-drama-id]");
      if (mini) onOpenDrama(Number(mini.dataset.updateDramaId));
    });

    els.updatesGrid.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const mini = e.target.closest("[data-update-drama-id]");
        if (mini) onOpenDrama(Number(mini.dataset.updateDramaId));
      }
    });

    els.dismissShelfBtn.addEventListener("click", () => {
      els.updatesShelf.classList.add("is-hidden");
    });

    els.checkUpdatesBtn.addEventListener("click", checkForUpdates);
  }

  bindEvents();

  return {
    loadTaxonomyFilters,
    loadSpotlight,
    refreshLastUpdatedLabel,
    refresh,
    applyTropeFilter,
    selectYear,
    setNavMode,
    resetAllFilters,
  };
}
