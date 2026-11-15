"""Window the satellite observations of the plot cover.

SMAP and IMERG answer slowly (an AppEEARS job, a pile of daily granules), so
the recommendation reads them from the cache and refreshes them in the
background. That only works if the window is the same for everyone who asks
during the month: complete calendar months, ending with last month.
"""

from __future__ import annotations

from datetime import date, timedelta


def add_months(month_start: date, months: int) -> date:
    """First day of the calendar month [months] after [month_start]."""
    total = month_start.year * 12 + month_start.month - 1 + months
    return date(total // 12, total % 12 + 1, 1)


def observation_window(months: int, today: date | None = None) -> tuple[date, date]:
    """First and last day of the last [months] complete calendar months."""
    reference = today or date.today()
    end = date(reference.year, reference.month, 1) - timedelta(days=1)
    start = add_months(date(end.year, end.month, 1), -(months - 1))
    return start, end
