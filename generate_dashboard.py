"""
Builds a self-contained, offline dashboard.html from garmin/data.json.

Read-only: only reads the local JSON file already produced by sync_garmin.py.
Makes no network calls and never touches your Garmin account.

Usage:
    venv\\Scripts\\python.exe generate_dashboard.py
"""

import json
import os
import statistics
from datetime import date, datetime, timedelta

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_JSON = os.path.join(PROJECT_DIR, "garmin", "data.json")
OUTPUT_HTML = os.path.join(PROJECT_DIR, "dashboard.html")


def safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, list):
            if isinstance(k, int) and -len(cur) <= k < len(cur):
                cur = cur[k]
            else:
                return default
        else:
            return default
        if cur is None:
            return default
    return cur


def m_to_km(m):
    return round(m / 1000, 2) if isinstance(m, (int, float)) else None


# ---------------------------------------------------------------- extraction

def extract_daily(wellness_by_day):
    days = []
    for day_str in sorted(wellness_by_day.keys()):
        d = wellness_by_day[day_str] or {}
        sleep = d.get("sleep") or {}
        hrv = d.get("hrv") or {}
        rhr = d.get("rhr") or {}
        body_battery = d.get("body_battery") or []
        stress = d.get("stress") or {}
        steps = d.get("steps") or []
        readiness = d.get("training_readiness") or []

        sleep_seconds = safe_get(sleep, "dailySleepDTO", "sleepTimeSeconds")
        sleep_score = safe_get(sleep, "dailySleepDTO", "sleepScores", "overall", "value")

        hrv_avg = safe_get(hrv, "hrvSummary", "lastNightAvg")
        hrv_status = safe_get(hrv, "hrvSummary", "status")

        rhr_value = rhr.get("restingHeartRate") if isinstance(rhr, dict) else None
        if not rhr_value:
            rhr_value = safe_get(
                rhr, "allMetrics", "metricsMap", "WELLNESS_RESTING_HEART_RATE", 0, "value"
            )

        bb_high = bb_low = None
        if isinstance(body_battery, list) and body_battery:
            values = body_battery[0].get("bodyBatteryValuesArray") or []
            levels = [
                v[1] for v in values
                if isinstance(v, list) and len(v) > 1 and isinstance(v[1], (int, float))
            ]
            if levels:
                bb_high, bb_low = max(levels), min(levels)

        avg_stress = stress.get("avgStressLevel") if isinstance(stress, dict) else None
        if not (isinstance(avg_stress, (int, float)) and avg_stress >= 0):
            avg_stress = None

        total_steps = None
        if isinstance(steps, list) and steps:
            total_steps = sum(s.get("steps", 0) or 0 for s in steps if isinstance(s, dict))

        readiness_score = readiness_level = None
        if isinstance(readiness, list) and readiness:
            readiness_score = readiness[0].get("score")
            readiness_level = readiness[0].get("level")
        elif isinstance(readiness, dict):
            readiness_score = readiness.get("score")
            readiness_level = readiness.get("level")

        max_metrics = d.get("max_metrics") or []
        vo2max_running = safe_get(max_metrics, 0, "generic", "vo2MaxValue")
        vo2max_cycling = safe_get(max_metrics, 0, "cycling", "vo2MaxValue")

        days.append({
            "date": day_str,
            "sleep_score": sleep_score,
            "sleep_min": round(sleep_seconds / 60) if isinstance(sleep_seconds, (int, float)) else None,
            "hrv": hrv_avg,
            "hrv_status": hrv_status,
            "rhr": rhr_value,
            "bb_low": bb_low,
            "bb_high": bb_high,
            "stress": avg_stress,
            "steps": total_steps,
            "readiness": readiness_score,
            "readiness_level": readiness_level,
            "vo2max_running": vo2max_running,
            "vo2max_cycling": vo2max_cycling,
            "ftp": None,
        })

    _forward_fill(days, "vo2max_running")
    _forward_fill(days, "vo2max_cycling")
    return days


def _forward_fill(days, key):
    last = None
    for d in days:
        if isinstance(d.get(key), (int, float)):
            last = d[key]
        elif last is not None:
            d[key] = last


def merge_ftp_history(days, ftp_history):
    if not ftp_history or not days:
        return
    history = sorted(ftp_history, key=lambda h: h["date"])
    idx = 0
    last = None
    for d in days:
        while idx < len(history) and history[idx]["date"] <= d["date"]:
            last = history[idx]["ftp"]
            idx += 1
        if last is not None:
            d["ftp"] = last


CYCLING_TYPES = {"road_biking", "cycling", "indoor_cycling", "virtual_ride", "mountain_biking", "gravel_cycling"}
STRENGTH_TYPES = {"strength_training", "hiit", "indoor_cardio"}
RUNNING_TYPES = {"running", "treadmill_running", "trail_running"}


def extract_activities(activities_raw, exercise_sets_raw=None):
    exercise_sets_raw = exercise_sets_raw or {}
    out = []
    for a in activities_raw:
        start = a.get("startTimeLocal", "")
        day = start.split(" ")[0] if start else None
        if not day:
            continue
        distance_km = m_to_km(a.get("distance"))
        duration_sec = a.get("duration")
        duration_min = round(duration_sec / 60, 1) if isinstance(duration_sec, (int, float)) else None
        activity_type = safe_get(a, "activityType", "typeKey", default="activity")
        out.append({
            "id": a.get("activityId"),
            "date": day,
            "name": a.get("activityName") or "Workout",
            "type": activity_type,
            "distance_km": distance_km,
            "duration_min": duration_min,
            "calories": a.get("calories"),
            "avg_hr": a.get("averageHR"),
            "max_hr": a.get("maxHR"),
            "avg_power": a.get("avgPower"),
            "normalized_power": a.get("normPower"),
            "aerobic_effect": a.get("aerobicTrainingEffect"),
            "anaerobic_effect": a.get("anaerobicTrainingEffect"),
            "muscle_groups": exercise_sets_raw.get(str(a.get("activityId"))) or {},
        })
    out.sort(key=lambda a: a["date"], reverse=True)
    return out


def compute_muscle_balance(activities, days=14):
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    tally = {}
    for a in activities:
        if a["date"] < cutoff:
            continue
        for group, count in (a.get("muscle_groups") or {}).items():
            tally[group] = tally.get(group, 0) + count
    return dict(sorted(tally.items(), key=lambda kv: -kv[1]))


