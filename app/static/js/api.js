/**
 * Клиентский модуль взаимодействия с REST API и SSE-потоками FastAPI.
 */

const JSON_HEADERS = { "Content-Type": "application/json" };

async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `Ошибка запроса (${response.status})`;
    try {
      const errData = await response.json();
      if (errData && errData.detail) {
        message = errData.detail;
      }
    } catch {
      // ignore json parse failure
    }
    throw new Error(message);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

export const api = {
  getDramas(params = {}) {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") {
        qs.set(k, String(v));
      }
    });
    return request(`/api/dramas?${qs.toString()}`);
  },

  getDramaDetail(dramaId) {
    return request(`/api/dramas/${dramaId}`);
  },

  createDrama(payload) {
    return request("/api/dramas", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    });
  },

  getRecommendations(dramaId, limit = 6) {
    return request(`/api/dramas/${dramaId}/recommendations?limit=${limit}`);
  },

  searchDramas(query, disableLayoutFix = false) {
    const qs = new URLSearchParams({
      q: query,
      limit: "36",
      disable_layout_fix: String(disableLayoutFix),
    });
    return request(`/api/search?${qs.toString()}`);
  },

  autocomplete(query) {
    const qs = new URLSearchParams({ q: query, limit: "10" });
    return request(`/api/search/autocomplete?${qs.toString()}`);
  },

  getGenres() {
    return request("/api/genres");
  },

  getTropes() {
    return request("/api/tropes");
  },

  getPlatforms() {
    return request("/api/platforms");
  },

  getYears() {
    return request("/api/years");
  },

  getPersonDetail(personId) {
    return request(`/api/persons/${personId}`);
  },

  getGraph({ centerType = "drama", centerId = null, depth = 2, includeCast = true, includeTropes = true, includeGenres = true } = {}) {
    const qs = new URLSearchParams({
      center_type: centerType,
      depth: String(depth),
      include_cast: String(includeCast),
      include_tropes: String(includeTropes),
      include_genres: String(includeGenres),
    });
    if (centerId !== null && centerId !== undefined) {
      qs.set("center_id", String(centerId));
    }
    return request(`/api/graph?${qs.toString()}`);
  },

  getLists() {
    return request("/api/lists");
  },

  createList(name, description = "") {
    return request("/api/lists", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ name, description }),
    });
  },

  deleteList(listId) {
    return request(`/api/lists/${listId}`, { method: "DELETE" });
  },

  upsertListItem(listId, payload) {
    return request(`/api/lists/${listId}/items`, {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    });
  },

  removeListItem(listId, dramaId) {
    return request(`/api/lists/${listId}/items/${dramaId}`, { method: "DELETE" });
  },

  getOverview() {
    return request("/api/overview");
  },

  getSyncStatus() {
    return request("/api/sync/status");
  },

  openSyncStream(mode = "auto") {
    const qs = new URLSearchParams({ mode });
    return new EventSource(`/api/sync/stream?${qs.toString()}`);
  },

  runBenchmark() {
    return request("/api/benchmark");
  },
};
