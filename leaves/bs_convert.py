"""
AD ↔ BS date conversion, ported from Module:नेपाली मिति (Lua).
Base reference: AD 1943-04-14 = BS 2000-01-01
Supported BS range: 1975–2099
"""

from datetime import date, timedelta
from calendar import month_abbr

# ── BS month-length lookup table ────────────────────────────────────────────
_BS: dict[int, list[int]] = {}

_BS[1975] = [31, 31, 32, 32, 31, 30, 30, 29, 30, 29, 30, 30]
_BS[1976] = [31, 32, 31, 32, 31, 30, 30, 30, 29, 29, 30, 31]
_BS[1977] = [30, 32, 31, 32, 31, 31, 29, 30, 30, 29, 29, 31]
_BS[1978] = [31, 31, 32, 31, 31, 31, 30, 29, 30, 29, 30, 30]
_BS[1979] = _BS[1975]
_BS[1980] = _BS[1976]
_BS[1981] = [31, 31, 31, 32, 31, 31, 29, 30, 30, 29, 29, 31]
_BS[1982] = _BS[1978]
_BS[1983] = _BS[1975]
_BS[1984] = _BS[1976]
_BS[1985] = [31, 31, 31, 32, 31, 31, 29, 30, 30, 29, 30, 30]
_BS[1986] = _BS[1978]
_BS[1987] = [31, 32, 31, 32, 31, 30, 30, 29, 30, 29, 30, 30]
_BS[1988] = _BS[1976]
_BS[1989] = [31, 31, 31, 32, 31, 31, 30, 29, 30, 29, 30, 30]
_BS[1990] = _BS[1978]
_BS[1991] = [31, 32, 31, 32, 31, 30, 30, 30, 29, 29, 30, 30]
_BS[1992] = [31, 32, 31, 32, 31, 30, 30, 30, 29, 30, 29, 31]
_BS[1993] = _BS[1989]
_BS[1994] = _BS[1978]
_BS[1995] = _BS[1991]
_BS[1996] = _BS[1992]
_BS[1997] = _BS[1978]
_BS[1998] = [31, 31, 32, 31, 32, 30, 30, 29, 30, 29, 30, 30]
_BS[1999] = _BS[1976]
_BS[2000] = [30, 32, 31, 32, 31, 30, 30, 30, 29, 30, 29, 31]
_BS[2001] = _BS[1978]
_BS[2002] = _BS[1975]
_BS[2003] = _BS[1976]
_BS[2004] = _BS[2000]
_BS[2005] = _BS[1978]
_BS[2006] = _BS[1975]
_BS[2007] = _BS[1976]
_BS[2008] = _BS[1981]
_BS[2009] = _BS[1978]
_BS[2010] = _BS[1975]
_BS[2011] = _BS[1976]
_BS[2012] = _BS[1985]
_BS[2013] = _BS[1978]
_BS[2014] = _BS[1975]
_BS[2015] = _BS[1976]
_BS[2016] = _BS[1985]
_BS[2017] = _BS[1978]
_BS[2018] = _BS[1987]
_BS[2019] = _BS[1992]
_BS[2020] = _BS[1989]
_BS[2021] = _BS[1978]
_BS[2022] = _BS[1991]
_BS[2023] = _BS[1992]
_BS[2024] = _BS[1989]
_BS[2025] = _BS[1978]
_BS[2026] = _BS[1976]
_BS[2027] = _BS[2000]
_BS[2028] = _BS[1978]
_BS[2029] = _BS[1998]
_BS[2030] = _BS[1976]
_BS[2031] = _BS[2000]
_BS[2032] = _BS[1978]
_BS[2033] = _BS[1975]
_BS[2034] = _BS[1976]
_BS[2035] = _BS[1977]
_BS[2036] = _BS[1978]
_BS[2037] = _BS[1975]
_BS[2038] = _BS[1976]
_BS[2039] = _BS[1985]
_BS[2040] = _BS[1978]
_BS[2041] = _BS[1975]
_BS[2042] = _BS[1976]
_BS[2043] = _BS[1985]
_BS[2044] = _BS[1978]
_BS[2045] = _BS[1987]
_BS[2046] = _BS[1976]
_BS[2047] = _BS[1989]
_BS[2048] = _BS[1978]
_BS[2049] = _BS[1991]
_BS[2050] = _BS[1992]
_BS[2051] = _BS[1989]
_BS[2052] = _BS[1978]
_BS[2053] = _BS[1991]
_BS[2054] = _BS[1992]
_BS[2055] = _BS[1978]
_BS[2056] = _BS[1998]
_BS[2057] = _BS[1976]
_BS[2058] = _BS[2000]
_BS[2059] = _BS[1978]
_BS[2060] = _BS[1975]
_BS[2061] = _BS[1976]
_BS[2062] = [30, 32, 31, 32, 31, 31, 29, 30, 29, 30, 29, 31]
_BS[2063] = _BS[1978]
_BS[2064] = _BS[1975]
_BS[2065] = _BS[1976]
_BS[2066] = _BS[1981]
_BS[2067] = _BS[1978]
_BS[2068] = _BS[1975]
_BS[2069] = _BS[1976]
_BS[2070] = _BS[1985]
_BS[2071] = _BS[1978]
_BS[2072] = _BS[1987]
_BS[2073] = _BS[1976]
_BS[2074] = _BS[1989]
_BS[2075] = _BS[1978]
_BS[2076] = _BS[1991]
_BS[2077] = _BS[1992]
_BS[2078] = _BS[1989]
_BS[2079] = _BS[1978]
_BS[2080] = _BS[1991]
_BS[2081] = _BS[1992]
_BS[2082] = _BS[1989]
_BS[2083] = _BS[1978]
_BS[2084] = _BS[1976]
_BS[2085] = _BS[2000]
_BS[2086] = _BS[1978]
_BS[2087] = _BS[1975]
_BS[2088] = _BS[1976]
_BS[2089] = _BS[2000]
_BS[2090] = _BS[1978]
_BS[2091] = _BS[1975]
_BS[2092] = _BS[1976]
_BS[2093] = _BS[1981]
_BS[2094] = _BS[1978]
_BS[2095] = _BS[1975]
_BS[2096] = _BS[1976]
_BS[2097] = _BS[1985]
_BS[2098] = _BS[1978]
_BS[2099] = _BS[1975]