def compute_weekly_volume(activities):
    weeks = {}
    for a in activities:
        try:
            d = datetime.strptime(a["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        iso_year, iso_week, _ = d.isocalendar()
        monday = d - timedelta(days=d.weekday())
        key = monday.isoformat()
        w = weeks.setdefault(key, {"week_start": key, "km": 0.0, "minutes": 0.0, "count": 0})
        w["km"] += a["distance_km"] or 0
        w["minutes"] += a["duration_min"] or 0
        w["count"] += 1
    result = sorted(weeks.values(), key=lambda w: w["week_start"])
    for w in result:
        w["km"] = round(w["km"], 1)
        w["minutes"] = round(w["minutes"], 0)
    return result


# ------------------------------------------------------------------ insights

def _avg(values):
    vals = [v for v in values if isinstance(v, (int, float))]
    return round(statistics.mean(vals), 1) if vals else None


ROUTINE = {
    0: ("functional", "Functional training"),
    1: ("cycling_flat", "Club ride — flat"),
    2: ("functional", "Functional training"),
    3: ("cycling_hilly", "Club ride — hilly"),
    4: ("functional", "Functional training"),
    5: ("cycling_long", "Club ride — long"),
    6: ("rest", "Rest / free day"),
}


def compute_tomorrow_focus(daily, activities):
    if not daily:
        return {"headline": "Not enough data yet", "body": ["Check back after a few days of syncing."]}

    latest = daily[-1]
    tomorrow = date.today() + timedelta(days=1)
    kind, label = ROUTINE[tomorrow.weekday()]

    readiness_score = latest.get("readiness")
    readiness_level = (latest.get("readiness_level") or "").upper()
    hrv = latest.get("hrv")
    sleep_score = latest.get("sleep_score")

    if readiness_level == "HIGH" or (readiness_score is not None and readiness_score >= 70):
        state = "high"
    elif readiness_level in ("LOW", "POOR") or (readiness_score is not None and readiness_score < 40):
        state = "low"
    else:
        state = "moderate"

    stats_bits = []
    if sleep_score is not None:
        stats_bits.append(f"sleep score {sleep_score}")
    if hrv is not None:
        stats_bits.append(f"HRV {hrv} ms")
    if readiness_score is not None:
        lvl = f" ({readiness_level})" if readiness_level else ""
        stats_bits.append(f"readiness {readiness_score}{lvl}")
    stats_str = ", ".join(stats_bits) if stats_bits else "no recovery data yet for last night"

    body = [f"Last night: {stats_str}."]

    if kind == "cycling_flat":
        if state == "high":
            body.append("Recovery looks strong — good day for the harder peloton and sustained threshold power on the flats.")
        elif state == "low":
            body.append("Recovery is low tonight — take the easier peloton and treat tomorrow as aerobic/endurance riding, not a pace day.")
        else:
            body.append("Recovery is middling — ride with whichever peloton feels comfortable, but stop short of an all-out effort.")
    elif kind == "cycling_hilly":
        if state == "high":
            body.append("Prime terrain for building FTP — consider the harder peloton and push seated/standing efforts on the climbs.")
        elif state == "low":
            body.append("Take the easier peloton and treat the hills as tempo work rather than max effort — let the legs recover.")
        else:
            body.append("Moderate recovery — pick your peloton by feel, and treat 1-2 climbs as quality efforts rather than the whole ride.")
    elif kind == "cycling_long":
        if state == "low":
            body.append("Recovery is low going into the long ride — prioritize pacing and fueling early, don't chase the front group the whole way.")
        else:
            body.append("Good position for the long ride — steady aerobic pacing, and a good day to practice fueling/hydration for longer efforts.")
    elif kind == "functional":
        balance = compute_muscle_balance(activities, days=10)
        if balance:
            least = min(balance, key=balance.get)
            body.append(f"Muscle balance over the last 10 days shows {least} getting the least attention — worth prioritizing it tomorrow if recovery allows.")
        if state == "low":
            body.append("Recovery is low — keep it lighter: mobility, core, and technique work over heavy loading.")
        else:
            body.append("Recovery supports a normal-intensity session.")
    elif kind == "rest":
        recent_km = sum(
            a["distance_km"] or 0 for a in activities
            if a["date"] >= (date.today() - timedelta(days=6)).isoformat()
        )
        if recent_km > 0:
            body.append(
                f"You've covered about {round(recent_km, 1)} km this week already — a full rest or an easy "
                "spin both work, let how you feel guide it."
            )
        else:
            body.append("Good chance to fully recover, or get outside for something light and low-stress.")

    return {"headline": f"Tomorrow: {label}", "body": body}


def compute_insights(daily, activities):
    insights = []
    if len(daily) < 8:
        return ["Not enough history yet for trend insights — check back after a few more days of syncing."]

    last7 = daily[-7:]
    prev7 = daily[-14:-7] if len(daily) >= 14 else []

    def trend_line(label, key, unit, higher_is_good, fmt="{:.1f}"):
        cur = _avg([d[key] for d in last7])
        prior = _avg([d[key] for d in prev7]) if prev7 else None
        if cur is None:
            return None
        if prior is None or prior == 0:
            return f"{label}: 7-day average is {fmt.format(cur)} {unit}."
        delta = cur - prior
        pct = abs(delta) / abs(prior) * 100 if prior else 0
        if pct < 4:
            return f"{label} is steady: {fmt.format(cur)} {unit} (7-day avg), about the same as the week before."
        direction = "up" if delta > 0 else "down"
        good = (delta > 0) == higher_is_good
        judgement = "a good sign" if good else "worth keeping an eye on"
        return (
            f"{label} is {direction} {fmt.format(abs(delta))} {unit} vs the prior week "
            f"({fmt.format(cur)} {unit} now) — {judgement}."
        )

    for line in [
        trend_line("HRV", "hrv", "ms", True),
        trend_line("Resting heart rate", "rhr", "bpm", False),
        trend_line("Sleep score", "sleep_score", "pts", True),
        trend_line("Training readiness", "readiness", "pts", True),
        trend_line("Average stress", "stress", "", False),
    ]:
        if line:
            insights.append(line)

    hrv_cur, hrv_prior = _avg([d["hrv"] for d in last7]), _avg([d["hrv"] for d in prev7]) if prev7 else None
    rhr_cur, rhr_prior = _avg([d["rhr"] for d in last7]), _avg([d["rhr"] for d in prev7]) if prev7 else None
    if hrv_cur is not None and hrv_prior and rhr_cur is not None and rhr_prior:
        if hrv_cur < hrv_prior * 0.96 and rhr_cur > rhr_prior * 1.02:
            insights.append(
                "HRV is down and resting heart rate is up at the same time this week — "
                "a classic early sign of fatigue or under-recovery. Consider an easier few days."
            )

    week_ago = date.today() - timedelta(days=7)
    two_weeks_ago = date.today() - timedelta(days=14)
    recent_acts = [a for a in activities if a["date"] >= week_ago.isoformat()]
    prior_acts = [a for a in activities if two_weeks_ago.isoformat() <= a["date"] < week_ago.isoformat()]
    recent_km = round(sum(a["distance_km"] or 0 for a in recent_acts), 1)
    prior_km = round(sum(a["distance_km"] or 0 for a in prior_acts), 1)
    if recent_acts or prior_acts:
        insights.append(
            f"You logged {len(recent_acts)} workout(s) covering {recent_km} km in the last 7 days, "
            f"vs {len(prior_acts)} workout(s) / {prior_km} km the week before."
        )

    return insights[:6]


def compute_suggestions(daily, activities, weekly, ftp_history=None):
    suggestions = []
    if len(daily) < 8:
        return suggestions

    last7 = daily[-7:]
    prev7 = daily[-14:-7] if len(daily) >= 14 else []
    today_d = date.today()

    hrv_cur, hrv_prior = _avg([d["hrv"] for d in last7]), (_avg([d["hrv"] for d in prev7]) if prev7 else None)
    rhr_cur, rhr_prior = _avg([d["rhr"] for d in last7]), (_avg([d["rhr"] for d in prev7]) if prev7 else None)
    if hrv_cur is not None and hrv_prior and rhr_cur is not None and rhr_prior:
        if hrv_cur < hrv_prior * 0.96 and rhr_cur > rhr_prior * 1.02:
            suggestions.append(
                "Your body is flashing early fatigue signs (HRV down and resting heart rate up together). "
                "Swap your next hard session for an easy day or full rest, and reassess in 2-3 days."
            )

    low_days = sum(1 for d in last7 if (d.get("readiness_level") or "").upper() in ("LOW", "POOR"))
    if low_days >= 3:
        suggestions.append(
            f"Training readiness was LOW on {low_days} of the last 7 days. Prioritize sleep and dial back "
            "intensity until it's consistently back to MODERATE or HIGH."
        )

    sleep_cur = _avg([d["sleep_score"] for d in last7])
    if sleep_cur is not None and sleep_cur < 70:
        suggestions.append(
            f"Average sleep score this week is {sleep_cur} (below the ~70-80 'good' band). Protecting even 30 "
            "extra minutes of bedtime tends to move HRV and next-day readiness noticeably."
        )

    def km_in_window(start_days_ago, end_days_ago):
        start = (today_d - timedelta(days=start_days_ago)).isoformat()
        end = (today_d - timedelta(days=end_days_ago)).isoformat()
        return sum(a["distance_km"] or 0 for a in activities if end <= a["date"] <= start)

    recent_km = km_in_window(6, 0)
    baseline_km = km_in_window(27, 7) / 3 if len(daily) >= 28 else None
    if baseline_km and baseline_km > 0.5 and recent_km > baseline_km * 1.3:
        pct = round((recent_km / baseline_km - 1) * 100)
        suggestions.append(
            f"This week's distance ({round(recent_km, 1)} km) is {pct}% above your recent 3-week average "
            f"({round(baseline_km, 1)} km) — a common trigger for overuse injury. Consider easing back next "
            "week (the classic no-more-than +10%/week guidance)."
        )

    days_with_activity = {a["date"] for a in activities if a["date"] >= (today_d - timedelta(days=6)).isoformat()}
    if len(days_with_activity) >= 7:
        suggestions.append(
            "You've trained every day for the last 7 days with no rest day. Recovery adaptations happen on "
            "rest days — schedule at least one this coming week."
        )

    stress_cur = _avg([d["stress"] for d in last7])
    if stress_cur is not None and stress_cur > 40:
        suggestions.append(
            f"Average daily stress this week is {stress_cur}, on the high side. Body battery and HRV tend to "
            "follow stress down a day or two later — short walks or a few minutes of breathing work on your "
            "highest-stress days can help."
        )

    def stagnant(vals, tolerance):
        if len(vals) < 10:
            return None
        first_half = _avg(vals[:len(vals) // 2])
        second_half = _avg(vals[len(vals) // 2:])
        if first_half is None or second_half is None:
            return None
        return second_half <= first_half + tolerance

    window60 = daily[-60:] if len(daily) >= 60 else daily

    ftp_history = ftp_history or []
    if len(ftp_history) >= 2:
        latest_ftp, prior_ftp = ftp_history[-1]["ftp"], ftp_history[-2]["ftp"]
        if latest_ftp <= prior_ftp:
            suggestions.append(
                f"Cycling FTP hasn't moved (currently {latest_ftp}W). Since Thursday's hilly ride is your best "
                "structured-effort terrain, try 2-3 sustained 8-12min threshold efforts on the climbs — the "
                "single biggest lever for raising FTP, more than extra easy volume."
            )

    vo2_cycle_vals = [d["vo2max_cycling"] for d in window60 if isinstance(d.get("vo2max_cycling"), (int, float))]
    if stagnant(vo2_cycle_vals, 0.3):
        suggestions.append(
            "Estimated cycling VO2 max has been flat despite consistent riding. Short, hard efforts — "
            "4-5min at a very hard pace with equal recovery, worked into a club ride or on your own — tend to "
            "move this more than additional steady-state volume."
        )

    balance = compute_muscle_balance(activities, days=14)
    if balance and len(balance) >= 2:
        max_group, max_count = max(balance.items(), key=lambda kv: kv[1])
        min_group, min_count = min(balance.items(), key=lambda kv: kv[1])
        if max_count >= 3 and min_count <= max_count * 0.3:
            suggestions.append(
                f"Over the last 14 days of functional training, {max_group.lower()} work has dominated and "
                f"{min_group.lower()} has gotten comparatively little attention. Worth rebalancing your next "
                "session or two toward it."
            )

    vo2_run_vals = [d["vo2max_running"] for d in window60 if isinstance(d.get("vo2max_running"), (int, float))]
    if stagnant(vo2_run_vals, 0.3):
        suggestions.append(
            "Estimated running VO2 max has been flat over the recent stretch. Since running is a side interest "
            "for you, this is only worth acting on if you want to — a few strides or a tempo effort now and "
            "then would nudge it."
        )

    return suggestions[:6]


# --------------------------------------------------------------------- HTML

def render_html(daily, activities, weekly, insights, suggestions, tomorrow_focus, generated_at):
    data_blob = json.dumps({
        "daily": daily,
        "activities": activities[:60],
        "weekly": weekly,
    })
    insights_html = "\n".join(f"<li>{i}</li>" for i in insights)
    suggestions_html = "\n".join(f"<li>{s}</li>" for s in suggestions)
    latest = daily[-1] if daily else {}

    focus_body_html = "\n".join(f"<p>{line}</p>" for line in tomorrow_focus["body"])

    balance = compute_muscle_balance(activities, days=14)
    if balance:
        max_count = max(balance.values())
        chips = []
        for group, count in balance.items():
            pct = round(count / max_count * 100)
            chips.append(
                f'<div class="chip"><span>{group}</span>'
                f'<div class="chip-bar"><div class="chip-fill" style="width:{pct}%"></div></div>'
                f'<span class="chip-count">{count}</span></div>'
            )
        balance_html = "\n".join(chips)
    else:
        balance_html = "<p class=\"cap\">No functional training sessions with detected exercises in the last 14 days.</p>"

    functional_sessions = [a for a in activities if a.get("muscle_groups")][:8]
    if functional_sessions:
        rows = []
        for a in functional_sessions:
            groups_str = ", ".join(f"{g} ({c})" for g, c in sorted(a["muscle_groups"].items(), key=lambda kv: -kv[1]))
            effect = a.get("aerobic_effect")
            effect_str = f"{round(effect, 1)}" if isinstance(effect, (int, float)) else "—"
            rows.append(
                f"<tr><td>{a['date']}</td><td>{a['name']}</td>"
                f"<td class=\"num\">{a['duration_min'] or '—'} min</td>"
                f"<td class=\"num\">{effect_str}</td><td>{groups_str or 'Not detected'}</td></tr>"
            )
        functional_table_html = "\n".join(rows)
    else:
        functional_table_html = '<tr><td colspan="5" class="cap">No functional training sessions found yet.</td></tr>'

    html = HTML_TEMPLATE
    html = html.replace("__GENERATED_AT__", generated_at)
    html = html.replace("__INSIGHTS_LIST__", insights_html or "<li>No insights yet.</li>")
    html = html.replace(
        "__SUGGESTIONS_LIST__",
        suggestions_html or "<li>Nothing stands out right now — keep up the current routine.</li>",
    )
    html = html.replace("__FOCUS_HEADLINE__", tomorrow_focus["headline"])
    html = html.replace("__FOCUS_BODY__", focus_body_html)
    html = html.replace("__MUSCLE_BALANCE__", balance_html)
    html = html.replace("__FUNCTIONAL_TABLE__", functional_table_html)
    html = html.replace("__DATA_JSON__", data_blob)
    html = html.replace("__LATEST_DATE__", latest.get("date", "—"))
    return html


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Garmin Recovery &amp; Training Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  .viz-root {
    color-scheme: light;
    --surface-1:      #fcfcfb;
    --page-plane:     #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --text-muted:     #898781;
    --gridline:       #e1e0d9;
    --baseline:       #c3c2b7;
    --border:         rgba(11,11,11,0.10);
    --series-1:       #2a78d6;
    --series-1-wash:  rgba(42,120,214,0.10);
    --series-1-light: #86b6ef;
    --good-text:      #006300;
    --status-good:    #0ca30c;
    --status-warning: #fab219;
    --status-serious: #ec835a;
    --status-critical:#d03b3b;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: dark;
      --surface-1:      #1a1a19;
      --page-plane:     #0d0d0d;
      --text-primary:   #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted:     #898781;
      --gridline:       #2c2c2a;
      --baseline:       #383835;
      --border:         rgba(255,255,255,0.10);
      --series-1:       #3987e5;
      --series-1-wash:  rgba(57,135,229,0.14);
      --series-1-light: #184f95;
      --good-text:      #0ca30c;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page-plane:     #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted:     #898781;
    --gridline:       #2c2c2a;
    --baseline:       #383835;
    --border:         rgba(255,255,255,0.10);
    --series-1:       #3987e5;
    --series-1-wash:  rgba(57,135,229,0.14);
    --series-1-light: #184f95;
    --good-text:      #0ca30c;
  }

  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page-plane);
    color: var(--text-primary);
  }
  .wrap { max-width: 1100px; margin: 0 auto; padding: 24px 20px 64px; }

  header.top { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 4px; }
  h1 { font-size: 22px; margin: 0; }
  .subtitle { color: var(--text-secondary); font-size: 13px; margin: 4px 0 20px; }
  button.theme-toggle {
    font: inherit; font-size: 12px; padding: 6px 10px; border-radius: 8px;
    border: 1px solid var(--border); background: var(--surface-1); color: var(--text-secondary); cursor: pointer;
  }

  .card {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 18px;
  }

  .focus-card {
    background: var(--surface-1); border: 1px solid var(--border); border-left: 4px solid var(--series-1);
    border-radius: 12px; padding: 18px 20px; margin-bottom: 20px;
  }
  .focus-card h2 { font-size: 12px; margin: 0 0 8px; color: var(--text-secondary); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
  .focus-card .headline { font-size: 20px; font-weight: 600; margin: 0 0 8px; }
  .focus-card p { margin: 4px 0; font-size: 14px; line-height: 1.5; color: var(--text-primary); }

  .section-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: .04em; margin: 28px 0 10px; }
  .section-title:first-of-type { margin-top: 0; }
  .section-sub { font-size: 12px; color: var(--text-muted); margin: -6px 0 12px; }

  .side-quest { opacity: 0.88; }
  .side-quest .kpi-grid, .side-quest .chart-grid { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }

  .chip { display: flex; align-items: center; gap: 8px; margin: 8px 0; font-size: 13px; }
  .chip span:first-child { min-width: 110px; color: var(--text-secondary); }
  .chip-bar { flex: 1; height: 8px; background: var(--gridline); border-radius: 999px; overflow: hidden; }
  .chip-fill { height: 100%; background: var(--series-1); border-radius: 999px; }
  .chip-count { min-width: 20px; text-align: right; font-variant-numeric: tabular-nums; color: var(--text-muted); }

  .panel-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; margin-bottom: 20px; }
  .insights.card { margin-bottom: 0; }
  .insights h2 { font-size: 14px; margin: 0 0 10px; color: var(--text-secondary); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
  .insights ul { margin: 0; padding-left: 18px; }
  .insights li { margin: 6px 0; font-size: 14px; line-height: 1.5; }
  .insights.suggestions { border-left: 3px solid var(--series-1); }

  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 24px; }
  .kpi .label { font-size: 12px; color: var(--text-secondary); }
  .kpi .value { font-size: 26px; font-weight: 600; margin: 4px 0 2px; }
  .kpi .unit { font-size: 13px; color: var(--text-muted); font-weight: 400; }
  .kpi .delta { font-size: 12px; font-weight: 600; }
  .kpi .delta.good { color: var(--good-text); }
  .kpi .delta.bad { color: var(--status-critical); }
  .kpi .delta.flat { color: var(--text-muted); }
  .kpi .badge { display: inline-block; font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 999px; margin-top: 6px; }
  .kpi svg.spark { display: block; margin-top: 8px; }

  .filters { display: flex; gap: 6px; margin: 4px 0 18px; flex-wrap: wrap; }
  .filters button {
    font: inherit; font-size: 12px; padding: 6px 12px; border-radius: 999px;
    border: 1px solid var(--border); background: var(--surface-1); color: var(--text-secondary); cursor: pointer;
  }
  .filters button.active { background: var(--series-1); color: #fff; border-color: var(--series-1); }

  .chart-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 16px; margin-bottom: 20px; }
  .chart-card h3 { font-size: 14px; margin: 0 0 2px; }
  .chart-card .cap { font-size: 12px; color: var(--text-muted); margin: 0 0 8px; }
  .chart-card .head-row { display:flex; justify-content: space-between; align-items:flex-start; }
  .table-toggle { font: inherit; font-size: 11px; color: var(--text-secondary); background: none; border: 1px solid var(--border); border-radius: 6px; padding: 3px 8px; cursor: pointer; }

  svg.chart { width: 100%; height: auto; overflow: visible; }
  .gridline { stroke: var(--gridline); stroke-width: 1; }
  .baseline { stroke: var(--baseline); stroke-width: 1; }
  .line-path { fill: none; stroke: var(--series-1); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
  .area-path { fill: var(--series-1-wash); stroke: none; }
  .end-dot { fill: var(--series-1); stroke: var(--surface-1); stroke-width: 2; }
  .axis-label { fill: var(--text-muted); font-size: 10px; }
  .crosshair { stroke: var(--baseline); stroke-width: 1; }
  .bar { fill: var(--series-1); }
  .hit { fill: transparent; }

  .tooltip {
    position: absolute; pointer-events: none; background: var(--text-primary); color: var(--surface-1);
    font-size: 12px; padding: 6px 9px; border-radius: 6px; transform: translate(-50%, -110%);
    white-space: nowrap; opacity: 0; transition: opacity .08s; z-index: 5;
  }
  .tooltip .v { font-weight: 700; }
  .chart-wrap { position: relative; }

  table.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  table.data-table th, table.data-table td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--gridline); }
  table.data-table th { color: var(--text-secondary); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .03em; }
  table.data-table td.num { font-variant-numeric: tabular-nums; text-align: right; }
  .table-view { display: none; max-height: 260px; overflow: auto; }
  .table-view.shown { display: block; }
  .chart-view.hidden { display: none; }

  .activities-card { margin-top: 4px; }
  .activities-wrap { max-height: 420px; overflow: auto; }

  footer.note { color: var(--text-muted); font-size: 12px; margin-top: 28px; }
</style>
</head>
<body>
<div class="viz-root">
<div class="wrap">

  <header class="top">
    <h1>Garmin Recovery &amp; Training</h1>
    <button class="theme-toggle" id="themeToggle" type="button">Toggle theme</button>
  </header>
  <p class="subtitle">Latest day: __LATEST_DATE__ · Generated __GENERATED_AT__ · Read-only, generated from Garmin data</p>

  <section class="focus-card">
    <h2>Focus</h2>
    <p class="headline">__FOCUS_HEADLINE__</p>
    __FOCUS_BODY__
  </section>

  <div class="panel-grid">
    <section class="insights card">
      <h2>Insights</h2>
      <ul>__INSIGHTS_LIST__</ul>
    </section>
    <section class="insights suggestions card">
      <h2>Suggestions</h2>
      <ul>__SUGGESTIONS_LIST__</ul>
    </section>
  </div>

  <p class="section-title">Recovery — right now</p>
  <div class="kpi-grid" id="kpiGridRecovery"></div>

  <p class="section-title">Cycling performance</p>
  <p class="section-sub">Your main focus — VO2 max and FTP, so you can hold more power for longer.</p>
  <div class="kpi-grid" id="kpiGridCycling"></div>

  <p class="section-title">Functional training</p>
  <p class="section-sub">Muscle groups worked over the last 14 days (Garmin's auto-detection is approximate).</p>
  <section class="card" style="margin-bottom: 16px;">
    __MUSCLE_BALANCE__
  </section>
  <section class="card activities-card" style="margin-bottom: 4px;">
    <div class="activities-wrap" style="max-height: 260px;">
      <table class="data-table">
        <thead>
          <tr><th>Date</th><th>Name</th><th class="num">Duration</th><th class="num">Training effect</th><th>Muscle groups (detected sets)</th></tr>
        </thead>
        <tbody>__FUNCTIONAL_TABLE__</tbody>
      </table>
    </div>
  </section>

  <div class="filters" id="filters">
    <button data-days="7">7d</button>
    <button data-days="30">30d</button>
    <button data-days="90">90d</button>
    <button data-days="365" class="active">1y</button>
    <button data-days="all">All</button>
  </div>

  <p class="section-title">Recovery trends</p>
  <div class="chart-grid" id="chartGridRecovery"></div>

  <p class="section-title">Cycling trends</p>
  <div class="chart-grid" id="chartGridCycling"></div>

  <p class="section-title">Weekly training volume</p>
  <div class="chart-grid" id="chartGridVolume"></div>

  <section class="side-quest">
    <p class="section-title">Running (side quest)</p>
    <p class="section-sub">Occasional — not a priority, but nice to track progress.</p>
    <div class="kpi-grid" id="kpiGridRunning"></div>
    <div class="chart-grid" id="chartGridRunning"></div>
  </section>

  <p class="section-title">Recent workouts</p>
  <section class="card activities-card">
    <div class="activities-wrap">
      <table class="data-table" id="activitiesTable">
        <thead>
          <tr><th>Date</th><th>Name</th><th>Type</th><th class="num">Distance</th><th class="num">Duration</th><th class="num">Avg HR</th><th class="num">Calories</th></tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <footer class="note">Built locally from garmin/data.json, updated automatically each evening, and published to an unlisted GitHub Pages URL not indexed by search engines. Never shared beyond that link.</footer>
</div>
</div>

<script>
const DATA = __DATA_JSON__;

// ---------- theme toggle ----------
(function() {
  const btn = document.getElementById('themeToggle');
  const saved = localStorage.getItem('garmin-dashboard-theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
  btn.addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const next = (cur === 'dark' || (!cur && prefersDark)) ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('garmin-dashboard-theme', next);
  });
})();

// ---------- helpers ----------
function fmt1(n) { return (n === null || n === undefined) ? '—' : (Math.round(n * 10) / 10).toString(); }
function avg(arr) {
  const v = arr.filter(x => typeof x === 'number');
  if (!v.length) return null;
  return v.reduce((a,b)=>a+b,0) / v.length;
}
function lastN(arr, n) { return arr.slice(Math.max(0, arr.length - n)); }
function textContentSet(el, text) { el.textContent = text; }

function niceTicks(min, max, count) {
  if (min === max) { min -= 1; max += 1; }
  const range = max - min;
  const rawStep = range / count;
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const steps = [1, 2, 5, 10];
  let step = steps[0] * mag;
  for (const s of steps) { if (s * mag >= rawStep) { step = s * mag; break; } }
  const niceMin = Math.floor(min / step) * step;
  const niceMax = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = niceMin; v <= niceMax + 1e-9; v += step) ticks.push(Math.round(v * 100) / 100);
  return ticks;
}

// ---------- KPI tiles ----------
const KPI_RECOVERY = [
  { key: 'sleep_score', label: 'Sleep score', unit: 'pts', higherGood: true, badge: null },
  { key: 'hrv', label: 'HRV', unit: 'ms', higherGood: true, badge: 'hrv_status' },
  { key: 'rhr', label: 'Resting HR', unit: 'bpm', higherGood: false, badge: null },
  { key: 'bb_high', label: 'Body battery (peak)', unit: '', higherGood: true, badge: null },
  { key: 'stress', label: 'Avg stress', unit: '', higherGood: false, badge: null },
  { key: 'readiness', label: 'Training readiness', unit: 'pts', higherGood: true, badge: 'readiness_level' },
];
const KPI_CYCLING = [
  { key: 'vo2max_cycling', label: 'VO2 max (cycling)', unit: '', higherGood: true, badge: null },
  { key: 'ftp', label: 'FTP', unit: 'W', higherGood: true, badge: null },
];
const KPI_RUNNING = [
  { key: 'vo2max_running', label: 'VO2 max (running)', unit: '', higherGood: true, badge: null },
];

function buildSparkline(values) {
  const w = 120, h = 28, pad = 3;
  const vals = values.filter(v => typeof v === 'number');
  if (vals.length < 2) return '';
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = (max - min) || 1;
  const step = (w - pad*2) / (values.length - 1);
  let d = '';
  values.forEach((v, i) => {
    if (typeof v !== 'number') return;
    const x = pad + i*step;
    const y = h - pad - ((v - min) / span) * (h - pad*2);
    d += (d ? 'L' : 'M') + x.toFixed(1) + ',' + y.toFixed(1);
  });
  const lastVal = vals[vals.length - 1];
  const lastIdx = values.length - 1 - [...values].reverse().findIndex(v => typeof v === 'number');
  const lx = pad + lastIdx*step;
  const ly = h - pad - ((lastVal - min) / span) * (h - pad*2);
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    <path d="${d}" fill="none" stroke="var(--text-muted)" stroke-width="1.5"/>
    <circle cx="${lx}" cy="${ly}" r="3" fill="var(--series-1)"/>
  </svg>`;
}

function renderKPIGroup(defs, gridId) {
  const grid = document.getElementById(gridId);
  grid.innerHTML = '';
  const daily = DATA.daily;
  const last7 = lastN(daily, 7);
  const prev7 = daily.slice(Math.max(0, daily.length - 14), Math.max(0, daily.length - 7));
  const latest = daily[daily.length - 1] || {};

  defs.forEach(def => {
    const curAvg = avg(last7.map(d => d[def.key]));
    const priorAvg = avg(prev7.map(d => d[def.key]));
    const latestVal = latest[def.key];
    const div = document.createElement('div');
    div.className = 'card kpi';

    const label = document.createElement('div');
    label.className = 'label';
    textContentSet(label, def.label);
    div.appendChild(label);

    const value = document.createElement('div');
    value.className = 'value';
    const valText = (latestVal === null || latestVal === undefined) ? '—' : fmt1(latestVal);
    value.appendChild(document.createTextNode(valText + ' '));
    const unitSpan = document.createElement('span');
    unitSpan.className = 'unit';
    textContentSet(unitSpan, def.unit);
    value.appendChild(unitSpan);
    div.appendChild(value);

    if (curAvg !== null && priorAvg !== null && priorAvg !== 0) {
      const delta = curAvg - priorAvg;
      const pct = Math.abs(delta) / Math.abs(priorAvg) * 100;
      const deltaDiv = document.createElement('div');
      if (pct < 4) {
        deltaDiv.className = 'delta flat';
        textContentSet(deltaDiv, 'steady vs last week');
      } else {
        const good = (delta > 0) === def.higherGood;
        deltaDiv.className = 'delta ' + (good ? 'good' : 'bad');
        textContentSet(deltaDiv, (delta > 0 ? '+' : '') + fmt1(delta) + ' vs last week');
      }
      div.appendChild(deltaDiv);
    }

    if (def.badge && latest[def.badge]) {
      const badge = document.createElement('span');
      badge.className = 'badge';
      const lvl = String(latest[def.badge]).toUpperCase();
      let bg = 'var(--text-muted)', fg = '#fff';
      if (['HIGH','BALANCED','OPTIMAL'].includes(lvl)) { bg = 'var(--status-good)'; }
      else if (['MODERATE','UNBALANCED'].includes(lvl)) { bg = 'var(--status-warning)'; fg='#1a1a19'; }
      else if (['LOW','POOR'].includes(lvl)) { bg = 'var(--status-critical)'; }
      badge.style.background = bg; badge.style.color = fg;
      textContentSet(badge, lvl);
      div.appendChild(badge);
    }

    const sparkWrap = document.createElement('div');
    sparkWrap.innerHTML = buildSparkline(last14(daily, def.key));
    div.appendChild(sparkWrap);

    grid.appendChild(div);
  });
}
function last14(daily, key) { return lastN(daily, 14).map(d => d[key]); }

// ---------- line / band chart ----------
const NS = 'http://www.w3.org/2000/svg';
function svgEl(tag, attrs) {
  const el = document.createElementNS(NS, tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

function drawSeriesChart(container, points, opts) {
  // points: [{date, value, value2?}]  value2 used for band-low
  const W = 640, H = 200, padL = 40, padR = 12, padT = 12, padB = 24;
  const plotW = W - padL - padR, plotH = H - padT - padB;

  const svg = svgEl('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}` });
  const valid = points.filter(p => typeof p.value === 'number');
  if (!valid.length) {
    container.innerHTML = '<p class="cap">No data in this range.</p>';
    return;
  }
  let lo = Math.min(...valid.map(p => opts.band ? (p.value2 ?? p.value) : p.value));
  let hi = Math.max(...valid.map(p => p.value));
  const ticks = niceTicks(lo, hi, 4);
  lo = ticks[0]; hi = ticks[ticks.length - 1];
  const span = (hi - lo) || 1;

  const xFor = i => padL + (points.length === 1 ? plotW/2 : (i / (points.length - 1)) * plotW);
  const yFor = v => padT + plotH - ((v - lo) / span) * plotH;

  // gridlines + y labels
  ticks.forEach(t => {
    const y = yFor(t);
    svg.appendChild(svgEl('line', { class: 'gridline', x1: padL, x2: W - padR, y1: y, y2: y }));
    const lbl = svgEl('text', { class: 'axis-label', x: padL - 6, y: y + 3, 'text-anchor': 'end' });
    lbl.textContent = t;
    svg.appendChild(lbl);
  });
  svg.appendChild(svgEl('line', { class: 'baseline', x1: padL, x2: W - padR, y1: padT + plotH, y2: padT + plotH }));

  // x labels: first, middle, last
  [0, Math.floor((points.length-1)/2), points.length-1].forEach(i => {
    if (i < 0 || i >= points.length) return;
    const lbl = svgEl('text', { class: 'axis-label', x: xFor(i), y: H - 6, 'text-anchor': i===0?'start':(i===points.length-1?'end':'middle') });
    lbl.textContent = points[i].date.slice(5);
    svg.appendChild(lbl);
  });

  // path(s) with gap handling for nulls
  function pathFor(key) {
    let d = '';
    points.forEach((p, i) => {
      if (typeof p[key] !== 'number') { d += ''; return; }
      const cmd = (i === 0 || typeof points[i-1][key] !== 'number') ? 'M' : 'L';
      d += `${cmd}${xFor(i).toFixed(1)},${yFor(p[key]).toFixed(1)} `;
    });
    return d.trim();
  }

  if (opts.band) {
    let areaD = '';
    let started = false;
    points.forEach((p, i) => {
      if (typeof p.value !== 'number') return;
      areaD += (started ? 'L' : 'M') + xFor(i).toFixed(1) + ',' + yFor(p.value).toFixed(1) + ' ';
      started = true;
    });
    for (let i = points.length - 1; i >= 0; i--) {
      const p = points[i];
      const v2 = typeof p.value2 === 'number' ? p.value2 : p.value;
      if (typeof v2 !== 'number') continue;
      areaD += 'L' + xFor(i).toFixed(1) + ',' + yFor(v2).toFixed(1) + ' ';
    }
    areaD += 'Z';
    svg.appendChild(svgEl('path', { class: 'area-path', d: areaD }));
  }

  svg.appendChild(svgEl('path', { class: 'line-path', d: pathFor('value') }));

  // end dot
  for (let i = points.length - 1; i >= 0; i--) {
    if (typeof points[i].value === 'number') {
      svg.appendChild(svgEl('circle', { class: 'end-dot', r: 4, cx: xFor(i), cy: yFor(points[i].value) }));
      break;
    }
  }

  // crosshair + tooltip
  const crosshair = svgEl('line', { class: 'crosshair', x1: 0, x2: 0, y1: padT, y2: padT + plotH, style: 'opacity:0' });
  svg.appendChild(crosshair);
  const hit = svgEl('rect', { class: 'hit', x: padL, y: padT, width: plotW, height: plotH });
  svg.appendChild(hit);

  const wrap = document.createElement('div');
  wrap.className = 'chart-wrap';
  wrap.appendChild(svg);
  const tooltip = document.createElement('div');
  tooltip.className = 'tooltip';
  wrap.appendChild(tooltip);

  function nearestIndex(mx) {
    let best = 0, bestDist = Infinity;
    points.forEach((p, i) => {
      const d = Math.abs(xFor(i) - mx);
      if (d < bestDist) { bestDist = d; best = i; }
    });
    return best;
  }

  hit.addEventListener('pointermove', e => {
    const rect = svg.getBoundingClientRect();
    const mx = (e.clientX - rect.left) / rect.width * W;
    const i = nearestIndex(mx);
    const p = points[i];
    crosshair.setAttribute('x1', xFor(i)); crosshair.setAttribute('x2', xFor(i));
    crosshair.style.opacity = 1;
    tooltip.style.opacity = 1;
    tooltip.style.left = (xFor(i) / W * rect.width) + 'px';
    tooltip.style.top = (yFor(typeof p.value === 'number' ? p.value : lo) / H * rect.height) + 'px';
    const valStr = typeof p.value === 'number' ? fmt1(p.value) + (opts.unit ? ' ' + opts.unit : '') : 'no data';
    const bandStr = opts.band && typeof p.value2 === 'number' ? ` (low ${fmt1(p.value2)})` : '';
    tooltip.innerHTML = `<span class="v">${valStr}</span>${bandStr}<br>${p.date}`;
  });
  hit.addEventListener('pointerleave', () => { crosshair.style.opacity = 0; tooltip.style.opacity = 0; });

  container.appendChild(wrap);
}

