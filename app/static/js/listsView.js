/**
 * Контроллер пользовательских списков просмотра, оценок и заметок.
 */

import { api } from "./api.js";
import { escapeHtml, formatStatusRu, showToast } from "./uiHelpers.js";

export function createListsController({ onOpenDrama }) {
  const tabsEl = document.getElementById("lists-tabs");
  const contentEl = document.getElementById("lists-content");
  const createForm = document.getElementById("create-list-form");
  const newListInput = document.getElementById("new-list-name");

  let activeListId = null;
  let cachedLists = [];

  async function refresh() {
    try {
      cachedLists = await api.getLists();
      if (!cachedLists.length) return;

      if (!activeListId || !cachedLists.some((l) => l.id === activeListId)) {
        activeListId = cachedLists[0].id;
      }
      renderTabs();
      renderActiveList();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  function renderTabs() {
    tabsEl.innerHTML = cachedLists
      .map(
        (lst) => `
          <button type="button" class="seg-tab ${lst.id === activeListId ? "is-active" : ""}" data-list-id="${lst.id}">
            ${escapeHtml(lst.name)} (${lst.items_count})
          </button>
        `
      )
      .join("");
  }

  function renderActiveList() {
    const active = cachedLists.find((l) => l.id === activeListId);
    if (!active) return;

    const deleteListHeader = !active.is_system
      ? `
        <div class="catalog-meta-bar">
          <span class="meta-summary">${escapeHtml(active.description || "Пользовательская подборка")}</span>
          <button type="button" id="btn-delete-active-list" class="btn btn-danger">Удалить список</button>
        </div>
      `
      : `<div class="catalog-meta-bar"><span class="meta-summary">${escapeHtml(active.description)}</span></div>`;

    if (!active.items || !active.items.length) {
      contentEl.innerHTML = `
        ${deleteListHeader}
        <div class="empty-state">
          <h3>В списке «${escapeHtml(active.name)}» пока пусто</h3>
          <p>Откройте любую дораму в каталоге и добавьте её в этот список, чтобы отслеживать прогресс.</p>
        </div>
      `;
    } else {
      const rowsHtml = active.items
        .map(
          (item) => `
            <div class="list-item-row" data-drama-id="${item.drama_id}">
              <div>
                <button type="button" class="btn-link" style="padding: 0; font-size: 1rem; color: var(--text-primary);" data-open-drama="${item.drama_id}">
                  ${escapeHtml(item.title_ru)}
                </button>
                <div class="drama-card-meta">
                  ${escapeHtml(item.release_year)} · ${escapeHtml(formatStatusRu(item.status))} · Рейтинг БЗ: ★ ${Number(item.global_rating).toFixed(1)}
                </div>
                ${item.notes ? `<div class="drama-card-tropes">${escapeHtml(item.notes)}</div>` : ""}
              </div>
              <div class="mono-num" style="font-size: 0.86rem;">
                Серий: ${item.watched_episodes} / ${item.episodes_count}
              </div>
              <div class="mono-num" style="font-size: 0.9rem; color: var(--accent-sage);">
                ${item.personal_rating ? `Моя оценка: ${Number(item.personal_rating).toFixed(1)}` : "Без оценки"}
              </div>
              <button type="button" class="btn btn-secondary" data-remove-item="${item.drama_id}">Убрать</button>
            </div>
          `
        )
        .join("");

      contentEl.innerHTML = deleteListHeader + rowsHtml;
    }

    const delBtn = document.getElementById("btn-delete-active-list");
    if (delBtn) {
      delBtn.addEventListener("click", async () => {
        try {
          await api.deleteList(active.id);
          showToast(`Список «${active.name}» удалён`);
          activeListId = null;
          refresh();
        } catch (err) {
          showToast(err.message, "error");
        }
      });
    }

    contentEl.querySelectorAll("[data-open-drama]").forEach((btn) => {
      btn.addEventListener("click", () => onOpenDrama(Number(btn.dataset.openDrama)));
    });

    contentEl.querySelectorAll("[data-remove-item]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const dramaId = Number(btn.dataset.removeItem);
        try {
          await api.removeListItem(active.id, dramaId);
          showToast("Дорама удалена из списка");
          refresh();
        } catch (err) {
          showToast(err.message, "error");
        }
      });
    });
  }

  tabsEl.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-list-id]");
    if (!btn) return;
    activeListId = Number(btn.dataset.listId);
    renderTabs();
    renderActiveList();
  });

  createForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = newListInput.value.trim();
    if (!name) return;
    try {
      const created = await api.createList(name);
      newListInput.value = "";
      activeListId = created.id;
      showToast(`Создан список «${created.name}»`);
      refresh();
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  return { refresh };
}
