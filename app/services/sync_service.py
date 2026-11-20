"""Сервис автономного пополнения и синхронизации базы знаний (TMDB API + Оффлайн JSON + APScheduler).

Обеспечивает:
- Плановое фоновое обновление новых корейских дорам и онгоингов через APScheduler;
- Ручной запуск обновления с потоковой передачей прогресса (SSE) в веб-интерфейс;
- Идемпотентный UPSERT в SQL без дублей + автоназначение сюжетных тропов по синопсису;
- Автоматический переход на резервный оффлайн JSON-датасет при отсутствии ключа или сети.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.db.connection import DatabaseManager, get_db_manager
from app.db.repositories.sync_repo import SyncTelemetryRepository
from app.db.seed import slugify_text, upsert_drama_bundle, upsert_reference_dictionaries
from app.services.auto_tagger import TropeAutoTagger
from app.services.search_engine import get_search_engine

logger = get_logger(__name__)


TMDB_GENRE_SLUG_BY_ID: Dict[int, str] = {
    18: "drama",
    10749: "romance",
    53: "thriller",
    80: "crime",
    9648: "mystery",
    10765: "fantasy",
    35: "comedy",
    10759: "action",
    36: "historical",
    878: "scifi",
    10751: "slice-of-life",
    99: "medical",
}

TMDB_NETWORK_MAP: Dict[str, str] = {
    "tvn": "tvn",
    "netflix": "netflix",
    "jtbc": "jtbc",
    "sbs": "sbs",
    "kbs2": "kbs2",
    "kbs 2tv": "kbs2",
    "mbc": "mbc",
    "ena": "ena",
    "disney+": "disney-plus",
    "coupang play": "coupang-play",
    "ocn": "ocn",
    "tving": "tving",
    "wavve": "wavve",
    "apple tv+": "apple-tv",
}

TMDB_GENRE_NAME_RU_BY_SLUG: Dict[str, str] = {
    "drama": "драма",
    "romance": "романтика",
    "thriller": "триллер",
    "crime": "криминал",
    "mystery": "детектив",
    "fantasy": "фэнтези",
    "comedy": "комедия",
    "action": "боевик",
    "historical": "история",
    "scifi": "фантастика",
    "slice-of-life": "повседневность",
    "medical": "медицина",
}

_KO_SURNAME_RU: Dict[str, str] = {
    "park": "Пак", "pak": "Пак",
    "kim": "Ким",
    "lee": "Ли", "yi": "Ли", "rhee": "Ли",
    "jung": "Чон", "jeong": "Чон", "chon": "Чон",
    "jang": "Чан", "chang": "Чан",
    "kang": "Кан", "gang": "Кан",
    "cho": "Чо", "jo": "Чо",
    "choi": "Чхве", "choe": "Чхве",
    "yoon": "Юн", "yun": "Юн",
    "han": "Хан",
    "seo": "Со", "suh": "Со",
    "shin": "Шин", "sin": "Шин",
    "kwon": "Квон", "gwon": "Квон",
    "hwang": "Хван",
    "ahn": "Ан", "an": "Ан",
    "song": "Сон",
    "lim": "Лим", "im": "Им",
    "yoo": "Ю", "yu": "Ю", "you": "Ю",
    "oh": "О",
    "cha": "Чха",
    "jeon": "Чон", "jun": "Чон",
    "nam": "Нам",
    "moon": "Мун", "mun": "Мун",
    "baek": "Пэк", "paik": "Пэк",
    "heo": "Хо", "hur": "Хо", "huh": "Хо",
    "ryu": "Рю", "yoo-ryu": "Рю",
    "byeon": "Пён", "byun": "Пён",
    "chae": "Чхэ",
    "go": "Ко", "ko": "Ко", "koh": "Ко",
    "koo": "Ку", "gu": "Ку", "goo": "Ку",
    "bae": "Пэ",
    "ha": "Ха",
    "hong": "Хон",
    "yang": "Ян",
    "yeo": "Ё",
    "woo": "У",
    "seong": "Сон", "sung": "Сон",
    "son": "Сон",
    "na": "На", "ra": "Ра",
    "ma": "Ма",
    "ji": "Чи",
    "jin": "Чжин",
    "ki": "Ки", "gi": "Ки",
    "do": "До",
    "no": "Но", "noh": "Но", "roh": "Но",
    "uhm": "Ом", "eom": "Ом",
    "chu": "Чху", "choo": "Чху",
    "gong": "Кон", "kong": "Кон",
    "kwak": "Квак",
    "sim": "Шим", "shim": "Шим",
    "won": "Вон",
    "yeom": "Ём",
    "bang": "Пан",
    "min": "Мин",
    "seol": "Соль", "sul": "Соль",
    "joo": "Чу", "ju": "Чу",
    "soo": "Су", "su": "Су",
    "tae": "Тхэ",
    "ok": "Ок",
}

_KO_SYLLABLE_RU: Dict[str, str] = {
    "hyo": "Хё", "hye": "Хе", "hyun": "Хён", "hyeon": "Хён", "hyung": "Хён", "hyeong": "Хён",
    "hyuk": "Хёк", "hyeok": "Хёк", "hoon": "Хун", "hun": "Хун", "han": "Хан", "ha": "Ха",
    "hae": "Хэ", "ho": "Хо", "hee": "Хи", "hui": "Хи", "hwa": "Хва", "hwan": "Хван",
    "seok": "Сок", "suk": "Сок", "seon": "Сон", "sun": "Сон", "seong": "Сон", "sung": "Сон",
    "seung": "Сын", "seo": "Со", "se": "Се", "si": "Ши", "shin": "Шин", "shik": "Шик", "sik": "Шик",
    "sang": "Сан", "san": "Сан", "sol": "Соль", "soo": "Су", "su": "Су", "soon": "Сун",
    "seul": "Сыль", "seop": "Соп", "seob": "Соп", "sub": "Соп", "song": "Сон",
    "yeong": "Ён", "young": "Ён", "yeon": "Ён", "yun": "Юн", "yoon": "Юн", "yoo": "Ю", "yu": "Ю",
    "ye": "Е", "yeo": "Ё", "yo": "Ё", "yong": "Ён",
    "joon": "Джун", "jun": "Джун", "jung": "Джон", "jeong": "Джон", "jeon": "Чон",
    "jin": "Джин", "ji": "Джи", "jae": "Джэ", "joo": "Джу", "ju": "Джу", "jang": "Джан",
    "min": "Мин", "mi": "Ми", "moon": "Мун", "mun": "Мун", "myung": "Мён", "myeong": "Мён",
    "woo": "У", "won": "Вон", "wook": "Ук", "uk": "Ук", "wan": "Ван", "wang": "Ван", "wi": "Ви",
    "bo": "Бо", "bin": "Бин", "byeol": "Бёль", "byul": "Бёль", "beom": "Бом", "bum": "Бом",
    "baek": "Бэк", "bae": "Пэ",
    "ra": "Ра", "ran": "Ран", "ri": "Ри", "rin": "Рин", "rim": "Рим", "ro": "Ро",
    "ryeo": "Рё", "ryeong": "Рён", "ryu": "Рю",
    "eun": "Ын", "ae": "Э", "ah": "А", "a": "А", "eom": "Ом", "eui": "Ый", "ui": "Ый",
    "kyung": "Кён", "gyeong": "Гён", "kyu": "Кю", "gyu": "Гю", "ki": "Ки", "gi": "Ги",
    "gun": "Гон", "geon": "Гон", "geun": "Гын", "gwang": "Кван", "kwang": "Кван", "gyeom": "Гём",
    "tae": "Тхэ", "dae": "Дэ", "dong": "Дон", "do": "До", "dam": "Дам", "da": "Да",
    "chan": "Чан", "chang": "Чан", "chae": "Чхэ", "cheol": "Чхоль", "chul": "Чхоль",
    "cheon": "Чхон", "chi": "Чи", "cho": "Чо", "choi": "Чхве",
    "il": "Иль", "in": "Ин", "na": "На", "nam": "Нам", "neul": "Ныль", "no": "Но",
    "ok": "Ок", "on": "Он", "oh": "О",
    "woong": "Ун", "ung": "Ун", "kang": "Кан", "gang": "Кан", "ko": "Ко", "go": "Ко",
    "kwon": "Квон", "gwon": "Квон", "cha": "Чха", "so": "Со", "sa": "Са",
}

_LATIN_DIGRAPH_FALLBACK = [
    ("yeo", "ё"), ("yoo", "ю"), ("you", "ю"), ("woo", "у"), ("soo", "су"), ("joo", "джу"),
    ("choo", "чху"), ("sh", "ш"), ("ch", "ч"), ("th", "т"), ("ph", "п"), ("wh", "хв"),
    ("oo", "у"), ("ee", "и"), ("ae", "э"), ("oe", "ве"), ("eo", "о"), ("eu", "ы"),
    ("ya", "я"), ("yo", "ё"), ("yu", "ю"), ("ye", "е"), ("wa", "ва"), ("wo", "во"),
    ("wi", "ви"), ("ng", "н"), ("jj", "чч"), ("kk", "кк"), ("tt", "тт"), ("pp", "пп"),
    ("ss", "сс"), ("ck", "к"), ("qu", "кв"),
]

_LATIN_CHAR_FALLBACK = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г",
    "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н",
    "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у",
    "v": "в", "w": "в", "x": "кс", "y": "й", "z": "з",
}


def _transliterate_token(token: str) -> str:
    low = token.lower()
    if low in _KO_SYLLABLE_RU:
        return _KO_SYLLABLE_RU[low]
    # Пробуем разбить слитный двусложный токен (например, "boyoung" -> "bo"+"young")
    if len(low) >= 4:
        for split_at in range(2, len(low) - 1):
            left, right = low[:split_at], low[split_at:]
            if left in _KO_SYLLABLE_RU and right in _KO_SYLLABLE_RU:
                return f"{_KO_SYLLABLE_RU[left]} {_KO_SYLLABLE_RU[right]}"

    out: List[str] = []
    i = 0
    while i < len(low):
        matched = False
        for src, dst in _LATIN_DIGRAPH_FALLBACK:
            if low.startswith(src, i):
                out.append(dst)
                i += len(src)
                matched = True
                break
        if not matched:
            out.append(_LATIN_CHAR_FALLBACK.get(low[i], low[i]))
            i += 1
    res = "".join(out)
    return res[:1].upper() + res[1:] if res else token


_HANGUL_INITIALS = [
    "к", "кк", "н", "т", "тт", "р", "м", "п", "пп", "с", "сс", "", "ч", "чч", "чх", "кх", "тх", "пх", "х",
]
_HANGUL_MEDIALS = [
    "а", "э", "я", "йя", "о", "е", "ё", "йе", "о", "ва", "вэ", "ве", "ё", "у", "во", "ве", "ви", "ю", "ы", "ый", "и",
]
_HANGUL_FINALS = [
    "", "к", "к", "к", "н", "н", "н", "т", "ль", "к", "м", "ль", "ль", "льтх", "льпх", "ль",
    "м", "п", "п", "т", "т", "н", "т", "т", "к", "т", "п", "т",
]


def _hangul_to_russian(text: str) -> str:
    """Транскрибирует корейский хангыль на русский язык по системе Концевича."""
    syllables: List[str] = []
    for ch in text:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            offset = code - 0xAC00
            ini = offset // 588
            med = (offset % 588) // 28
            fin = offset % 28
            # Упрощённая межвокальная и начальная адаптация: ㅇ в начале немой, ㅎ в конце часто немой
            part = f"{_HANGUL_INITIALS[ini]}{_HANGUL_MEDIALS[med]}{_HANGUL_FINALS[fin]}"
            syllables.append(part)
        elif ch.isspace():
            syllables.append(" ")
    if not syllables:
        return text
    if len(syllables) >= 2 and " " not in syllables:
        # Стандартное корейское ФИО: 1 слог фамилия + остальные имя
        surname = syllables[0].capitalize()
        given = "".join(syllables[1:]).capitalize()
        return f"{surname} {given}"
    return "".join(syllables).title()


def roman_to_russian(name: str) -> str:
    """Транслитерирует латинизированное или хангыль корейское имя в русскую запись."""
    cleaned = (name or "").strip()
    if not cleaned:
        return ""
    if any("\u0400" <= ch <= "\u04ff" for ch in cleaned):
        return cleaned
    if any(0xAC00 <= ord(ch) <= 0xD7A3 for ch in cleaned):
        return _hangul_to_russian(cleaned)

    raw_parts = cleaned.replace("-", " ").split()
    if not raw_parts:
        return cleaned

    ru_parts: List[str] = []
    for idx, part in enumerate(raw_parts):
        low = part.lower()
        if idx == 0 and low in _KO_SURNAME_RU:
            ru_parts.append(_KO_SURNAME_RU[low])
        else:
            ru_parts.append(_transliterate_token(part))
    return " ".join(p for p in ru_parts if p)


class SyncOrchestrator:
    """Оркестратор синхронизации БЗ с внешним TMDB API и резервным оффлайн-источником."""

    def __init__(
        self,
        db: Optional[DatabaseManager] = None,
        sync_repo: Optional[SyncTelemetryRepository] = None,
    ) -> None:
        self.settings = get_settings()
        self.db = db or get_db_manager()
        self.sync_repo = sync_repo or SyncTelemetryRepository(self.db)
        self.auto_tagger = TropeAutoTagger(self.db)
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.is_running: bool = False
        self._sync_lock = asyncio.Lock()

    def start_scheduler(self) -> None:
        """Запускает фоновый планировщик APScheduler."""
        if not self.settings.sync_enabled:
            logger.info("APScheduler disabled by configuration.")
            return
        if self.scheduler is not None and self.scheduler.running:
            return

        self.scheduler = AsyncIOScheduler(timezone=timezone.utc)
        self.scheduler.add_job(
            self.run_scheduled_sync,
            trigger=IntervalTrigger(hours=self.settings.sync_interval_hours),
            id="kdrama_autonomous_sync",
            replace_existing=True,
            max_instances=1,
        )
        self.scheduler.start()
        logger.info(
            "APScheduler started: autonomous sync every %d hours",
            self.settings.sync_interval_hours,
        )

    def stop_scheduler(self) -> None:
        """Корректно останавливает фоновый планировщик."""
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("APScheduler stopped.")

    def get_status(self) -> Dict[str, Any]:
        """Возвращает текущее состояние планировщика и историю синхронизаций."""
        next_run: Optional[str] = None
        active = bool(self.scheduler and self.scheduler.running)
        if active and self.scheduler is not None:
            job = self.scheduler.get_job("kdrama_autonomous_sync")
            if job and job.next_run_time:
                next_run = job.next_run_time.isoformat()

        return {
            "is_running": self.is_running,
            "scheduler_active": active,
            "interval_hours": self.settings.sync_interval_hours,
            "next_run_at": next_run,
            "has_tmdb_key": self.settings.has_tmdb_key,
            "recent_logs": self.sync_repo.get_sync_logs(limit=15),
        }

    async def run_scheduled_sync(self) -> Dict[str, Any]:
        """Фоновая задача планировщика (без SSE-потребителя)."""
        summary: Dict[str, Any] = {}
        async for event in self.stream_sync(mode="auto", trigger_type="scheduled"):
            if event.get("event") == "complete":
                summary = event["data"]
        return summary

    async def stream_sync(
        self,
        mode: str = "auto",
        trigger_type: str = "manual",
    ) -> AsyncIterator[Dict[str, Any]]:
        """Асинхронный генератор событий синхронизации для живого прогресс-бара (SSE)."""
        if self._sync_lock.locked():
            yield {
                "event": "error",
                "data": {"message": "Синхронизация уже выполняется. Дождитесь завершения текущего цикла."},
            }
            return

        async with self._sync_lock:
            self.is_running = True
            actual_source = self._resolve_source_mode(mode)
            log_id = self.sync_repo.create_sync_log(source=actual_source, trigger_type=trigger_type)

            scanned = 0
            added = 0
            updated = 0
            tropes_assigned = 0
            details: List[Dict[str, Any]] = []
            fallback_used = False

            try:
                yield {
                    "event": "start",
                    "data": {
                        "log_id": log_id,
                        "source": actual_source,
                        "trigger_type": trigger_type,
                        "message": f"Инициализация синхронизации (источник: {actual_source})...",
                        "progress": 5,
                    },
                }
                await asyncio.sleep(0.15)

                batch_payload: Dict[str, Any]
                if actual_source == "tmdb_api":
                    try:
                        yield {
                            "event": "progress",
                            "data": {
                                "progress": 15,
                                "message": "Поиск новых корейских дорам и проверка онгоингов в TMDB API v3...",
                            },
                        }
                        batch_payload = await self._fetch_from_tmdb()
                    except Exception as api_exc:
                        logger.warning("TMDB API fetch failed (%s), switching to offline delta.", api_exc)
                        if not self.settings.sync_offline_fallback:
                            raise
                        fallback_used = True
                        actual_source = "offline_json"
                        yield {
                            "event": "progress",
                            "data": {
                                "progress": 20,
                                "message": f"TMDB API недоступен ({api_exc}). Переключение на оффлайн JSON-резерв...",
                            },
                        }
                        batch_payload = self._load_offline_delta()
                else:
                    yield {
                        "event": "progress",
                        "data": {
                            "progress": 20,
                            "message": "Чтение локального дельта-пакета и проверка онгоингов...",
                        },
                    }
                    batch_payload = self._load_offline_delta()
                    await asyncio.sleep(0.15)

                dramas_list = batch_payload.get("dramas", [])
                total_items = max(len(dramas_list), 1)

                with self.db.write_session() as conn:
                    # Сначала убеждаемся, что актуальные справочники на месте
                    base_dataset = json.loads(self.settings.offline_dataset_path.read_text(encoding="utf-8"))
                    merged_refs = {
                        "genres": base_dataset.get("genres", []) + batch_payload.get("genres", []),
                        "platforms": base_dataset.get("platforms", []) + batch_payload.get("platforms", []),
                        "tropes": base_dataset.get("tropes", []) + batch_payload.get("tropes", []),
                        "persons": base_dataset.get("persons", []) + batch_payload.get("persons", []),
                    }
                    maps = upsert_reference_dictionaries(conn, merged_refs)

                    for idx, drama_item in enumerate(dramas_list, start=1):
                        scanned += 1
                        drama_id, action = upsert_drama_bundle(conn, drama_item, maps)

                        # Автоматически извлекаем сюжетные тропы по синопсису (RU + EN) и тегам
                        extracted = self.auto_tagger.apply_auto_tags(
                            conn=conn,
                            drama_id=drama_id,
                            synopsis_ru=drama_item.get("synopsis_ru", ""),
                            synopsis_en=drama_item.get("synopsis_en", ""),
                            extra_keywords=drama_item.get("tmdb_keywords", []),
                        )
                        tropes_assigned += len(extracted)

                        if action == "added":
                            added += 1
                        elif action == "updated":
                            updated += 1

                        item_log = {
                            "drama_id": drama_id,
                            "slug": drama_item["slug"],
                            "title_ru": drama_item["title_ru"],
                            "status": drama_item.get("status", "Completed"),
                            "rating": drama_item.get("rating", 0.0),
                            "action": action,
                            "auto_tropes": [t.name_ru for t in extracted[:4]],
                        }
                        details.append(item_log)

                        pct = 25 + int((idx / total_items) * 65)
                        yield {
                            "event": "item",
                            "data": {
                                "index": idx,
                                "total": total_items,
                                "progress": pct,
                                "item": item_log,
                            },
                        }
                        await asyncio.sleep(0.15)

                # Перестраиваем поисковый индекс в памяти после обновления БЗ
                yield {
                    "event": "progress",
                    "data": {
                        "progress": 95,
                        "message": "Перестроение индекса нечёткого поиска в памяти...",
                    },
                }
                get_search_engine().rebuild_index()

                final_status = "partial" if fallback_used else "completed"
                self.sync_repo.complete_sync_log(
                    log_id=log_id,
                    status=final_status,
                    dramas_scanned=scanned,
                    dramas_added=added,
                    dramas_updated=updated,
                    tropes_assigned=tropes_assigned,
                    details=details,
                )

                yield {
                    "event": "complete",
                    "data": {
                        "log_id": log_id,
                        "source": actual_source,
                        "status": final_status,
                        "progress": 100,
                        "dramas_scanned": scanned,
                        "dramas_added": added,
                        "dramas_updated": updated,
                        "tropes_assigned": tropes_assigned,
                        "details": details,
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    },
                }
            except Exception as exc:
                logger.exception("Sync failed: %s", exc)
                self.sync_repo.complete_sync_log(
                    log_id=log_id,
                    status="failed",
                    dramas_scanned=scanned,
                    dramas_added=added,
                    dramas_updated=updated,
                    tropes_assigned=tropes_assigned,
                    details=details,
                    error_message=str(exc),
                )
                yield {
                    "event": "error",
                    "data": {"message": f"Ошибка синхронизации: {exc}", "log_id": log_id},
                }
            finally:
                self.is_running = False

    def _resolve_source_mode(self, requested_mode: str) -> str:
        if requested_mode == "offline":
            return "offline_json"
        if requested_mode == "tmdb":
            return "tmdb_api" if self.settings.has_tmdb_key else "offline_json"
        return "tmdb_api" if self.settings.has_tmdb_key else "offline_json"

    def _load_offline_delta(self) -> Dict[str, Any]:
        """Загружает резервный JSON-пакет для оффлайн-пополнения и обновления онгоингов."""
        delta_path = self.settings.sync_delta_path
        if not delta_path.exists():
            return {"genres": [], "platforms": [], "tropes": [], "persons": [], "dramas": []}
        return json.loads(delta_path.read_text(encoding="utf-8"))

    async def _discover_unseen_tmdb_ids(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        existing_tmdb_ids: set[int],
        limit_new: int = 8,
        max_pages: int = 25,
    ) -> List[int]:
        """Сканирует страницы /discover/tv и отбирает ещё не загруженные в БЗ корейские дорамы."""
        base = self.settings.tmdb_base_url
        lang = self.settings.tmdb_language
        selected_with_overview: List[int] = []
        selected_fallback: List[int] = []
        seen_in_scan: set[int] = set()

        for sort_order in ("popularity.desc", "first_air_date.desc"):
            for page in range(1, max_pages + 1):
                resp = await client.get(
                    f"{base}/discover/tv",
                    params={
                        "api_key": api_key,
                        "with_origin_country": "KR",
                        "with_original_language": "ko",
                        "without_genres": "10764,10767,10763,10762",
                        "vote_count.gte": 10,
                        "sort_by": sort_order,
                        "language": lang,
                        "page": page,
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
                results = payload.get("results", [])
                if not results:
                    break

                for item in results:
                    tid = int(item["id"])
                    if tid in existing_tmdb_ids or tid in seen_in_scan:
                        continue
                    if not item.get("poster_path"):
                        continue
                    seen_in_scan.add(tid)
                    if (item.get("overview") or "").strip():
                        selected_with_overview.append(tid)
                    else:
                        selected_fallback.append(tid)

                if len(selected_with_overview) >= limit_new:
                    return selected_with_overview[:limit_new]

                total_pages = int(payload.get("total_pages") or 1)
                if page >= total_pages:
                    break

            if len(selected_with_overview) + len(selected_fallback) >= limit_new:
                break

        combined = selected_with_overview + selected_fallback
        return combined[:limit_new]

    async def _fetch_from_tmdb(self) -> Dict[str, Any]:
        """Загружает новые корейские дорамы (с постраничным обходом) и обновляет онгоинги из TMDB API v3."""
        api_key = self.settings.tmdb_api_key.strip()
        if not api_key:
            raise RuntimeError("TMDB_API_KEY не задан")

        base = self.settings.tmdb_base_url
        lang = self.settings.tmdb_language
        timeout = self.settings.tmdb_timeout_seconds

        dramas_out: List[Dict[str, Any]] = []
        persons_out: List[Dict[str, Any]] = []
        seen_person_slugs: set[str] = set()
        batch_slugs_used: Dict[str, int] = {}

        with self.db.read_session() as conn:
            existing_rows = conn.execute(
                "SELECT tmdb_id, slug, status FROM dramas"
            ).fetchall()

        existing_tmdb_ids = {int(r["tmdb_id"]) for r in existing_rows if r["tmdb_id"] is not None}
        existing_slug_to_tmdb: Dict[str, Optional[int]] = {
            str(r["slug"]): (int(r["tmdb_id"]) if r["tmdb_id"] is not None else None)
            for r in existing_rows
        }
        ongoing_ids = [
            int(r["tmdb_id"])
            for r in existing_rows
            if r["status"] == "Ongoing" and r["tmdb_id"] is not None
        ]

        async with httpx.AsyncClient(timeout=timeout) as client:
            new_candidate_ids = await self._discover_unseen_tmdb_ids(
                client=client,
                api_key=api_key,
                existing_tmdb_ids=existing_tmdb_ids,
                limit_new=8,
                max_pages=25,
            )

            # К новым дорамам добавляем до 2 онгоингов для актуализации статуса/рейтинга/серий
            target_ids: List[int] = list(new_candidate_ids)
            for oid in ongoing_ids:
                if oid not in target_ids:
                    target_ids.append(oid)
                if len(target_ids) >= len(new_candidate_ids) + 2:
                    break

            new_added_details = 0
            for tmdb_id in target_ids:
                if tmdb_id in new_candidate_ids and new_added_details >= 6:
                    continue

                detail_resp = await client.get(
                    f"{base}/tv/{tmdb_id}",
                    params={
                        "api_key": api_key,
                        "language": lang,
                        "append_to_response": "credits,keywords,translations",
                    },
                )
                if detail_resp.status_code != 200:
                    continue
                tv = detail_resp.json()

                # Пропускаем ток-шоу, новости, детские передачи и реалити
                tv_genre_ids = {g.get("id") for g in tv.get("genres", [])}
                if tv_genre_ids & {10764, 10767, 10763, 10762}:
                    continue

                translations = tv.get("translations", {}).get("translations", [])
                ru_tr_overview = ""
                ru_tr_name = ""
                en_tr_overview = ""
                en_tr_name = ""
                for tr in translations:
                    tr_data = tr.get("data") or {}
                    ov = (tr_data.get("overview") or "").strip()
                    nm = (tr_data.get("name") or "").strip()
                    if tr.get("iso_639_1") == "ru":
                        if ov and not ru_tr_overview:
                            ru_tr_overview = ov
                        if nm and not ru_tr_name:
                            ru_tr_name = nm
                    elif tr.get("iso_639_1") == "en":
                        if ov and not en_tr_overview:
                            en_tr_overview = ov
                        if nm and not en_tr_name:
                            en_tr_name = nm

                title_ru = (tv.get("name") or ru_tr_name or en_tr_name or tv.get("original_name") or f"K-Drama {tmdb_id}").strip()
                title_en = (en_tr_name or tv.get("original_name") or title_ru).strip()
                first_air = tv.get("first_air_date") or "2024-01-01"
                year = int(first_air[:4]) if first_air[:4].isdigit() else 2024

                tmdb_status = tv.get("status", "Ended")
                if tmdb_status in ("Returning Series", "In Production"):
                    mapped_status = "Ongoing"
                elif tmdb_status == "Planned":
                    mapped_status = "Upcoming"
                elif tmdb_status == "Canceled":
                    mapped_status = "Cancelled"
                else:
                    mapped_status = "Completed"

                poster_path = tv.get("poster_path")
                poster_url = f"{self.settings.tmdb_image_base_url}{poster_path}" if poster_path else ""
                backdrop_path = tv.get("backdrop_path")
                backdrop_url = f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else ""

                genre_slugs = [
                    TMDB_GENRE_SLUG_BY_ID[g["id"]]
                    for g in tv.get("genres", [])
                    if g.get("id") in TMDB_GENRE_SLUG_BY_ID
                ] or ["drama"]

                platform_slugs = []
                for net in tv.get("networks", []):
                    key = str(net.get("name", "")).lower().strip()
                    if key in TMDB_NETWORK_MAP:
                        platform_slugs.append(TMDB_NETWORK_MAP[key])

                cast_entries = []
                cast_ru_names: List[str] = []
                for idx, member in enumerate(tv.get("credits", {}).get("cast", [])[:8]):
                    p_name = (member.get("name") or "").strip()
                    if not p_name:
                        continue
                    p_slug = slugify_text(p_name)
                    if not p_slug:
                        continue
                    p_name_ru = roman_to_russian(p_name)
                    if idx < 3:
                        cast_ru_names.append(p_name_ru)
                    profile_path = member.get("profile_path")
                    photo_url = f"https://image.tmdb.org/t/p/w300{profile_path}" if profile_path else ""
                    if p_slug not in seen_person_slugs:
                        seen_person_slugs.add(p_slug)
                        persons_out.append(
                            {
                                "tmdb_person_id": member.get("id"),
                                "slug": p_slug,
                                "name_ru": p_name_ru,
                                "name_en": p_name,
                                "name_kr": member.get("original_name", ""),
                                "primary_profession": "Actor",
                                "photo_url": photo_url,
                            }
                        )
                    cast_entries.append(
                        {
                            "person": p_slug,
                            "role_type": "Main" if idx < 3 else "Support",
                            "character_name": member.get("character", ""),
                            "billing_order": idx + 1,
                        }
                    )

                synopsis_ru = (tv.get("overview") or "").strip() or ru_tr_overview
                synopsis_en = en_tr_overview
                if not synopsis_ru:
                    genres_txt = ", ".join(TMDB_GENRE_NAME_RU_BY_SLUG.get(g, g) for g in genre_slugs[:3])
                    cast_txt = f" В главных ролях: {', '.join(cast_ru_names)}." if cast_ru_names else ""
                    synopsis_ru = f"Корейский сериал {year} года ({genres_txt}).{cast_txt}"

                kw_list = [k.get("name", "") for k in tv.get("keywords", {}).get("results", [])]
                base_slug = slugify_text(title_en or title_ru)
                if not base_slug or len(base_slug) < 3:
                    base_slug = f"tmdb-{tmdb_id}"
                owner_tmdb = existing_slug_to_tmdb.get(base_slug)
                if (base_slug in existing_slug_to_tmdb and owner_tmdb != tmdb_id) or (
                    base_slug in batch_slugs_used and batch_slugs_used[base_slug] != tmdb_id
                ):
                    computed_slug = f"{base_slug}-{tmdb_id}"
                else:
                    computed_slug = base_slug
                batch_slugs_used[computed_slug] = tmdb_id

                if tmdb_id in new_candidate_ids:
                    new_added_details += 1

                dramas_out.append(
                    {
                        "tmdb_id": tmdb_id,
                        "slug": computed_slug,
                        "title_ru": title_ru,
                        "title_en": title_en,
                        "title_kr": tv.get("original_name", ""),
                        "title_romaja": "",
                        "synopsis_ru": synopsis_ru,
                        "synopsis_en": synopsis_en,
                        "release_year": year,
                        "first_air_date": first_air,
                        "episodes_count": max(1, int(tv.get("number_of_episodes") or 16)),
                        "episode_runtime": int((tv.get("episode_run_time") or [65])[0]),
                        "status": mapped_status,
                        "rating": round(float(tv.get("vote_average") or 8.0), 1),
                        "votes_count": int(tv.get("vote_count") or 100),
                        "popularity_score": float(tv.get("popularity") or 50.0),
                        "poster_url": poster_url,
                        "backdrop_url": backdrop_url,
                        "genres": genre_slugs,
                        "platforms": platform_slugs or ["netflix"],
                        "tropes": [],
                        "cast": cast_entries,
                        "tmdb_keywords": kw_list,
                    }
                )

        return {
            "genres": [],
            "platforms": [],
            "tropes": [],
            "persons": persons_out,
            "dramas": dramas_out,
        }


_sync_orchestrator: Optional[SyncOrchestrator] = None


def get_sync_orchestrator() -> SyncOrchestrator:
    """Возвращает синглтон оркестратора синхронизации."""
    global _sync_orchestrator
    if _sync_orchestrator is None:
        _sync_orchestrator = SyncOrchestrator()
    return _sync_orchestrator
