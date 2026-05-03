"""Malaysia public holidays and cultural events for sales forecasting

Contains Malaysia-specific holiday calendars with consumption pattern data
for the sales forecasting and inventory prediction engines.

All dates are in local Malaysian time (UTC+8).
Cuisine trends reflect real cultural food consumption patterns for each
festival period.

Sources:
    - Jabatan Perdana Menteri (JPM) public holiday gazette
    - Tourism Malaysia cultural event calendar
    - Historical F&B sales data patterns across Malaysian states
"""

from __future__ import annotations

from typing import Any

# ─────────────────────────────────────────────
# 2026 Public Holidays
# ─────────────────────────────────────────────

MALAYSIA_HOLIDAYS_2026: list[dict[str, Any]] = [
    # ── National / Federal Territory ──────────────────────
    {
        "name": "Hari Raya Aidilfitri",
        "date": "2026-03-31",
        "duration_days": 2,
        "impact": "high",
        "cuisine_trend": "ketupat, rendang, lemang, satay, serunding, kuih raya",
        "dine_in_boost": 0.30,
        "takeaway_boost": 0.15,
        "category_boost": {"malay": 0.35, "fusion": 0.10},
        "prep_lead_days": 3,
        "note": "Hari Raya Puasa marks end of Ramadan; first day is 1 Syawal. Major interstate balik kampung travel.",
    },
    {
        "name": "Chinese New Year",
        "date": "2026-02-17",
        "duration_days": 2,
        "impact": "high",
        "cuisine_trend": "yee sang, bak kwa, CNY set menu, prosperity dishes, mandarin oranges",
        "dine_in_boost": 0.25,
        "takeaway_boost": 0.20,
        "category_boost": {"chinese": 0.30, "fusion": 0.15},
        "prep_lead_days": 5,
        "note": "Year of the Horse. Reunion dinner (tuan yuan fan) on eve of CNY drives highest single-night revenue of the year.",
    },
    {
        "name": "Hari Raya Aidiladha",
        "date": "2026-07-07",
        "duration_days": 1,
        "impact": "high",
        "cuisine_trend": "rendang, sup daging, sate daging, gulai kawah",
        "dine_in_boost": 0.20,
        "takeaway_boost": 0.10,
        "category_boost": {"malay": 0.25},
        "prep_lead_days": 2,
        "note": "Hari Raya Haji / Korban. Qurban ritual increases beef/mutton demand significantly.",
    },
    {
        "name": "Deepavali",
        "date": "2026-11-08",
        "duration_days": 1,
        "impact": "medium",
        "cuisine_trend": "indian sweets, murukku, banana leaf rice, curry, pal payasam",
        "dine_in_boost": 0.10,
        "takeaway_boost": 0.05,
        "category_boost": {"indian": 0.20},
        "prep_lead_days": 1,
        "note": "Festival of Lights. Celebrated by Malaysian Indians. Sweet consumption peaks.",
    },
    # ── Movable Muslim Holidays ─────────────────────────
    {
        "name": "Awal Muharram (Maal Hijrah)",
        "date": "2026-07-20",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "traditional malay dishes, bubur lambuk",
        "dine_in_boost": 0.05,
        "takeaway_boost": 0.02,
        "category_boost": {"malay": 0.05},
        "prep_lead_days": 0,
        "note": "Islamic New Year. Modest impact on F&B.",
    },
    {
        "name": "Maulidur Rasul",
        "date": "2026-09-28",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "bubur asyura, traditional malay kuih",
        "dine_in_boost": 0.05,
        "takeaway_boost": 0.02,
        "category_boost": {"malay": 0.05},
        "prep_lead_days": 0,
        "note": "Prophet Muhammad's birthday. Religious events at mosques.",
    },
    {
        "name": "Nuzul Al-Quran",
        "date": "2026-03-17",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "dates, kurma, light iftar meals",
        "dine_in_boost": 0.03,
        "takeaway_boost": 0.03,
        "category_boost": {"malay": 0.05},
        "prep_lead_days": 0,
        "note": "Occurs during Ramadan. Evening iftar demand increase.",
    },
    # ── Ramadan Period ──────────────────────────────────
    {
        "name": "Ramadan Month",
        "date": "2026-03-01",
        "duration_days": 30,
        "impact": "high",
        "cuisine_trend": "kurma, bubur lambuk, nasi kerabu, ayam percik, murtabak, teh tarik",
        "dine_in_boost": -0.20,
        "takeaway_boost": 0.40,
        "category_boost": {"malay": 0.30, "fusion": -0.10},
        "prep_lead_days": 1,
        "note": "Fasting month. Daytime F&B drops sharply; post-iftar (7pm+) takeaway and bazaar sales surge. Bazaar food competition is intense.",
    },
    # ── Buddhist / Chinese Cultural ─────────────────────
    {
        "name": "Wesak Day",
        "date": "2026-05-31",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "vegetarian dishes, kuih tradisional",
        "dine_in_boost": 0.03,
        "takeaway_boost": 0.02,
        "category_boost": {"chinese": 0.05},
        "prep_lead_days": 0,
        "note": "Buddhist celebration of Buddha's birth, enlightenment and passing.",
    },
    {
        "name": "Mid-Autumn Festival",
        "date": "2026-09-27",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "mooncakes, tea, pomelo",
        "dine_in_boost": 0.05,
        "takeaway_boost": 0.03,
        "category_boost": {"chinese": 0.08},
        "prep_lead_days": 3,
        "note": "Mooncake gift-giving drives bakery/premium F&B. Not a gazetted holiday but widely observed by Chinese community.",
    },
    {
        "name": "Dongzhi (Winter Solstice)",
        "date": "2026-12-22",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "tang yuan (glutinous rice balls), family meals",
        "dine_in_boost": 0.05,
        "takeaway_boost": 0.02,
        "category_boost": {"chinese": 0.08},
        "prep_lead_days": 1,
        "note": "Not a public holiday but culturally significant for Chinese families.",
    },
    # ── Christian / Cultural ────────────────────────────
    {
        "name": "Christmas Day",
        "date": "2026-12-25",
        "duration_days": 1,
        "impact": "medium",
        "cuisine_trend": "christmas ham, log cake, roast chicken, festive set dinners",
        "dine_in_boost": 0.15,
        "takeaway_boost": 0.08,
        "category_boost": {"chinese": 0.10, "fusion": 0.15},
        "prep_lead_days": 2,
        "note": "Widely celebrated across all communities in Malaysia. Family gatherings boost dine-in.",
    },
    {
        "name": "Good Friday",
        "date": "2026-04-03",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "fish dishes, light meals",
        "dine_in_boost": 0.03,
        "takeaway_boost": 0.01,
        "category_boost": {},
        "prep_lead_days": 0,
        "note": "Observed in Sabah, Sarawak and Labuan. Christian community.",
    },
    {
        "name": "Easter Sunday",
        "date": "2026-04-05",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "brunch sets, easter eggs",
        "dine_in_boost": 0.05,
        "takeaway_boost": 0.02,
        "category_boost": {},
        "prep_lead_days": 0,
        "note": "Brunch and family meal demand increase.",
    },
    # ── National / State ────────────────────────────────
    {
        "name": "Merdeka Day (National Day)",
        "date": "2026-08-31",
        "duration_days": 1,
        "impact": "medium",
        "cuisine_trend": "malaysian street food, national dishes",
        "dine_in_boost": 0.12,
        "takeaway_boost": 0.08,
        "category_boost": {"malay": 0.10, "chinese": 0.10, "indian": 0.10, "fusion": 0.10},
        "prep_lead_days": 1,
        "note": "Malaysia's Independence Day. Patriotic menus and promotions common.",
    },
    {
        "name": "Malaysia Day",
        "date": "2026-09-16",
        "duration_days": 1,
        "impact": "medium",
        "cuisine_trend": "sabah/sarawak dishes, malaysian street food",
        "dine_in_boost": 0.10,
        "takeaway_boost": 0.06,
        "category_boost": {"fusion": 0.10},
        "prep_lead_days": 0,
        "note": "Formation of Malaysia in 1963. East Malaysia specials often featured.",
    },
    {
        "name": "Labour Day",
        "date": "2026-05-01",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "brunch, family set meals",
        "dine_in_boost": 0.06,
        "takeaway_boost": 0.04,
        "category_boost": {},
        "prep_lead_days": 0,
        "note": "Public holiday. Family outing day boosts mid-range F&B.",
    },
    {
        "name": "Agong's Birthday",
        "date": "2026-06-06",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "",
        "dine_in_boost": 0.03,
        "takeaway_boost": 0.01,
        "category_boost": {},
        "prep_lead_days": 0,
        "note": "Yang di-Pertuan Agong's official birthday. Federal holiday.",
    },
    # ── State-Specific (Penang / Johor / Sabah / Sarawak) ─
    {
        "name": "George Town Heritage Day",
        "date": "2026-07-07",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "penang street food, char koay teow, cendol",
        "dine_in_boost": 0.08,
        "takeaway_boost": 0.04,
        "category_boost": {"chinese": 0.08, "fusion": 0.05},
        "prep_lead_days": 1,
        "note": "Penang UNESCO Heritage Day. Street food tourism peak. Relevant for Penang stores only.",
    },
    {
        "name": "Kaamatan (Harvest Festival)",
        "date": "2026-05-30",
        "duration_days": 2,
        "impact": "medium",
        "cuisine_trend": "hinava, tuhau, bambangan, linopot, sagal, montoku",
        "dine_in_boost": 0.10,
        "takeaway_boost": 0.05,
        "category_boost": {"fusion": 0.10},
        "prep_lead_days": 2,
        "note": "Sabah harvest festival. Indigenous Kadazan-Dusun cuisine demand spikes. Sabah stores only.",
    },
    {
        "name": "Gawai Dayak",
        "date": "2026-06-01",
        "duration_days": 2,
        "impact": "medium",
        "cuisine_trend": "tuak, kasam, pansoh (bamboo chicken), kerabu",
        "dine_in_boost": 0.10,
        "takeaway_boost": 0.05,
        "category_boost": {"fusion": 0.10},
        "prep_lead_days": 2,
        "note": "Sarawak Dayak harvest festival. Tuak (rice wine) and traditional Bidayuh/Iban dishes. Sarawak stores only.",
    },
    {
        "name": "Hari Hol Johor",
        "date": "2026-03-19",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "",
        "dine_in_boost": 0.03,
        "takeaway_boost": 0.01,
        "category_boost": {},
        "prep_lead_days": 0,
        "note": "Johor state holiday only.",
    },
]

