/**
 * Модальные окна детальной карточки дорамы (с описанием, сюжетом, актёрами,
 * списками и рекомендациями) и профиля персоны.
 */

import { api } from "./api.js";
import {
  closeModal,
  escapeHtml,
  formatRoleTypeRu,
  formatStatusRu,
  openModal,
  renderPosterMarkup,
  showToast,
} from "./uiHelpers.js";

export function createDetailModals({
  onFilterByTrope,
  onSelectYear,
  onListsChanged,
}) {
  const dramaBody = document.getElementById("drama-modal-body");
  const personBody = document.getElementById("person-modal-body");

  document.getElementById("btn-close-drama-modal").addEventListener("click", () => closeModal("drama-modal"));
  document.getElementById("btn-close-person-modal").addEventListener("click", () => closeModal("person-modal"));

  document.getElementById("drama-modal").addEventListener("click", (e) => {
    if (e.target.id === "drama-modal") closeModal("drama-modal");
  });
  document.getElementById("person-modal").addEventListener("click", (e) => {
    if (e.target.id === "person-modal") closeModal("person-modal");
  });

  async function openDrama(dramaId) {
    dramaBody.innerHTML = `<p class="meta-summary">Загрузка карточки дорамы...</p>`;
    openModal("drama-modal");

    try {
      const [drama, recResp, lists] = await Promise.all([
        api.getDramaDetail(dramaId),
        api.getRecommendations(dramaId, 6),
        api.getLists(),
      ]);
      renderDramaModal(drama, recResp.recommendations || [], lists);
    } catch (err) {
      dramaBody.innerHTML = `<p class="meta-summary" style="color: var(--accent-coral);">${escapeHtml(err.message)}</p>`;
    }
  }

  function renderDramaModal(drama, recommendations, lists) {
    const genresLine = (drama.genres || []).map((g) => g.name_ru).join(", ") || "—";
    const platformsLine = (drama.platforms || []).map((p) => p.name).join(", ") || "—";

    const tropesHtml = (drama.tropes || []).length
      ? drama.tropes
          .map(
            (t) => `
              <button type="button" class="trope-action-row" data-trope-slug="${escapeHtml(t.slug)}">
                <span>${escapeHtml(t.name_ru)}</span>
                <span class="mono-num" style="font-size: 0.8rem; color: var(--accent-gold);">подобрать похожее</span>
              </button>
            `
          )
          .join("")
      : `<p class="meta-summary">Сюжетные мотивы ещё не добавлены.</p>`;

    function renderActorAvatar(person, cssClass) {
      const hasPhoto = Boolean(person.photo_url && person.photo_url.trim());
      const initials = (person.name_ru || person.name_en || "?")
        .split(/\s+/)
        .slice(0, 2)
        .map((w) => w[0] || "")
        .join("")
        .toUpperCase();
      const imgTag = hasPhoto
        ? `<img src="${escapeHtml(person.photo_url)}" alt="${escapeHtml(person.name_ru)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';" />`
        : "";
      const fallbackDisplay = hasPhoto ? "none" : "flex";
      return `
        <div class="${cssClass}">
          ${imgTag}
          <div class="cast-avatar-fallback" style="display: ${fallbackDisplay}">${escapeHtml(initials)}</div>
        </div>
      `;
    }

    const castHtml = (drama.cast || []).length
      ? drama.cast
          .map(
            (c) => `
              <button type="button" class="cast-btn" data-person-id="${c.id}">
                ${renderActorAvatar(c, "cast-avatar")}
                <div class="cast-info">
                  <span class="cast-name">${escapeHtml(c.name_ru)}</span>
                  <span class="cast-role ${c.role_type === "Main" ? "is-main" : ""}">${escapeHtml(formatRoleTypeRu(c.role_type))}${c.character_name ? ` · ${escapeHtml(c.character_name)}` : ""}</span>
                </div>
              </button>
            `
          )
          .join("")
      : `<p class="meta-summary">Информация о составе появится после обновления каталога.</p>`;

    const recHtml = recommendations.length
      ? recommendations
          .map((rec) => {
            const exp = rec.explanation;
            const reasons = [];
            if (exp.shared_tropes.length) reasons.push(`Тропы: ${exp.shared_tropes.slice(0, 3).join(", ")}`);
            if (exp.shared_genres.length) reasons.push(`Жанры: ${exp.shared_genres.join(", ")}`);
            if (exp.shared_persons.length) reasons.push(`Актёры/авторы: ${exp.shared_persons.join(", ")}`);

            return `
              <div class="rec-card" data-rec-drama-id="${rec.drama.id}" tabindex="0">
                <div class="rec-header">
                  <span class="rec-title">${escapeHtml(rec.drama.title_ru)}</span>
                  <span class="rec-match">${rec.match_percent}% совпадение</span>
                </div>
                <div class="drama-card-meta">${escapeHtml(rec.drama.release_year)} · ★ ${Number(rec.drama.rating).toFixed(1)}</div>
                <div class="rec-reason">${escapeHtml(reasons.join(" · ") || "Схожее настроение и тематика")}</div>
              </div>
            `;
          })
          .join("")
      : `<p class="meta-summary">Пока нет похожих подборок.</p>`;

    const existingEntry = (drama.user_entries || [])[0];
    const defaultListId = existingEntry ? existingEntry.list_id : (lists[0] ? lists[0].id : "");

    const listOptionsHtml = lists
      .map(
        (l) => `<option value="${l.id}" ${Number(l.id) === Number(defaultListId) ? "selected" : ""}>${escapeHtml(l.name)}</option>`
      )
      .join("");

    dramaBody.innerHTML = `
      <div class="detail-hero">
        <div class="detail-poster">
          ${renderPosterMarkup(drama)}
        </div>
        <div>
          <h2 id="modal-drama-title" class="detail-title-ru">${escapeHtml(drama.title_ru)}</h2>
          <p class="detail-title-alt">
            ${escapeHtml(drama.title_en)}${drama.title_kr ? ` · ${escapeHtml(drama.title_kr)}` : ""}${drama.title_romaja ? ` (${escapeHtml(drama.title_romaja)})` : ""}
          </p>
          <div class="detail-meta-line">
            <button type="button" class="year-link" data-modal-year="${escapeHtml(drama.release_year)}" title="Показать все дорамы ${escapeHtml(drama.release_year)} года">${escapeHtml(drama.release_year)} год</button>
            <span>·</span>
            <span>${escapeHtml(formatStatusRu(drama.status))}</span>
            <span>·</span>
            <span>${escapeHtml(drama.episodes_count)} сер. (~${escapeHtml(drama.episode_runtime)} мин)</span>
            <span>·</span>
            <span>${escapeHtml(genresLine)}</span>
            <span>·</span>
            <span>${escapeHtml(platformsLine)}</span>
          </div>
          <p class="detail-synopsis">${escapeHtml(drama.synopsis_ru || "Описание временно отсутствует.")}</p>
        </div>
      </div>

      <div class="detail-section">
        <h3 class="detail-section-title">Сохранить в мой список</h3>
        <form id="drama-list-form" class="list-assign-form">
          <label>
            <span>Список</span>
            <select name="list_id">${listOptionsHtml}</select>
          </label>
          <label>
            <span>Просмотрено серий (из ${drama.episodes_count})</span>
            <input name="watched_episodes" type="number" min="0" max="${drama.episodes_count}" value="${existingEntry ? existingEntry.watched_episodes : 0}" />
          </label>
          <label>
            <span>Моя оценка (1–10)</span>
            <input name="personal_rating" type="number" step="0.5" min="1" max="10" value="${existingEntry && existingEntry.personal_rating ? existingEntry.personal_rating : ""}" placeholder="9.0" />
          </label>
          <button type="submit" class="btn btn-primary">Сохранить</button>
        </form>
      </div>

      <div class="detail-section">
        <h3 class="detail-section-title">Сюжетные мотивы (нажмите, чтобы найти похожие дорамы)</h3>
        <div class="trope-rows">${tropesHtml}</div>
      </div>

      <div class="detail-section">
        <h3 class="detail-section-title">Актёрский состав и создатели</h3>
        <div class="cast-grid">${castHtml}</div>
      </div>

      <div class="detail-section">
        <h3 class="detail-section-title">Похожие дорамы</h3>
        <div class="rec-grid">${recHtml}</div>
      </div>
    `;

    const modalYearBtn = dramaBody.querySelector("[data-modal-year]");
    if (modalYearBtn) {
      modalYearBtn.addEventListener("click", () => {
        const y = Number(modalYearBtn.dataset.modalYear);
        closeModal("drama-modal");
        onSelectYear(y);
      });
    }

    dramaBody.querySelector("#drama-list-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const listId = Number(fd.get("list_id"));
      const ratingRaw = fd.get("personal_rating");
      const watched = Number(fd.get("watched_episodes") || 0);
      try {
        await api.upsertListItem(listId, {
          drama_id: drama.id,
          watched_episodes: watched,
          personal_rating: ratingRaw ? Number(ratingRaw) : null,
          notes: existingEntry ? existingEntry.notes : "",
        });
        showToast("Дорама сохранена в ваш список");
        onListsChanged();
      } catch (err) {
        showToast(err.message, "error");
      }
    });

    dramaBody.querySelectorAll(".trope-action-row").forEach((btn) => {
      btn.addEventListener("click", () => {
        closeModal("drama-modal");
        onFilterByTrope(btn.dataset.tropeSlug);
      });
    });

    dramaBody.querySelectorAll(".cast-btn").forEach((btn) => {
      btn.addEventListener("click", () => openPerson(Number(btn.dataset.personId)));
    });

    dramaBody.querySelectorAll(".rec-card").forEach((card) => {
      card.addEventListener("click", () => openDrama(Number(card.dataset.recDramaId)));
    });
  }

  async function openPerson(personId) {
    personBody.innerHTML = `<p class="meta-summary">Загрузка профиля...</p>`;
    openModal("person-modal");

    try {
      const person = await api.getPersonDetail(personId);
      const filmsHtml = (person.filmography || [])
        .map(
          (f) => `
            <div class="rec-card" data-film-drama-id="${f.id}" tabindex="0">
              <div class="rec-header">
                <span class="rec-title">${escapeHtml(f.title_ru)}</span>
                <span class="rec-match">★ ${Number(f.rating).toFixed(1)}</span>
              </div>
              <div class="drama-card-meta">${escapeHtml(f.release_year)} · ${escapeHtml(formatRoleTypeRu(f.role_type))}${f.character_name ? ` (${escapeHtml(f.character_name)})` : ""}</div>
            </div>
          `
        )
        .join("");

      const hasPhoto = Boolean(person.photo_url && person.photo_url.trim());
      const initials = (person.name_ru || person.name_en || "?")
        .split(/\s+/)
        .slice(0, 2)
        .map((w) => w[0] || "")
        .join("")
        .toUpperCase();
      const portraitHtml = `
        <div class="person-portrait">
          ${hasPhoto ? `<img src="${escapeHtml(person.photo_url)}" alt="${escapeHtml(person.name_ru)}" referrerpolicy="no-referrer" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';" />` : ""}
          <div class="cast-avatar-fallback" style="display: ${hasPhoto ? "none" : "flex"}; font-size: 1.4rem;">${escapeHtml(initials)}</div>
        </div>
      `;

      personBody.innerHTML = `
        <div class="person-hero">
          ${portraitHtml}
          <div>
            <h2 id="modal-person-title" class="modal-heading">${escapeHtml(person.name_ru)}</h2>
            <p class="detail-title-alt">${escapeHtml(person.name_en)}${person.name_kr ? ` · ${escapeHtml(person.name_kr)}` : ""}${person.birth_year ? ` · род. ${person.birth_year}` : ""}</p>
            <p class="detail-synopsis">${escapeHtml(person.bio_short || "")}</p>
          </div>
        </div>
        <h3 class="detail-section-title">Дорамы с участием (${(person.filmography || []).length})</h3>
        <div class="rec-grid">${filmsHtml}</div>
      `;

      personBody.querySelectorAll("[data-film-drama-id]").forEach((card) => {
        card.addEventListener("click", () => {
          closeModal("person-modal");
          openDrama(Number(card.dataset.filmDramaId));
        });
      });
    } catch (err) {
      personBody.innerHTML = `<p class="meta-summary" style="color: var(--accent-coral);">${escapeHtml(err.message)}</p>`;
    }
  }

  return {
    openDrama,
    openPerson,
  };
}
