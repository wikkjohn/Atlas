# Business calendars

Phase 26 (roadmap Milestone C, step 4). Each country's calendar now includes its
lunar-calendar holidays. The job scheduler and the simulation can follow a country's
business days.

## Dated holidays

Holidays of lunar and lunisolar calendars have no simple rule, so they come from tables
(`backend/app/modules/reference/dated.py`).
- **Festivals:** `FESTIVALS` gives the first day of 12 festivals for each year 2025–2030:
  Lunar New Year, Qingming, Dragon Boat, Mid-Autumn, Eid al-Fitr, Eid al-Adha, Islamic
  New Year, the Prophet's Birthday, Diwali, Vesak, Rosh Hashanah and Passover.
- **Country rules:** a holiday rule `{"name", "festival", "offset"}` takes the festival's
  date plus `offset` days. This covers several-day holidays ("Eid al-Fitr (day 2)"), eves
  ("Day of Arafah", Lunar New Year's Eve) and holidays fixed relative to a festival:
  - Yom Kippur is Rosh Hashanah + 9;
  - Shavuot is Passover + 50.
- **Coverage:** 50 countries gain 257 dated rules. These include the Gulf, North and West
  Africa, Israel, Turkey, China, Hong Kong, Korea, Singapore, Malaysia, Indonesia, Vietnam,
  India, Pakistan, Bangladesh and Sri Lanka.
- **Observance:** dated holidays follow the country's weekend observance like fixed-date
  ones. For example, Singapore's Vesak Day on Sunday 31 May 2026 is observed on Monday
  1 June.
- **Year boundaries:** an eve that falls in the previous Gregorian year counts in that
  year. Vietnam's Tết eve of 2028 is 25 January 2028.

Outside 2025–2030 these holidays are not computed, and each affected country's notes say
so. The tables give dates as published or widely expected. An Islamic holiday can move by
a day when the moon is sighted.

Reference data version `2026.2` carries the dated rules. Migration 0023 loads them from a
frozen snapshot (`0023_reference_data.json`), and `python -m app.cli reference load`
applies them to an existing database. In Saudi Arabia, 2026 now has 254 business days
(259 before Eid was dated).

Still not modelled:
- state and provincial holidays;
- bridge days;
- working weekends that make up for holidays (China, Vietnam, Korea).

## Schedules on business days

A job schedule can name a business calendar: a country code (`job_schedules.business_calendar`).
- **Due on a weekend or holiday:** if the schedule falls due on a weekend or public holiday
  of that country (in the country's local time), the scheduler queues no job. It moves the
  next run forward a day at a time to the first business day, at the same time of day.
- **After a run:** the next run is the interval later, moved the same way.
- **Example:** a daily UK schedule due on Christmas Day 2026, a Friday, next runs on
  Tuesday 29 December. Boxing Day falls on Saturday 26 December and is observed on Monday
  28 December.
- **Default:** a schedule without a calendar runs every day, as before.

Set or clear a calendar with `PATCH /api/v1/job-schedules/{name}`, using
`{"business_calendar": "GB"}` to set it or `""` to clear it. The country must exist, and the
change is audited. On System Settings → Background jobs, administrators choose the calendar
in the *Business days* column.

## Simulation arrivals

A scenario can set `business_calendar` in its configuration.
- **Arrivals:** a case that would arrive on a weekend or holiday of that country arrives on
  the next business day, at the same local time.
- **Reproducible:** the calendar comes from the reference data in code, not the database,
  so a run reproduces even after operators edit country data.
- **Hashes:** scenarios without the field keep their configuration hash.

The new scenario `payments-easter` (v1) shows the effect.
- **What runs:** domestic payments over the UK Easter weekend of 2026, using WF-0002 v1.
- **When:** the arrival window is 96 hours from Thursday 2 April, 08:00 UTC.
- **Mix:** the same kinds of cases as `domestic-payments`.
- **Result:** everything that would arrive from Good Friday to Easter Monday queues up for
  Tuesday 7 April.

## Limitations

- Dated holidays cover 2025–2030 only.
- Scheduler calendars move whole days. A schedule that runs several times a day skips the
  whole non-business day.
- Only arrivals follow the calendar in the simulation. Simulated staff still work every day.