function drawBarChart(container, points, opts) {
  const W = 640, H = 200, padL = 40, padR = 12, padT = 12, padB = 24;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const svg = svgEl('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}` });
  const valid = points.filter(p => typeof p.value === 'number');
  if (!valid.length) { container.innerHTML = '<p class="cap">No data in this range.</p>'; return; }
  const hi = Math.max(...valid.map(p => p.value), 0.01);
  const ticks = niceTicks(0, hi, 4);
  const maxTick = ticks[ticks.length - 1];
  const n = points.length;
  const bandW = plotW / n;
  const barW = Math.min(24, bandW * 0.6);

  ticks.forEach(t => {
    const y = padT + plotH - (t / maxTick) * plotH;
    svg.appendChild(svgEl('line', { class: 'gridline', x1: padL, x2: W - padR, y1: y, y2: y }));
    const lbl = svgEl('text', { class: 'axis-label', x: padL - 6, y: y + 3, 'text-anchor': 'end' });
    lbl.textContent = t;
    svg.appendChild(lbl);
  });
  svg.appendChild(svgEl('line', { class: 'baseline', x1: padL, x2: W - padR, y1: padT + plotH, y2: padT + plotH }));

  const wrap = document.createElement('div');
  wrap.className = 'chart-wrap';
  const tooltip = document.createElement('div');
  tooltip.className = 'tooltip';

  points.forEach((p, i) => {
    const cx = padL + bandW * i + bandW/2;
    const val = typeof p.value === 'number' ? p.value : 0;
    const barH = (val / maxTick) * plotH;
    const y = padT + plotH - barH;
    const rect = svgEl('rect', { class: 'bar', x: cx - barW/2, y, width: barW, height: Math.max(barH,1), rx: 4 });
    svg.appendChild(rect);
    const hit = svgEl('rect', { class: 'hit', x: cx - bandW/2, y: padT, width: bandW, height: plotH });
    hit.addEventListener('pointermove', e => {
      const rect2 = svg.getBoundingClientRect();
      tooltip.style.opacity = 1;
      tooltip.style.left = (cx / W * rect2.width) + 'px';
      tooltip.style.top = (y / H * rect2.height) + 'px';
      tooltip.innerHTML = `<span class="v">${fmt1(val)} ${opts.unit||''}</span><br>${p.date}`;
    });
    hit.addEventListener('pointerleave', () => { tooltip.style.opacity = 0; });
    svg.appendChild(hit);
  });

  if (n <= 20) {
    [0, Math.floor((n-1)/2), n-1].forEach(i => {
      if (i < 0 || i >= n) return;
      const cx = padL + bandW * i + bandW/2;
      const lbl = svgEl('text', { class: 'axis-label', x: cx, y: H - 6, 'text-anchor': 'middle' });
      lbl.textContent = points[i].date.slice(5);
      svg.appendChild(lbl);
    });
  }

  wrap.appendChild(svg);
  wrap.appendChild(tooltip);
  container.appendChild(wrap);
}

// ---------- table view ----------
function buildTable(points, cols) {
  const table = document.createElement('table');
  table.className = 'data-table';
  const thead = document.createElement('thead');
  const htr = document.createElement('tr');
  cols.forEach(c => { const th = document.createElement('th'); textContentSet(th, c.label); htr.appendChild(th); });
  thead.appendChild(htr);
  table.appendChild(thead);
  const tbody = document.createElement('tbody');
  [...points].reverse().forEach(p => {
    const tr = document.createElement('tr');
    cols.forEach(c => {
      const td = document.createElement('td');
      if (c.num) td.className = 'num';
      const v = p[c.key];
      textContentSet(td, (v === null || v === undefined) ? '—' : v.toString());
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  return table;
}

// ---------- chart cards ----------
const CHART_RECOVERY = [
  { id: 'hrv', title: 'HRV (overnight average)', key: 'hrv', unit: 'ms', type: 'line' },
  { id: 'rhr', title: 'Resting heart rate', key: 'rhr', unit: 'bpm', type: 'line' },
  { id: 'sleep', title: 'Sleep score', key: 'sleep_score', unit: 'pts', type: 'line' },
  { id: 'readiness', title: 'Training readiness', key: 'readiness', unit: 'pts', type: 'line' },
  { id: 'bodybattery', title: 'Body battery range', key: 'bb_high', key2: 'bb_low', unit: '', type: 'band' },
  { id: 'stress', title: 'Average daily stress', key: 'stress', unit: '', type: 'line' },
];
const CHART_CYCLING = [
  { id: 'vo2cycle', title: 'VO2 max (cycling, estimated)', key: 'vo2max_cycling', unit: '', type: 'line',
    note: "Garmin only recalculates this after qualifying rides; value is carried forward between updates." },
  { id: 'ftp', title: 'Cycling FTP (Garmin estimate)', key: 'ftp', unit: 'W', type: 'line',
    note: "Garmin's API only exposes the current FTP reading, not history — this trend builds from the day syncing started, forward-filled between recalculations." },
];
const CHART_RUNNING = [
  { id: 'vo2run', title: 'VO2 max (running, estimated)', key: 'vo2max_running', unit: '', type: 'line',
    note: "Garmin only recalculates this after qualifying runs; value is carried forward between updates." },
];

let currentDays = 365;

function filteredDaily() {
  if (currentDays === 'all') return DATA.daily;
  return lastN(DATA.daily, currentDays);
}
function filteredWeekly() {
  if (currentDays === 'all') return DATA.weekly;
  const cutoffDays = Math.ceil(currentDays / 7) + 1;
  return lastN(DATA.weekly, cutoffDays);
}
function filteredActivities() {
  if (currentDays === 'all') return DATA.activities;
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - currentDays);
  const cutoffStr = cutoff.toISOString().slice(0,10);
  return DATA.activities.filter(a => a.date >= cutoffStr);
}

function renderChartGroup(defs, gridId) {
  const grid = document.getElementById(gridId);
  grid.innerHTML = '';
  const daily = filteredDaily();

  defs.forEach(def => {
    const card = document.createElement('div');
    card.className = 'card chart-card';
    const head = document.createElement('div');
    head.className = 'head-row';
    const titleWrap = document.createElement('div');
    const h3 = document.createElement('h3'); textContentSet(h3, def.title); titleWrap.appendChild(h3);
    const cap = document.createElement('p'); cap.className = 'cap';
    textContentSet(cap, def.note || (def.unit ? `Unit: ${def.unit}` : 'Score'));
    titleWrap.appendChild(cap);
    head.appendChild(titleWrap);
    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'table-toggle';
    textContentSet(toggleBtn, 'View as table');
    head.appendChild(toggleBtn);
    card.appendChild(head);

    const chartView = document.createElement('div');
    chartView.className = 'chart-view';
    const tableView = document.createElement('div');
    tableView.className = 'table-view';

    const points = daily.map(d => ({ date: d.date, value: d[def.key], value2: def.key2 ? d[def.key2] : undefined }));
    if (def.type === 'band') {
      drawSeriesChart(chartView, points, { band: true, unit: def.unit });
      tableView.appendChild(buildTable(daily.map(d => ({date: d.date, high: d.bb_high, low: d.bb_low})),
        [{key:'date',label:'Date'},{key:'high',label:'High',num:true},{key:'low',label:'Low',num:true}]));
    } else {
      drawSeriesChart(chartView, points, { unit: def.unit });
      tableView.appendChild(buildTable(daily.map(d => ({date: d.date, value: d[def.key]})),
        [{key:'date',label:'Date'},{key:'value',label:def.title,num:true}]));
    }

    toggleBtn.addEventListener('click', () => {
      const showing = tableView.classList.toggle('shown');
      chartView.classList.toggle('hidden', showing);
      textContentSet(toggleBtn, showing ? 'View as chart' : 'View as table');
    });

    card.appendChild(chartView);
    card.appendChild(tableView);
    grid.appendChild(card);
  });
}

function renderVolumeChart() {
  const grid = document.getElementById('chartGridVolume');
  grid.innerHTML = '';
  const weekly = filteredWeekly();
  const card = document.createElement('div');
  card.className = 'card chart-card';
  const head = document.createElement('div');
  head.className = 'head-row';
  const titleWrap = document.createElement('div');
  const h3 = document.createElement('h3'); textContentSet(h3, 'Weekly training volume'); titleWrap.appendChild(h3);
  const cap = document.createElement('p'); cap.className = 'cap'; textContentSet(cap, 'Distance per week (km), Monday start, all activity types'); titleWrap.appendChild(cap);
  head.appendChild(titleWrap);
  const toggleBtn = document.createElement('button'); toggleBtn.className = 'table-toggle'; textContentSet(toggleBtn, 'View as table');
  head.appendChild(toggleBtn);
  card.appendChild(head);
  const chartView = document.createElement('div'); chartView.className = 'chart-view';
  const tableView = document.createElement('div'); tableView.className = 'table-view';
  drawBarChart(chartView, weekly.map(w => ({ date: w.week_start, value: w.km })), { unit: 'km' });
  tableView.appendChild(buildTable(weekly.map(w => ({date: w.week_start, km: w.km, workouts: w.count})),
    [{key:'date',label:'Week of'},{key:'km',label:'Km',num:true},{key:'workouts',label:'Workouts',num:true}]));
  toggleBtn.addEventListener('click', () => {
    const showing = tableView.classList.toggle('shown');
    chartView.classList.toggle('hidden', showing);
    textContentSet(toggleBtn, showing ? 'View as chart' : 'View as table');
  });
  card.appendChild(chartView); card.appendChild(tableView);
  grid.appendChild(card);
}

function renderActivitiesTable() {
  const tbody = document.querySelector('#activitiesTable tbody');
  tbody.innerHTML = '';
  filteredActivities().forEach(a => {
    const tr = document.createElement('tr');
    const cells = [
      a.date, a.name, a.type,
      a.distance_km ? a.distance_km + ' km' : '—',
      a.duration_min ? a.duration_min + ' min' : '—',
      a.avg_hr || '—',
      a.calories || '—',
    ];
    cells.forEach((v, i) => {
      const td = document.createElement('td');
      if (i >= 3) td.className = 'num';
      textContentSet(td, v.toString());
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function renderAllCharts() {
  renderChartGroup(CHART_RECOVERY, 'chartGridRecovery');
  renderChartGroup(CHART_CYCLING, 'chartGridCycling');
  renderChartGroup(CHART_RUNNING, 'chartGridRunning');
  renderVolumeChart();
}

function renderAll() {
  renderKPIGroup(KPI_RECOVERY, 'kpiGridRecovery');
  renderKPIGroup(KPI_CYCLING, 'kpiGridCycling');
  renderKPIGroup(KPI_RUNNING, 'kpiGridRunning');
  renderAllCharts();
  renderActivitiesTable();
}

document.querySelectorAll('#filters button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#filters button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const d = btn.getAttribute('data-days');
    currentDays = d === 'all' ? 'all' : parseInt(d, 10);
    renderAllCharts();
    renderActivitiesTable();
  });
});

renderAll();
</script>
</body>
</html>
"""


def main():
    if not os.path.exists(DATA_JSON):
        print(f"No data found at {DATA_JSON}. Run sync_garmin.py first.")
        return

    with open(DATA_JSON, "r", encoding="utf-8") as f:
        raw = json.load(f)

    ftp_history = raw.get("cycling_ftp_history", [])
    daily = extract_daily(raw.get("wellness", {}))
    merge_ftp_history(daily, ftp_history)
    activities = extract_activities(raw.get("activities", []), raw.get("exercise_sets", {}))
    weekly = compute_weekly_volume(activities)
    insights = compute_insights(daily, activities)
    suggestions = compute_suggestions(daily, activities, weekly, ftp_history)
    tomorrow_focus = compute_tomorrow_focus(daily, activities)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = render_html(daily, activities, weekly, insights, suggestions, tomorrow_focus, generated_at)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard written to {OUTPUT_HTML}")
    print(f"  {len(daily)} wellness days, {len(activities)} activities, {len(weekly)} weeks")


if __name__ == "__main__":
    main()