# ─────────────────────────────────────────────
# 2027 Public Holidays
# ─────────────────────────────────────────────

MALAYSIA_HOLIDAYS_2027: list[dict[str, Any]] = [
    {
        "name": "Chinese New Year",
        "date": "2027-02-06",
        "duration_days": 2,
        "impact": "high",
        "cuisine_trend": "yee sang, bak kwa, CNY set menu, prosperity dishes, mandarin oranges",
        "dine_in_boost": 0.25,
        "takeaway_boost": 0.20,
        "category_boost": {"chinese": 0.30, "fusion": 0.15},
        "prep_lead_days": 5,
        "note": "Year of the Goat. Reunion dinner drives peak revenue.",
    },
    {
        "name": "Hari Raya Aidilfitri",
        "date": "2027-03-21",
        "duration_days": 2,
        "impact": "high",
        "cuisine_trend": "ketupat, rendang, lemang, satay, serunding, kuih raya",
        "dine_in_boost": 0.30,
        "takeaway_boost": 0.15,
        "category_boost": {"malay": 0.35, "fusion": 0.10},
        "prep_lead_days": 3,
        "note": "End of Ramadan. Balik kampung travel peak.",
    },
    {
        "name": "Ramadan Month",
        "date": "2027-02-19",
        "duration_days": 30,
        "impact": "high",
        "cuisine_trend": "kurma, bubur lambuk, nasi kerabu, ayam percik, murtabak, teh tarik",
        "dine_in_boost": -0.20,
        "takeaway_boost": 0.40,
        "category_boost": {"malay": 0.30, "fusion": -0.10},
        "prep_lead_days": 1,
        "note": "Fasting month. Nighttime and takeaway surge.",
    },
    {
        "name": "Deepavali",
        "date": "2027-10-28",
        "duration_days": 1,
        "impact": "medium",
        "cuisine_trend": "indian sweets, murukku, banana leaf rice, curry, pal payasam",
        "dine_in_boost": 0.10,
        "takeaway_boost": 0.05,
        "category_boost": {"indian": 0.20},
        "prep_lead_days": 1,
        "note": "Festival of Lights.",
    },
    {
        "name": "Christmas Day",
        "date": "2027-12-25",
        "duration_days": 1,
        "impact": "medium",
        "cuisine_trend": "christmas ham, log cake, roast chicken, festive set dinners",
        "dine_in_boost": 0.15,
        "takeaway_boost": 0.08,
        "category_boost": {"chinese": 0.10, "fusion": 0.15},
        "prep_lead_days": 2,
        "note": "Widely celebrated across communities.",
    },
    {
        "name": "Merdeka Day (National Day)",
        "date": "2027-08-31",
        "duration_days": 1,
        "impact": "medium",
        "cuisine_trend": "malaysian street food, national dishes",
        "dine_in_boost": 0.12,
        "takeaway_boost": 0.08,
        "category_boost": {"malay": 0.10, "chinese": 0.10, "indian": 0.10, "fusion": 0.10},
        "prep_lead_days": 1,
        "note": "Malaysia's Independence Day.",
    },
    {
        "name": "Malaysia Day",
        "date": "2027-09-16",
        "duration_days": 1,
        "impact": "medium",
        "cuisine_trend": "sabah/sarawak dishes, malaysian street food",
        "dine_in_boost": 0.10,
        "takeaway_boost": 0.06,
        "category_boost": {"fusion": 0.10},
        "prep_lead_days": 0,
        "note": "Formation of Malaysia.",
    },
    {
        "name": "Hari Raya Aidiladha",
        "date": "2027-06-26",
        "duration_days": 1,
        "impact": "high",
        "cuisine_trend": "rendang, sup daging, sate daging, gulai kawah",
        "dine_in_boost": 0.20,
        "takeaway_boost": 0.10,
        "category_boost": {"malay": 0.25},
        "prep_lead_days": 2,
        "note": "Hari Raya Haji / Korban.",
    },
    {
        "name": "Wesak Day",
        "date": "2027-05-20",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "vegetarian dishes, kuih tradisional",
        "dine_in_boost": 0.03,
        "takeaway_boost": 0.02,
        "category_boost": {"chinese": 0.05},
        "prep_lead_days": 0,
        "note": "Buddhist celebration.",
    },
    {
        "name": "Labour Day",
        "date": "2027-05-01",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "brunch, family set meals",
        "dine_in_boost": 0.06,
        "takeaway_boost": 0.04,
        "category_boost": {},
        "prep_lead_days": 0,
        "note": "Public holiday.",
    },
    {
        "name": "Awal Muharram (Maal Hijrah)",
        "date": "2027-07-08",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "traditional malay dishes",
        "dine_in_boost": 0.05,
        "takeaway_boost": 0.02,
        "category_boost": {"malay": 0.05},
        "prep_lead_days": 0,
        "note": "Islamic New Year.",
    },
    {
        "name": "Maulidur Rasul",
        "date": "2027-09-17",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "bubur asyura, traditional malay kuih",
        "dine_in_boost": 0.05,
        "takeaway_boost": 0.02,
        "category_boost": {"malay": 0.05},
        "prep_lead_days": 0,
        "note": "Prophet Muhammad's birthday.",
    },
    {
        "name": "Agong's Birthday",
        "date": "2027-06-05",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "",
        "dine_in_boost": 0.03,
        "takeaway_boost": 0.01,
        "category_boost": {},
        "prep_lead_days": 0,
        "note": "Yang di-Pertuan Agong's official birthday.",
    },
    {
        "name": "Good Friday",
        "date": "2027-03-26",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "fish dishes, light meals",
        "dine_in_boost": 0.03,
        "takeaway_boost": 0.01,
        "category_boost": {},
        "prep_lead_days": 0,
        "note": "Observed in Sabah, Sarawak and Labuan.",
    },
    {
        "name": "Mid-Autumn Festival",
        "date": "2027-09-15",
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "mooncakes, tea, pomelo",
        "dine_in_boost": 0.05,
        "takeaway_boost": 0.03,
        "category_boost": {"chinese": 0.08},
        "prep_lead_days": 3,
        "note": "Not a gazetted holiday but widely observed.",
    },
]

