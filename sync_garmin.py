"""
Pulls recent Garmin activities and daily wellness data (sleep, HRV, resting
heart rate, body battery, stress, steps, training readiness) and writes them
as plain-English markdown notes into the garmin/ folder, plus a data.json
file with the raw values.

Read-only: this script only calls "get_*" methods on the Garmin Connect
client. It never writes, deletes, or modifies anything on your Garmin
account.

Usage:
    venv\\Scripts\\python.exe sync_garmin.py --days 3
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

from garminconnect import Garmin

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKENSTORE = os.path.join(PROJECT_DIR, ".garmin_tokens")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "garmin")
DATA_JSON = os.path.join(OUTPUT_DIR, "data.json")


def connect():
    client = Garmin()
    try:
        client.login(TOKENSTORE)
    except Exception as exc:
        print("Could not resume your saved Garmin session.")
        print(f"Details: {exc}")
        print("Run login.py again to sign back in.")
        sys.exit(1)
    return client


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


def sec_to_hm(sec):
    if not isinstance(sec, (int, float)):
        return None
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def write_activity_note(activity):
    activity_id = activity.get("activityId")
    name = activity.get("activityName") or "Workout"
    activity_type = safe_get(activity, "activityType", "typeKey", default="activity")
    start = activity.get("startTimeLocal", "")
    day = start.split(" ")[0] if start else "unknown-date"

    distance_km = m_to_km(activity.get("distance"))
    duration_sec = activity.get("duration")
    duration = sec_to_hm(duration_sec)
    calories = activity.get("calories")
    avg_hr = activity.get("averageHR")
    max_hr = activity.get("maxHR")

    avg_pace = None
    if distance_km and duration_sec and distance_km > 0:
        avg_pace = sec_to_hm(duration_sec / distance_km)

    lines = [f"# {name}", ""]
    lines.append(f"- Date: {day}")
    lines.append(f"- Type: {activity_type}")
    if distance_km:
        lines.append(f"- Distance: {distance_km} km")
    if duration:
        lines.append(f"- Duration: {duration}")
    if avg_pace:
        lines.append(f"- Average pace: {avg_pace} / km")
    if calories:
        lines.append(f"- Calories: {calories}")
    if avg_hr:
        lines.append(f"- Average heart rate: {avg_hr} bpm")
    if max_hr:
        lines.append(f"- Max heart rate: {max_hr} bpm")
    aerobic = activity.get("aerobicTrainingEffect")
    anaerobic = activity.get("anaerobicTrainingEffect")
    if aerobic:
        lines.append(f"- Aerobic training effect: {aerobic}")
    if anaerobic:
        lines.append(f"- Anaerobic training effect: {anaerobic}")

    filename = f"{day}-activity-{activity_id}.md"
    with open(os.path.join(OUTPUT_DIR, filename), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return filename


def write_wellness_note(day, sleep, hrv, rhr, body_battery, stress, steps, readiness, max_metrics=None):
    lines = [f"# Recovery & wellness — {day}", ""]

    sleep_dto = safe_get(sleep, "dailySleepDTO", default={}) or {}
    sleep_seconds = sleep_dto.get("sleepTimeSeconds")
    sleep_score = safe_get(sleep, "dailySleepDTO", "sleepScores", "overall", "value")
    if sleep_seconds:
        lines.append(f"- Sleep duration: {sec_to_hm(sleep_seconds)}")
    if sleep_score:
        lines.append(f"- Sleep score: {sleep_score}")
    deep = sleep_dto.get("deepSleepSeconds")
    rem = sleep_dto.get("remSleepSeconds")
    light = sleep_dto.get("lightSleepSeconds")
    awake = sleep_dto.get("awakeSleepSeconds")
    if deep:
        lines.append(f"- Deep sleep: {sec_to_hm(deep)}")
    if rem:
        lines.append(f"- REM sleep: {sec_to_hm(rem)}")
    if light:
        lines.append(f"- Light sleep: {sec_to_hm(light)}")
    if awake:
        lines.append(f"- Awake: {sec_to_hm(awake)}")

    hrv_avg = safe_get(hrv, "hrvSummary", "lastNightAvg")
    hrv_status = safe_get(hrv, "hrvSummary", "status")
    if hrv_avg:
        lines.append(f"- HRV (overnight average): {hrv_avg} ms")
    if hrv_status:
        lines.append(f"- HRV status: {hrv_status}")

    rhr_value = rhr.get("restingHeartRate") if isinstance(rhr, dict) else None
    if not rhr_value:
        rhr_value = safe_get(
            rhr, "allMetrics", "metricsMap", "WELLNESS_RESTING_HEART_RATE", 0, "value"
        )
    if rhr_value:
        lines.append(f"- Resting heart rate: {rhr_value} bpm")

    bb_high = bb_low = None
    if isinstance(body_battery, list) and body_battery:
        values = body_battery[0].get("bodyBatteryValuesArray") or []
        levels = [
            v[1]
            for v in values
            if isinstance(v, list) and len(v) > 1 and isinstance(v[1], (int, float))
        ]
        if levels:
            bb_high, bb_low = max(levels), min(levels)
    if bb_high is not None:
        lines.append(f"- Body battery range: {bb_low} to {bb_high}")

    avg_stress = stress.get("avgStressLevel") if isinstance(stress, dict) else None
    if isinstance(avg_stress, (int, float)) and avg_stress >= 0:
        lines.append(f"- Average stress level: {avg_stress}")

    total_steps = None
    if isinstance(steps, list) and steps:
        total_steps = sum(s.get("steps", 0) or 0 for s in steps if isinstance(s, dict))
    if total_steps:
        lines.append(f"- Steps: {total_steps}")

    readiness_score = readiness_level = None
    if isinstance(readiness, list) and readiness:
        readiness_score = readiness[0].get("score")
        readiness_level = readiness[0].get("level")
    elif isinstance(readiness, dict):
        readiness_score = readiness.get("score")
        readiness_level = readiness.get("level")
    if readiness_score is not None:
        if readiness_level:
            lines.append(f"- Training readiness: {readiness_score} ({readiness_level})")
        else:
            lines.append(f"- Training readiness: {readiness_score}")

    vo2max_running = safe_get(max_metrics, 0, "generic", "vo2MaxValue")
    vo2max_cycling = safe_get(max_metrics, 0, "cycling", "vo2MaxValue")
    if vo2max_running:
        lines.append(f"- VO2 max (running): {vo2max_running}")
    if vo2max_cycling:
        lines.append(f"- VO2 max (cycling): {vo2max_cycling}")

    if len(lines) == 2:
        lines.append("- No wellness data was available from Garmin for this day.")

    filename = f"{day}-wellness.md"
    with open(os.path.join(OUTPUT_DIR, filename), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return filename


def main():
    parser = argparse.ArgumentParser(description="Sync recent Garmin activity and wellness data.")
    parser.add_argument("--days", type=int, default=7, help="How many recent days to pull (default 7)")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    client = connect()

    today = date.today()
    start_day = today - timedelta(days=args.days - 1)
    print(f"Pulling data from {start_day} to {today}...")

    if os.path.exists(DATA_JSON):
        with open(DATA_JSON, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        raw_data.setdefault("activities", [])
        raw_data.setdefault("wellness", {})
    else:
        raw_data = {"activities": [], "wellness": {}}
    notes_written = []

    try:
        activities = client.get_activities_by_date(start_day.isoformat(), today.isoformat())
    except Exception as exc:
        print(f"Warning: could not fetch activities ({exc})")
        activities = []

    existing_by_id = {a.get("activityId"): a for a in raw_data["activities"]}
    for activity in activities:
        existing_by_id[activity.get("activityId")] = activity
    raw_data["activities"] = sorted(
        existing_by_id.values(), key=lambda a: a.get("startTimeLocal", "")
    )
    for activity in activities:
        notes_written.append(write_activity_note(activity))

    day_cursor = start_day
    while day_cursor <= today:
        day_str = day_cursor.isoformat()
        print(f"  wellness for {day_str}...")

        fetchers = {
            "sleep": lambda: client.get_sleep_data(day_str),
            "hrv": lambda: client.get_hrv_data(day_str),
            "rhr": lambda: client.get_rhr_day(day_str),
            "body_battery": lambda: client.get_body_battery(day_str),
            "stress": lambda: client.get_all_day_stress(day_str),
            "steps": lambda: client.get_daily_steps(day_str, day_str),
            "training_readiness": lambda: client.get_training_readiness(day_str),
            "max_metrics": lambda: client.get_max_metrics(day_str),
        }
        day_data = {}
        for key, fn in fetchers.items():
            try:
                day_data[key] = fn()
            except Exception:
                day_data[key] = None

        raw_data["wellness"][day_str] = day_data

        notes_written.append(
            write_wellness_note(
                day_str,
                day_data.get("sleep") or {},
                day_data.get("hrv") or {},
                day_data.get("rhr") or {},
                day_data.get("body_battery") or [],
                day_data.get("stress") or {},
                day_data.get("steps") or [],
                day_data.get("training_readiness") or [],
                day_data.get("max_metrics") or [],
            )
        )
        day_cursor += timedelta(days=1)

    try:
        ftp_raw = client.get_cycling_ftp()
        ftp_entry = ftp_raw[0] if isinstance(ftp_raw, list) and ftp_raw else ftp_raw
        ftp_value = ftp_entry.get("functionalThresholdPower") if isinstance(ftp_entry, dict) else None
        ftp_date = ftp_entry.get("calendarDate") if isinstance(ftp_entry, dict) else None
        if ftp_value and ftp_date:
            ftp_day = str(ftp_date).split("T")[0]
            history = raw_data.setdefault("cycling_ftp_history", [])
            if not any(h.get("date") == ftp_day for h in history):
                history.append({"date": ftp_day, "ftp": ftp_value})
                history.sort(key=lambda h: h["date"])
            print(f"Cycling FTP: {ftp_value}W (as of {ftp_day})")
    except Exception as exc:
        print(f"Warning: could not fetch cycling FTP ({exc})")

    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=2, default=str)

    print()
    print(f"Done. Wrote {len(notes_written)} notes to {OUTPUT_DIR}")
    for fname in sorted(notes_written):
        print(f"  - {fname}")


if __name__ == "__main__":
    main()
