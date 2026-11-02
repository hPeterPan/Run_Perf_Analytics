from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from garmin_personal_api import (
    GarminPersonalApiClient,
    HttpError,
    PersonalApiAuthenticator,
)

from config.settings import get_settings



logger = logging.getLogger(__name__)

PAGE_SIZE = 20
MAX_ATTEMPTS = 3
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class ExtractResult:

    activities: list[dict[str, Any]] = field(default_factory=list)
    failed_ids: list[int] = field(default_factory=list)


class GarminExtractor:

    def __init__(
            self,
            api_key: str,
            raw_dir: Path | None = None,
            request_delay: float = 0.25,
    ) -> None:
        self._api_key = api_key
        self._raw_dir = raw_dir
        self._delay = request_delay
        self._auth = PersonalApiAuthenticator()
        token = self._auth.obtain_token(api_key)
        self._client = GarminPersonalApiClient(token.access_token)

    def close(self) -> None:
        self._client.close()
        self._auth.close()

    def __enter__(self) -> GarminExtractor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _call(self, func:Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        refreshed = False

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return func(*args, **kwargs)
            except HttpError as exc:
                if exc.status_code == 401 and not refreshed:
                    logger.warning("Bearer token rejected: fetching a new one")
                    refreshed = True
                    token = self._auth.obtain_token(self._api_key, force_refresh = True)
                    self._client.update_bearer_token(token.access_token)
                    continue
                if exc.status_code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
                    wait = 2**attempt
                    logger.warning(
                        "Http %s from Garmin, retrying in %ss (attempt %s/%s)",
                        exc.status_code, wait, attempt, MAX_ATTEMPTS,
                    )
                    time.sleep(wait)
                    continue
                raise

    def list_run_ids(
            self,
            start_date: date | str,
            end_date: date | str | None = None,
            max_activities: int = 100,
    ) -> list[int]:
        ids: list[int] = []
        start = 0
        while len(ids) < max_activities:
            page = self._call(
                self._client.search_activities,
                start = start,
                limit = PAGE_SIZE,
                start_date = start_date,
                end_date = end_date,
                activity_type = "running",
            )

            if not isinstance(page, list):
                raise TypeError(f"Expected a list of activities, got {type(page).__name__}")
            ids.extend(int(item["activityId"]) for item in page)
            if len(page) < PAGE_SIZE:
                break
            start += PAGE_SIZE
        return ids[:max_activities]

    def get_activity(self, activity_id: int) -> dict[str, Any]:
        activity = self._call(self._client.get_activity, activity_id)
        if not isinstance (activity, dict):
            raise TypeError(f"unexpected response for activity {activity_id}")
        if self._raw_dir is not None:
            self._raw_dir.mkdir(parents=True, exist_ok=True)
            path = self._raw_dir / f"activity_{activity_id}.json"
            path.write_text(json.dumps(activity, indent=2))
        return activity

    def fetch_runs(
            self,
            start_date: date | str,
            end_date: date | str | None = None,
            max_activities: int = 100,
    ) -> ExtractResult:
        result = ExtractResult()
        for activity_id in self.list_run_ids(start_date, end_date, max_activities):
            try:
                result.activities.append(self.get_activity(activity_id))
            except Exception:
                logger.exception("failed to fetch activity %s", activity_id)
                result.failed_ids.append(activity_id)
            time.sleep(self._delay)
        logger.info(
            "fetched %s run(s); %s failed", len(result.activities), len(result.failed_ids)
        )
        return result

def create_extractor(save_raw: bool = True) -> GarminExtractor:
        settings = get_settings(require_database = False)
        return GarminExtractor(
            settings.garmin_api_key,
            raw_dir = settings.raw_data_dir if save_raw else None,
        )



if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    since = date.today() - timedelta(days =30)
    with create_extractor() as extractor:
        result = extractor.fetch_runs(since, max_activities = 3)

    for activity in result.activities:
        s = activity["summaryDTO"]
        print(
            f"{activity['activityId']}  {s['startTimeLocal'][:10]}  "
            f"{s['distance'] / 1000:.2f} km     {s['duration'] / 60:.1f} min    "
            f"avg HR {s.get('averageHR')}"
        )