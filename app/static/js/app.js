/**
 * Главная точка входа клиентского приложения «Дораматека».
 * Координирует переключение разделов каталога и пользовательских списков,
 * выбор года, фильтр по сюжету и открытие детальных карточек дорам и актёров.
 */

import { createCatalogController } from "./catalogView.js";
import { createDetailModals } from "./dramaModal.js";
import { createListsController } from "./listsView.js";

document.addEventListener("DOMContentLoaded", async () => {
  let currentSection = "catalog";

  const navButtons = document.querySelectorAll(".nav-link[data-nav-mode]");
  const catalogSection = document.getElementById("view-catalog");
  const listsSection = document.getElementById("view-lists");

  function switchTopNav(mode) {
    navButtons.forEach((btn) => btn.classList.toggle("is-active", btn.dataset.navMode === mode));

    if (mode === "lists") {
      currentSection = "lists";
      catalogSection.classList.remove("is-active");
      listsSection.classList.add("is-active");
      listsCtrl.refresh();
    } else {
      currentSection = "catalog";
      listsSection.classList.remove("is-active");
      catalogSection.classList.add("is-active");
      catalogCtrl.setNavMode(mode);
    }
  }

  const modalsCtrl = createDetailModals({
    onFilterByTrope: (tropeSlug) => {
      switchTopNav("all");
      catalogCtrl.applyTropeFilter(tropeSlug);
    },
    onSelectYear: (year) => {
      switchTopNav("all");
      catalogCtrl.selectYear(year);
    },
    onListsChanged: () => {
      if (currentSection === "lists") {
        listsCtrl.refresh();
      }
    },
  });

  const catalogCtrl = createCatalogController({
    onOpenDrama: (id) => modalsCtrl.openDrama(id),
    onOpenPerson: (id) => modalsCtrl.openPerson(id),
  });

  const listsCtrl = createListsController({
    onOpenDrama: (id) => modalsCtrl.openDrama(id),
  });

  navButtons.forEach((btn) => {
    btn.addEventListener("click", () => switchTopNav(btn.dataset.navMode));
  });

  document.querySelector(".brand-wordmark").addEventListener("click", (e) => {
    e.preventDefault();
    navButtons.forEach((btn) => btn.classList.toggle("is-active", btn.dataset.navMode === "all"));
    currentSection = "catalog";
    listsSection.classList.remove("is-active");
    catalogSection.classList.add("is-active");
    catalogCtrl.resetAllFilters();
  });

  // Первичная загрузка каталога
  await Promise.all([
    catalogCtrl.loadTaxonomyFilters(),
    catalogCtrl.loadSpotlight(),
    catalogCtrl.refreshLastUpdatedLabel(),
  ]);
  await catalogCtrl.refresh();
});