# ─────────────────────────────────────────────
# School Holidays
# ─────────────────────────────────────────────

MALAYSIA_SCHOOL_HOLIDAYS: list[dict[str, Any]] = [
    {
        "name": "Year End School Holiday",
        "months": [12],
        "duration_weeks": 6,
        "impact": "medium",
        "dine_in_boost": 0.12,
        "takeaway_boost": 0.06,
        "family_meal_boost": 0.20,
        "note": "Mid-Nov to early-Jan. Family dining and tourist areas see significant boost.",
    },
    {
        "name": "Mid Year School Holiday",
        "months": [6],
        "duration_weeks": 2,
        "impact": "low",
        "dine_in_boost": 0.06,
        "takeaway_boost": 0.03,
        "family_meal_boost": 0.10,
        "note": "Late May to early-Jun. Moderate family outing impact.",
    },
    {
        "name": "Hari Raya School Holiday",
        "weeks_before_raya": 1,
        "weeks_after_raya": 1,
        "impact": "high",
        "dine_in_boost": 0.15,
        "takeaway_boost": 0.10,
        "family_meal_boost": 0.25,
        "note": "Variable dates tied to Hari Raya Aidilfitri. Travel corridor impact.",
    },
    {
        "name": "Chinese New Year School Holiday",
        "weeks_before_cny": 0,
        "weeks_after_cny": 1,
        "impact": "medium",
        "dine_in_boost": 0.10,
        "takeaway_boost": 0.08,
        "family_meal_boost": 0.20,
        "note": "Typically 1 week coinciding with CNY.",
    },
    {
        "name": "Mid-Term Break A (Group 1)",
        "months": [3],
        "duration_weeks": 1,
        "impact": "low",
        "dine_in_boost": 0.04,
        "takeaway_boost": 0.02,
        "family_meal_boost": 0.06,
        "note": "Schools in Group 1 (Johor, Kedah, Kelantan, Terengganu).",
    },
    {
        "name": "Mid-Term Break B (Group 2)",
        "months": [3],
        "duration_weeks": 1,
        "impact": "low",
        "dine_in_boost": 0.04,
        "takeaway_boost": 0.02,
        "family_meal_boost": 0.06,
        "note": "Schools in Group 2 (remaining states).",
    },
]

