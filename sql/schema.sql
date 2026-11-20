-- ============================================================================
-- БАЗА ЗНАНИЙ «КОРЕЙСКИЕ ДОРАМЫ» (K-DRAMA KNOWLEDGE BASE)
-- СУБД: SQLite 3.35+ / PostgreSQL compatible (3НФ)
-- ============================================================================

PRAGMA foreign_keys = ON;

-- 1. Справочник жанров
CREATE TABLE IF NOT EXISTS genres (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tmdb_genre_id INTEGER UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    name_ru TEXT NOT NULL UNIQUE,
    name_en TEXT NOT NULL UNIQUE
);

-- 2. Справочник телеканалов и стриминговых платформ
CREATE TABLE IF NOT EXISTS platforms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    country TEXT NOT NULL DEFAULT 'KR',
    platform_type TEXT NOT NULL DEFAULT 'TV' CHECK (platform_type IN ('TV', 'OTT', 'Cable'))
);

-- 3. База персон (актёры, режиссёры, сценаристы)
CREATE TABLE IF NOT EXISTS persons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tmdb_person_id INTEGER UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    name_ru TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_kr TEXT NOT NULL DEFAULT '',
    primary_profession TEXT NOT NULL DEFAULT 'Actor' CHECK (primary_profession IN ('Actor', 'Director', 'Writer', 'Creator')),
    birth_year INTEGER DEFAULT NULL,
    bio_short TEXT NOT NULL DEFAULT '',
    photo_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 4. Семантическая таксономия сюжетных тропов (онтологические маркеры)
CREATE TABLE IF NOT EXISTS tropes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name_ru TEXT NOT NULL UNIQUE,
    name_en TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'Сюжет' CHECK (category IN ('Романтика', 'Сюжет', 'Сеттинг', 'Характеры', 'Детектив', 'Мистика')),
    description TEXT NOT NULL DEFAULT '',
    keywords_json TEXT NOT NULL DEFAULT '[]',
    base_weight REAL NOT NULL DEFAULT 0.70 CHECK (base_weight > 0.0 AND base_weight <= 1.0)
);

-- 5. Центральная сущность БЗ — Дорамы (фреймы объектов)
CREATE TABLE IF NOT EXISTS dramas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tmdb_id INTEGER UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    title_ru TEXT NOT NULL,
    title_en TEXT NOT NULL,
    title_kr TEXT NOT NULL DEFAULT '',
    title_romaja TEXT NOT NULL DEFAULT '',
    synopsis_ru TEXT NOT NULL DEFAULT '',
    synopsis_en TEXT NOT NULL DEFAULT '',
    release_year INTEGER NOT NULL CHECK (release_year >= 1980 AND release_year <= 2035),
    first_air_date TEXT DEFAULT '',
    episodes_count INTEGER NOT NULL DEFAULT 16 CHECK (episodes_count >= 1),
    episode_runtime INTEGER NOT NULL DEFAULT 60 CHECK (episode_runtime >= 5),
    status TEXT NOT NULL DEFAULT 'Completed' CHECK (status IN ('Ongoing', 'Completed', 'Upcoming', 'Cancelled')),
    rating REAL NOT NULL DEFAULT 0.0 CHECK (rating >= 0.0 AND rating <= 10.0),
    votes_count INTEGER NOT NULL DEFAULT 0 CHECK (votes_count >= 0),
    popularity_score REAL NOT NULL DEFAULT 0.0,
    poster_url TEXT NOT NULL DEFAULT '',
    backdrop_url TEXT NOT NULL DEFAULT '',
    age_rating TEXT NOT NULL DEFAULT '16+',
    content_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 6. Связь дорам и жанров (M:M)
CREATE TABLE IF NOT EXISTS drama_genres (
    drama_id INTEGER NOT NULL,
    genre_id INTEGER NOT NULL,
    PRIMARY KEY (drama_id, genre_id),
    FOREIGN KEY (drama_id) REFERENCES dramas(id) ON DELETE CASCADE,
    FOREIGN KEY (genre_id) REFERENCES genres(id) ON DELETE CASCADE
);

-- 7. Связь дорам и платформ вещания (M:M)
CREATE TABLE IF NOT EXISTS drama_platforms (
    drama_id INTEGER NOT NULL,
    platform_id INTEGER NOT NULL,
    is_original INTEGER NOT NULL DEFAULT 0 CHECK (is_original IN (0, 1)),
    PRIMARY KEY (drama_id, platform_id),
    FOREIGN KEY (drama_id) REFERENCES dramas(id) ON DELETE CASCADE,
    FOREIGN KEY (platform_id) REFERENCES platforms(id) ON DELETE CASCADE
);

