/**
 * Общие вспомогательные функции рендеринга, экранирования и уведомлений.
 */

export function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function formatStatusRu(status) {
  const map = {
    Ongoing: "Онгоинг",
    Completed: "Завершён",
    Upcoming: "Анонс",
    Cancelled: "Закрыт",
  };
  return map[status] || status;
}

export function formatRoleTypeRu(roleType) {
  const map = {
    Main: "Главная роль",
    Support: "Второй план",
    Cameo: "Камео",
    Director: "Режиссёр",
    Writer: "Сценарист",
  };
  return map[roleType] || roleType;
}

/**
 * Рендерит постер дорамы с политикой Zero-Broken-Image:
 * при отсутствии URL или ошибке загрузки отображается стильная типографическая обложка на хангыле.
 */
export function renderPosterMarkup(drama) {
  const hasPoster = Boolean(drama.poster_url && drama.poster_url.trim());
  const krTitle = escapeHtml(drama.title_kr || drama.title_en || drama.title_ru);
  const enTitle = escapeHtml(drama.title_en || "");
  const ratingText = Number(drama.rating || 0).toFixed(1);
  const statusText = formatStatusRu(drama.status);

  const imgHtml = hasPoster
    ? `<img src="${escapeHtml(drama.poster_url)}" alt="${escapeHtml(drama.title_ru)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';" />`
    : "";

  const fallbackDisplay = hasPoster ? "none" : "flex";
  const statusClass = drama.status === "Ongoing" ? "poster-status-text is-ongoing" : "poster-status-text";

  return `
    <div class="poster-frame">
      ${imgHtml}
      <div class="poster-fallback" style="display: ${fallbackDisplay}">
        <div class="poster-fallback-kr">${krTitle}</div>
        <div class="poster-fallback-en">${enTitle} · ${escapeHtml(drama.release_year)}</div>
      </div>
      <div class="poster-scrim"></div>
      <div class="poster-bottom-overlay">
        <span class="poster-rating">★ ${ratingText}</span>
        <span class="${statusClass}">${escapeHtml(statusText)}</span>
      </div>
    </div>
  `;
}

export function showToast(message, variant = "success") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast is-${variant}`;
  toast.textContent = message;
  container.appendChild(toast);

  window.setTimeout(() => {
    toast.remove();
  }, 3600);
}

export function openModal(modalId) {
  const el = document.getElementById(modalId);
  if (el) {
    el.classList.remove("is-hidden");
    document.body.style.overflow = "hidden";
  }
}

export function closeModal(modalId) {
  const el = document.getElementById(modalId);
  if (el) {
    el.classList.add("is-hidden");
    const anyOpen = document.querySelector(".modal-backdrop:not(.is-hidden)");
    if (!anyOpen) {
      document.body.style.overflow = "";
    }
  }
}