# ─────────────────────────────────────────────
# Seasonality Patterns
# ─────────────────────────────────────────────

MALAYSIA_SEASONALITY: dict[str, dict[str, Any]] = {
    "monsoon_season_nov_mar": {
        "months": [11, 12, 1, 2, 3],
        "impact": "medium",
        "cuisine_trend": "warming soups, spicy broths, steamboat, curry",
        "dine_in_boost": 0.05,
        "delivery_boost": 0.15,
        "note": "Northeast monsoon (Nov-Mar) brings heavy rain to east coast and increased delivery orders.",
    },
    "monsoon_season_apr_oct": {
        "months": [4, 5, 6, 7, 8, 9, 10],
        "impact": "low",
        "cuisine_trend": "cold drinks, ais kacang, cendol, fresh salads, grilled fish",
        "dine_in_boost": 0.08,
        "delivery_boost": -0.05,
        "note": "Southwest monsoon. Hotter weather drives cold beverage and ice dessert demand.",
    },
    "ramadan_bazaar_season": {
        "months": [2, 3],
        "impact": "high",
        "cuisine_trend": "bazaar food, fried chicken, murtabak, curries, kuih-muih, air tebu",
        "dine_in_boost": -0.25,
        "delivery_boost": 0.35,
        "note": "Ramadan bazaars compete heavily with restaurants. Takeaway and delivery surge post-iftar.",
    },
    "durian_season": {
        "months": [6, 7, 8],
        "impact": "low",
        "cuisine_trend": "durian desserts, durian crepes, durian ice cream, pengat durian",
        "dine_in_boost": 0.03,
        "delivery_boost": 0.05,
        "note": "Musang King and D24 durian peak. Durian-themed F&B promotions effective.",
    },
}