# ── Base reference ────────────────────────────────────────────────────────────
_BASE_AD = date(1943, 4, 14)
_BASE_BS_YEAR  = 2000
_BASE_BS_MONTH = 1
_BASE_BS_DAY   = 1


def ad_to_bs(ad_date: date) -> tuple[int, int, int]:
    offset = (ad_date - _BASE_AD).days

    bs_y, bs_m, bs_d = _BASE_BS_YEAR, _BASE_BS_MONTH, _BASE_BS_DAY

    if offset > 0:
        for _ in range(offset):
            months = _BS.get(bs_y)
            if months is None:
                raise ValueError(f"BS year {bs_y} not in lookup table")
            bs_d += 1
            if bs_d > months[bs_m - 1]:
                bs_d = 1
                bs_m += 1
                if bs_m > 12:
                    bs_m = 1
                    bs_y += 1
    elif offset < 0:
        for _ in range(-offset):
            bs_d -= 1
            if bs_d < 1:
                bs_m -= 1
                if bs_m < 1:
                    bs_m = 12
                    bs_y -= 1
                months = _BS.get(bs_y)
                if months is None:
                    raise ValueError(f"BS year {bs_y} not in lookup table")
                bs_d = months[bs_m - 1]

    if not (1975 <= bs_y <= 2099):
        raise ValueError(f"Resulting BS year {bs_y} out of supported range 1975–2099")

    return bs_y, bs_m, bs_d


def bs_to_ad(bs_year: int, bs_month: int, bs_day: int) -> date:
    """Convert a BS date to its corresponding AD date."""
    if not (1975 <= bs_year <= 2099):
        raise ValueError(f"BS year {bs_year} out of supported range 1975–2099")

    # Count total days from the base (BS 2000-01-01) to the target BS date
    total = 0

    # Add full BS years from base year up to (not including) target year
    for y in range(_BASE_BS_YEAR, bs_year):
        months = _BS.get(y)
        if months is None:
            raise ValueError(f"BS year {y} not in lookup table")
        total += sum(months)

    # Add full months in the target year up to (not including) target month
    months = _BS.get(bs_year)
    if months is None:
        raise ValueError(f"BS year {bs_year} not in lookup table")
    for mo in range(1, bs_month):
        total += months[mo - 1]

    # Add days within target month (1-indexed so subtract 1)
    total += bs_day - 1

    return _BASE_AD + timedelta(days=total)


# ── Month names ───────────────────────────────────────────────────────────────

BS_MONTHS = [
    "Baisakh", "Jestha", "Asar", "Shrawan",
    "Bhadra", "Ashwin", "Kartik", "Mangsir",
    "Poush", "Magh", "Falgun", "Chaitra",
]

def bs_month_name(month: int) -> str:
    """Return English BS month name for 1-indexed month number."""
    return BS_MONTHS[month - 1]


def format_bs_date(bs_year: int, bs_month: int, bs_day: int, include_year: bool = True) -> str:
    """Format a BS date as 'Baisakh 1, 2083'."""
    name = bs_month_name(bs_month)
    if include_year:
        return f"{name} {bs_day}, {bs_year}"
    return f"{name} {bs_day}"


def ad_to_bs_display(ad_date: date, include_year: bool = True) -> str:
    """Convert AD date to formatted BS string. Returns original on error."""
    try:
        bs_y, bs_m, bs_d = ad_to_bs(ad_date)
        return format_bs_date(bs_y, bs_m, bs_d, include_year)
    except (ValueError, AttributeError):
        return str(ad_date)


def build_ad_label(start_ad: date, end_ad: date) -> str:
    """
    Build a compact AD label for a BS month's date range.
    e.g. 'Jun 2026' if same month, 'Jun/Jul 2026' if spans two months
    in the same year, 'Dec 2026/Jan 2027' if it spans a year boundary.
    """
    if start_ad.month == end_ad.month and start_ad.year == end_ad.year:
        return f"{month_abbr[start_ad.month]} {start_ad.year}"
    elif start_ad.year == end_ad.year:
        return f"{month_abbr[start_ad.month]}/{month_abbr[end_ad.month]} {start_ad.year}"
    else:
        return f"{month_abbr[start_ad.month]} {start_ad.year}/{month_abbr[end_ad.month]} {end_ad.year}"


# ── Fiscal year helpers ───────────────────────────────────────────────────────

_NP_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")

def to_nepali_digits(s: str) -> str:
    return str(s).translate(_NP_DIGITS)

def bs_fiscal_year(ad_date: date) -> str:
    bs_y, bs_m, _ = ad_to_bs(ad_date)
    if bs_m >= 4:
        fy_start = bs_y
    else:
        fy_start = bs_y - 1
    fy_end_short = (fy_start + 1) % 100
    return f"{fy_start}–{fy_end_short:02d}"

def bs_fiscal_year_nepali(ad_date: date) -> str:
    return to_nepali_digits(bs_fiscal_year(ad_date))