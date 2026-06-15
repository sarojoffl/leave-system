"""
AD → BS date conversion, ported from Module:नेपाली मिति (Lua).
Base reference: AD 1943-04-14 = BS 2000-01-01
Supported BS range: 1975–2099
"""

from datetime import date, timedelta

# ── BS month-length lookup table ────────────────────────────────────────────
# Each list: [Baisakh, Jestha, Asar, Shravan, Bhadra, Ashwin,
#              Kartik, Mangsir, Poush, Magh, Falgun, Chaitra]
# Aliased rows share the same list object (identical pattern), matching Lua.

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
_BASE_AD = date(1943, 4, 14)   # = BS 2000-01-01
_BASE_BS_YEAR  = 2000
_BASE_BS_MONTH = 1
_BASE_BS_DAY   = 1


def ad_to_bs(ad_date: date) -> tuple[int, int, int]:
    """
    Convert a Python date object (AD/Gregorian) to a Bikram Sambat (BS) date.

    Returns (bs_year, bs_month, bs_day).
    bs_month is 1-indexed (1 = Baisakh, 12 = Chaitra).

    Raises ValueError for dates outside the supported BS range 1975–2099.
    """
    offset = (ad_date - _BASE_AD).days  # signed day offset from base

    bs_y, bs_m, bs_d = _BASE_BS_YEAR, _BASE_BS_MONTH, _BASE_BS_DAY

    if offset > 0:
        for _ in range(offset):
            months = _BS.get(bs_y)
            if months is None:
                raise ValueError(f"BS year {bs_y} not in lookup table")
            bs_d += 1
            if bs_d > months[bs_m - 1]:   # months list is 0-indexed
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


def bs_fiscal_year(ad_date: date) -> str:
    """
    Return the Nepali fiscal year string for a given AD date.

    Nepal's fiscal year runs Shrawan 1 to Ashad end (roughly mid-July to mid-July).
    We convert the AD date to BS, then check: if BS month >= 4 (Shrawan = month 4),
    we are in the NEW fiscal year starting that BS year; otherwise we are in the
    fiscal year that started the previous BS year.

    Returns e.g. "२०८१–८२"  (Nepali digits) or use bs_fiscal_year_ascii for "2081–82".
    """
    bs_y, bs_m, _ = ad_to_bs(ad_date)

    # Nepali FY starts Shrawan (month 4)
    if bs_m >= 4:
        fy_start = bs_y
    else:
        fy_start = bs_y - 1

    fy_end_short = (fy_start + 1) % 100   # last two digits
    return f"{fy_start}–{fy_end_short:02d}"


# ── Optional: Nepali-digit formatting ────────────────────────────────────────
_NP_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")

def to_nepali_digits(s: str) -> str:
    return str(s).translate(_NP_DIGITS)

def bs_fiscal_year_nepali(ad_date: date) -> str:
    """Same as bs_fiscal_year() but with Devanagari digits."""
    return to_nepali_digits(bs_fiscal_year(ad_date))