# ─────────────────────────────────────────────
# Multi-Day Observance Periods
# ─────────────────────────────────────────────

MALAYSIA_OBSERVANCE_PERIODS: list[dict[str, Any]] = [
    {
        "name": "Chap Goh Mei",
        "date_start": None,
        "date_end": None,
        "offset_days_from_cny": 15,
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "yee sang, mandarin oranges",
        "dine_in_boost": 0.08,
        "note": "15th day of Chinese New Year. Lantern Festival. Some restaurants extend CNY promos to Chap Goh Mei.",
    },
    {
        "name": "Cheng Beng (Qing Ming)",
        "date_start": None,
        "date_end": None,
        "month": 4,
        "approx_week": 1,
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "cold dishes, traditional chinese offerings",
        "dine_in_boost": 0.02,
        "note": "Tomb-sweeping day. Families gather for meals after visiting cemeteries.",
    },
    {
        "name": "Hungry Ghost Festival",
        "date_start": None,
        "date_end": None,
        "month": 8,
        "approx_week": 4,
        "duration_days": 30,
        "impact": "low",
        "cuisine_trend": "traditional chinese offerings, outdoor banquets",
        "dine_in_boost": -0.05,
        "note": "Seventh lunar month. Some Chinese consumers avoid dining out late at night.",
    },
    {
        "name": "Thaipusam",
        "date_start": None,
        "date_end": None,
        "month": 1,
        "approx_week": 4,
        "duration_days": 1,
        "impact": "low",
        "cuisine_trend": "indian vegetarian, banana leaf rice",
        "dine_in_boost": 0.05,
        "note": "Hindu festival. Vegetarian demand spikes. Batu Caves area sees massive crowds.",
    },
]

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def get_holidays_by_year(year: int) -> list[dict[str, Any]]:
    """Return the holiday list for the given year.

    Args:
        year: Calendar year (2026 or 2027 currently supported).

    Returns:
        List of holiday dicts for that year. Returns empty list if year
        is not yet defined.
    """
    _registry: dict[int, list[dict[str, Any]]] = {
        2026: MALAYSIA_HOLIDAYS_2026,
        2027: MALAYSIA_HOLIDAYS_2027,
    }
    return _registry.get(year, [])