-- 8. Взвешенные семантические связи дорама—троп (векторные веса для рекомендаций)
CREATE TABLE IF NOT EXISTS drama_tropes (
    drama_id INTEGER NOT NULL,
    trope_id INTEGER NOT NULL,
    weight REAL NOT NULL DEFAULT 0.75 CHECK (weight > 0.0 AND weight <= 1.0),
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'auto_tagger', 'tmdb_keyword')),
    matched_keywords TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (drama_id, trope_id),
    FOREIGN KEY (drama_id) REFERENCES dramas(id) ON DELETE CASCADE,
    FOREIGN KEY (trope_id) REFERENCES tropes(id) ON DELETE CASCADE
);

-- 9. Роли персон в дорамах (каст и съёмочная группа)
CREATE TABLE IF NOT EXISTS cast_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drama_id INTEGER NOT NULL,
    person_id INTEGER NOT NULL,
    role_type TEXT NOT NULL DEFAULT 'Main' CHECK (role_type IN ('Main', 'Support', 'Cameo', 'Director', 'Writer')),
    character_name TEXT NOT NULL DEFAULT '',
    billing_order INTEGER NOT NULL DEFAULT 10,
    FOREIGN KEY (drama_id) REFERENCES dramas(id) ON DELETE CASCADE,
    FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE CASCADE,
    UNIQUE (drama_id, person_id, role_type)
);

-- 10. Пользовательские коллекции и списки
CREATE TABLE IF NOT EXISTS user_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    list_type TEXT NOT NULL DEFAULT 'custom' CHECK (list_type IN ('watching', 'planned', 'completed', 'favorites', 'custom')),
    description TEXT NOT NULL DEFAULT '',
    is_system INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 11. Элементы списков пользователей с личными оценками и прогрессом
CREATE TABLE IF NOT EXISTS user_list_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id INTEGER NOT NULL,
    drama_id INTEGER NOT NULL,
    personal_rating REAL DEFAULT NULL CHECK (personal_rating IS NULL OR (personal_rating >= 1.0 AND personal_rating <= 10.0)),
    watched_episodes INTEGER NOT NULL DEFAULT 0 CHECK (watched_episodes >= 0),
    notes TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (list_id) REFERENCES user_lists(id) ON DELETE CASCADE,
    FOREIGN KEY (drama_id) REFERENCES dramas(id) ON DELETE CASCADE,
    UNIQUE (list_id, drama_id)
);

-- 12. Журнал автономных синхронизаций БЗ (ETL-аудит)
CREATE TABLE IF NOT EXISTS sync_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK (source IN ('tmdb_api', 'offline_json', 'hybrid', 'seed')),
    trigger_type TEXT NOT NULL CHECK (trigger_type IN ('scheduled', 'manual', 'startup')),
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    dramas_scanned INTEGER NOT NULL DEFAULT 0,
    dramas_added INTEGER NOT NULL DEFAULT 0,
    dramas_updated INTEGER NOT NULL DEFAULT 0,
    tropes_assigned INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '[]',
    error_message TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT DEFAULT NULL
);

-- 13. Телеметрия нечёткого поиска (оценка качества и времени отклика)
CREATE TABLE IF NOT EXISTS search_telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_query TEXT NOT NULL,
    normalized_query TEXT NOT NULL DEFAULT '',
    corrected_query TEXT NOT NULL DEFAULT '',
    correction_type TEXT NOT NULL DEFAULT 'none' CHECK (correction_type IN ('none', 'exact', 'typo', 'layout', 'layout_and_typo')),
    top_score REAL NOT NULL DEFAULT 0.0,
    results_count INTEGER NOT NULL DEFAULT 0,
    latency_ms REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Оптимизирующие индексы для быстрого поиска и рекомендаций
CREATE INDEX IF NOT EXISTS idx_dramas_title_ru ON dramas(title_ru);
CREATE INDEX IF NOT EXISTS idx_dramas_title_en ON dramas(title_en);
CREATE INDEX IF NOT EXISTS idx_dramas_year_rating ON dramas(release_year DESC, rating DESC);
CREATE INDEX IF NOT EXISTS idx_persons_name_ru ON persons(name_ru);
CREATE INDEX IF NOT EXISTS idx_cast_roles_drama ON cast_roles(drama_id, billing_order);
CREATE INDEX IF NOT EXISTS idx_drama_tropes_trope ON drama_tropes(trope_id, weight DESC);
CREATE INDEX IF NOT EXISTS idx_drama_genres_genre ON drama_genres(genre_id);
CREATE INDEX IF NOT EXISTS idx_search_telemetry_created ON search_telemetry(created_at DESC);