def get_holiday_by_name(name: str, year: int) -> dict[str, Any] | None:
    """Find a specific holiday by name and year.

    Args:
        name: Holiday name (case-sensitive).
        year: Calendar year.

    Returns:
        Holiday dict or None if not found.
    """
    holidays = get_holidays_by_year(year)
    for h in holidays:
        if h["name"] == name:
            return h
    return None


def get_high_impact_periods(year: int) -> list[dict[str, Any]]:
    """Return only high-impact holidays for the given year.

    High-impact events are those with the most significant F&B sales
    effects — Hari Raya, CNY, Ramadan, Aidiladha.

    Args:
        year: Calendar year.

    Returns:
        List of high-impact holiday dicts.
    """
    return [h for h in get_holidays_by_year(year) if h["impact"] == "high"]


def get_state_specific_holidays(state: str, year: int) -> list[dict[str, Any]]:
    """Return holidays specific to a Malaysian state.

    Args:
        state: State name (e.g., "Penang", "Sabah", "Sarawak", "Johor").
        year: Calendar year.

    Returns:
        List of holiday dicts relevant to the given state.
    """
    state_map: dict[str, set[str]] = {
        "penang": {"George Town Heritage Day"},
        "sabah": {"Kaamatan (Harvest Festival)", "Good Friday"},
        "sarawak": {"Gawai Dayak", "Good Friday"},
        "johor": {"Hari Hol Johor"},
        "labuan": {"Good Friday"},
    }
    relevant_names = state_map.get(state.lower(), set())
    return [h for h in get_holidays_by_year(year) if h["name"] in relevant_names]
