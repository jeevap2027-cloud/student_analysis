#!/usr/bin/env python3
"""
🎓 STUDENT PERFORMANCE PORTAL — Role-based login + Analytics (NumPy + Pandas + CSV)

Roles

  ADMIN    → everything (students, marks, subjects, users, audit log)
  HOD      → analytics, add student, add/alter marks, attendance, export
             (cannot remove students, manage users or read audit log)
  STUDENT  → only his/her own report card + change password

Files (auto-created in the same folder)
  students.csv   student data   (RollNo, Name, <subjects...>, StudyHours, Attendance)
  users.csv      login accounts (passwords stored as salted PBKDF2 hashes)
  audit_log.csv  who did what and when

Run:  python student_portal.py
"""

import getpass
import hmac
import hashlib
import os
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

# ───────────────────────── Config ─────────────────────────
STUDENTS_CSV, USERS_CSV, AUDIT_CSV = "students.csv", "users.csv", "audit_log.csv"
ID, NAME, HOURS, ATT = "RollNo", "Name", "StudyHours", "Attendance"
META = [ID, NAME, HOURS, ATT]
MAX_ATTEMPTS = 3
W = 64

# 🔐 EDIT THIS TABLE to change who can do what
PERMISSIONS = {
    "admin": {"analytics", "view_all", "add_student", "remove_student", "edit_marks",
              "add_subject", "edit_attendance", "export", "manage_users", "view_audit",
              "change_password"},
    "hod": {"analytics", "view_all", "add_student", "edit_marks", "edit_attendance",
            "export", "change_password"},
    "student": {"view_self", "change_password"},
}

# ───────────────────────── Colors / UI ─────────────────────────
R, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
RED, GREEN, YELLOW = "\033[91m", "\033[92m", "\033[93m"
BLUE, MAGENTA, CYAN, GRAY = "\033[94m", "\033[95m", "\033[96m", "\033[90m"
ROLE_COLOR = {"admin": RED, "hod": YELLOW, "student": GREEN}
ROLE_ICON = {"admin": "👑", "hod": "🎓", "student": "📘"}


def c(text, color):
    return f"{color}{text}{R}"


def clear():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def typewriter(text, delay=0.008):
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)
    print()


def banner():
    art = r"""
   ____  _             _            _     ____            _        _
  / ___|| |_ _   _  __| | ___ _ __ | |_  |  _ \ ___  _ __| |_ __ _| |
  \___ \| __| | | |/ _` |/ _ \ '_ \| __| | |_) / _ \| '__| __/ _` | |
   ___) | |_| |_| | (_| |  __/ | | | |_  |  __/ (_) | |  | || (_| | |
  |____/ \__|\__,_|\__,_|\___|_| |_|\__| |_|   \___/|_|   \__\__,_|_|
"""
    print(c(art, CYAN))
    print(c("  ✦ S T U D E N T   P E R F O R M A N C E   P O R T A L ✦", MAGENTA + BOLD))
    print(c("  " + "─" * W, GRAY))


def section(title, emoji="◆"):
    print(f"\n{c(f'{emoji}  {title.upper()}', YELLOW + BOLD)}")
    print(c("  " + "─" * W, GRAY))


def ok(msg):
    print(c(f"  ✔ {msg}", GREEN))


def err(msg):
    print(c(f"  ✘ {msg}", RED))


def pause():
    input(c("\n  ⏎ Press Enter to continue...", GRAY))


def ask(prompt, cast=str, lo=None, hi=None, blank=False):
    """Validated input. blank=True lets the user press Enter to skip (returns None)."""
    while True:
        raw = input(c(f"  {prompt}: ", CYAN)).strip()
        if raw == "":
            if blank:
                return None
            err("This field is required.")
            continue
        try:
            v = cast(raw)
        except ValueError:
            err("Invalid value, try again.")
            continue
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            err(f"Enter a value between {lo} and {hi}.")
            continue
        return v


def secret(prompt):
    try:
        return getpass.getpass(c(prompt, CYAN))
    except Exception:
        return input(prompt)


def confirm(msg):
    return input(c(f"  ⚠ {msg} [y/N]: ", YELLOW)).strip().lower() == "y"


def color_for(score):
    return GREEN if score >= 75 else CYAN if score >= 65 else YELLOW if score >= 50 else RED


def bar(value, max_value=100, width=24):
    filled = int(round(np.clip(value / max_value, 0, 1) * width))
    return c("█" * filled, color_for(value)) + c("░" * (width - filled), GRAY)


def sparkline(values):
    ticks = "▁▂▃▄▅▆▇█"
    v = np.asarray(values, dtype=float)
    span = np.ptp(v) or 1
    return "".join(ticks[i] for i in ((v - v.min()) / span * (len(ticks) - 1)).astype(int))


GRADE_COLORS = {"A+": GREEN, "A": GREEN, "B": CYAN, "C": YELLOW, "D": MAGENTA, "F": RED}

# ───────────────────────── Storage layer (CSV) ─────────────────────────
def save_csv(df, path):
    """Atomic save so a crash never corrupts the CSV."""
    tmp = path + ".tmp"
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)


def subjects_of(df):
    return [col for col in df.columns if col not in META]


def load_students():
    try:
        df = pd.read_csv(STUDENTS_CSV, dtype={ID: str})
    except FileNotFoundError:
        sys.exit(c(f"\n  ✘ {STUDENTS_CSV} not found. Put it next to this script.\n", RED))
    df.columns = df.columns.str.strip()
    if ID not in df.columns:                      # auto-create roll numbers
        df.insert(0, ID, [f"S{i:03d}" for i in range(1, len(df) + 1)])
        save_csv(df, STUDENTS_CSV)
    for col in (NAME, HOURS, ATT):
        if col not in df.columns:
            sys.exit(c(f"\n  ✘ Missing required column: {col}\n", RED))
    subs = subjects_of(df)
    num = subs + [HOURS, ATT]
    df[num] = df[num].apply(pd.to_numeric, errors="coerce")
    df[num] = df[num].fillna(df[num].median()).fillna(0)
    df[subs] = df[subs].clip(0, 100).round().astype(int)
    df[NAME] = df[NAME].astype(str).str.strip()
    df[ID] = df[ID].astype(str).str.strip()
    return df.drop_duplicates(subset=ID).reset_index(drop=True)


def save_students(df):
    save_csv(df, STUDENTS_CSV)


USER_COLS = ["username", "role", "salt", "pwhash", "linked_roll", "must_change", "failed", "locked"]


def hash_pw(pw, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt_hex), 120_000).hex()


def make_user(username, role, pw, linked="", must_change=1):
    salt = os.urandom(8).hex()
    return {"username": username.lower(), "role": role, "salt": salt,
            "pwhash": hash_pw(pw, salt), "linked_roll": linked,
            "must_change": must_change, "failed": 0, "locked": 0}


def load_users():
    df = pd.read_csv(USERS_CSV, dtype=str).fillna("")
    for col in ("must_change", "failed", "locked"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    return df


def save_users(df):
    save_csv(df[USER_COLS], USERS_CSV)


def update_user(username, **fields):
    df = load_users()
    mask = df["username"] == username
    for k, v in fields.items():
        df.loc[mask, k] = v
    save_users(df)


def add_user(row):
    df = load_users()
    save_users(pd.concat([df, pd.DataFrame([row])], ignore_index=True))


def log(user, action, detail=""):
    row = pd.DataFrame([{"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                         "user": user.get("username", "?"), "role": user.get("role", "-"),
                         "action": action, "detail": detail}])
    row.to_csv(AUDIT_CSV, mode="a", header=not os.path.exists(AUDIT_CSV), index=False)


def bootstrap():
    """First run: create admin, HOD and one account per student."""
    load_students()
    if os.path.exists(USERS_CSV):
        return
    rows = [make_user("admin", "admin", "Admin@123"), make_user("hod", "hod", "Hod@123")]
    for roll in load_students()[ID]:
        rows.append(make_user(roll.lower(), "student", f"Welcome@{roll}", roll))
    save_users(pd.DataFrame(rows))
    clear()
    banner()
    section("First-run setup complete", "🚀")
    print(f"  {c('Admin  ', RED + BOLD)} username: admin     password: Admin@123")
    print(f"  {c('HOD    ', YELLOW + BOLD)} username: hod       password: Hod@123")
    print(f"  {c('Student', GREEN + BOLD)} username: s001      password: Welcome@S001  (roll no based)")
    print(c("\n  You will be asked to change the password at first login.", DIM))
    pause()


# ───────────────────────── Permissions ─────────────────────────
def can(role, perm):
    return perm in PERMISSIONS.get(role, set())


def requires(perm):
    def deco(fn):
        def wrapper(user, *a, **k):
            if not can(user["role"], perm):
                err("Access denied for your role.")
                log(user, "ACCESS_DENIED", perm)
                return
            return fn(user, *a, **k)
        wrapper.__name__ = fn.__name__
        return wrapper
    return deco


# ───────────────────────── Analytics (NumPy + Pandas) ─────────────────────────
def enrich(df, subjects):
    d = df.copy()
    d["Average"] = d[subjects].mean(axis=1).fillna(0)
    d["Grade"] = pd.cut(d["Average"], bins=[-np.inf, 50, 60, 70, 80, 90, np.inf],
                        labels=["F", "D", "C", "B", "A", "A+"], right=False).astype(str)
    d["Best"] = d[subjects].idxmax(axis=1)
    d["Weak"] = d[subjects].idxmin(axis=1)
    d["Consistency"] = d[subjects].std(axis=1, ddof=0).fillna(0)
    d = d.sort_values("Average", ascending=False).reset_index(drop=True)
    d["Rank"] = np.arange(1, len(d) + 1)
    return d


def overview(d):
    a = d["Average"].to_numpy()
    section("Class Overview", "📊")
    q1, q3 = np.percentile(a, [25, 75])
    pr = (a >= 50).mean() * 100
    rows = [("Students", f"{len(d)}", CYAN), ("Class Average", f"{a.mean():.1f}%", GREEN),
            ("Median", f"{np.median(a):.1f}%", BLUE), ("Std Deviation", f"{a.std():.1f}", MAGENTA),
            ("Q1 / Q3", f"{q1:.1f} / {q3:.1f}", BLUE),
            ("Pass Rate", f"{pr:.0f}%", GREEN if pr >= 80 else YELLOW),
            ("Highest / Lowest", f"{a.max():.1f} / {a.min():.1f}", YELLOW)]
    for label, val, col in rows:
        print(f"  {c(label.ljust(18), GRAY)} {c(val, col + BOLD)}")
    print(f"  {c('Score spread'.ljust(18), GRAY)} {c(sparkline(a[::-1]), CYAN)}")


def leaderboard(d):
    section("Leaderboard", "🏆")
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    print(c(f"  {'#':<4}{'Roll':<7}{'Name':<11}{'Avg':>6}  {'Grd':<5}{'Performance':<26}", GRAY + BOLD))
    for _, s in d.iterrows():
        rk = medals.get(s["Rank"], f"{s['Rank']:>2}")
        gc = GRADE_COLORS[s["Grade"]]
        print(f"  {rk:<4}{s[ID]:<7}{c(s[NAME][:10].ljust(11), BOLD)}{s['Average']:>6.1f}  "
              f"{c(s['Grade'].ljust(5), gc + BOLD)}{bar(s['Average'])}")


def subject_analysis(d, subs):
    section("Subject Analysis", "📚")
    stats = d[subs].agg(["mean", "max", "min", "std"]).T.sort_values("mean", ascending=False)
    passp = (d[subs] >= 50).mean() * 100
    print(c(f"  {'Subject':<12}{'Avg':>6}{'Max':>6}{'Min':>6}{'Pass%':>7}   Average", GRAY + BOLD))
    for sub, r in stats.iterrows():
        print(f"  {sub:<12}{r['mean']:>6.1f}{r['max']:>6.0f}{r['min']:>6.0f}{passp[sub]:>6.0f}%   {bar(r['mean'], width=18)}")
    print(f"\n  {c('💡 Strongest:', GREEN)} {stats.index[0]}    {c('⚠ Needs attention:', RED)} {stats.index[-1]}")


def grade_distribution(d):
    section("Grade Distribution", "🎯")
    counts = d["Grade"].value_counts().reindex(["A+", "A", "B", "C", "D", "F"], fill_value=0)
    for g, n in counts.items():
        print(f"  {c(g.ljust(3), GRADE_COLORS[g] + BOLD)} {c('■' * int(n * 3), GRADE_COLORS[g])} "
              f"{n} {c(f'({n / len(d) * 100:.0f}%)', GRAY)}")


def insights(d):
    section("Smart Insights", "🧠")
    if len(d) >= 3:
        rh, ra = d[HOURS].corr(d["Average"]), d[ATT].corr(d["Average"])
        fmt = lambda r: "n/a" if np.isnan(r) else f"{r:+.2f}"
        print(f"  📖 Study hours ↔ score   r = {c(fmt(rh), CYAN + BOLD)}")
        print(f"  🏫 Attendance  ↔ score   r = {c(fmt(ra), CYAN + BOLD)}")
        if d[HOURS].nunique() > 1:
            slope, _ = np.polyfit(d[HOURS], d["Average"], 1)
            print(f"  📈 Each extra study hour ≈ {c(f'{slope:+.1f}', GREEN + BOLD)} marks")
    risk = d[(d["Average"] < 55) | (d[ATT] < 65)]
    print(f"\n  {c('🚨 At-risk students', RED + BOLD)}")
    if risk.empty:
        print(c("     None — the whole class is cruising! 🌴", GREEN))
    for _, s in risk.iterrows():
        why = []
        if s["Average"] < 55: why.append(f"avg {s['Average']:.0f}%")
        if s[ATT] < 65: why.append(f"attendance {s[ATT]:.0f}%")
        print(f"     • {c(s[NAME], BOLD)} ({s[ID]}) → {', '.join(why)} | weak in {c(s['Weak'], YELLOW)}")


def student_card(s, subs, total):
    print()
    print(c("  ╭" + "─" * 46 + "╮", MAGENTA))
    print(c("  │ ", MAGENTA) + c(f"{s[NAME]} ({s[ID]})".ljust(30)[:30], BOLD + CYAN) +
          c(f"Rank #{s['Rank']}/{total}".rjust(14), YELLOW) + c(" │", MAGENTA))
    print(c("  ├" + "─" * 46 + "┤", MAGENTA))
    for sub in subs:
        print(c("  │ ", MAGENTA) + f"{sub[:10]:<10}{s[sub]:>4.0f}  {bar(s[sub], width=22)}" + " " * 6 + c(" │", MAGENTA))
    print(c("  ├" + "─" * 46 + "┤", MAGENTA))
    for line in (f"Avg {s['Average']:.1f}%   Grade {s['Grade']}   Top {s['Rank'] / total * 100:.0f}%",
                 f"Study {s[HOURS]}h/day   Attendance {s[ATT]:.0f}%"):
        print(c("  │ ", MAGENTA) + line.ljust(44) + c(" │", MAGENTA))
    print(c("  ╰" + "─" * 46 + "╯", MAGENTA))


# ───────────────────────── Student helpers ─────────────────────────
def pick_student(df):
    q = ask("Roll No or Name", blank=True)
    if q is None:
        return None
    m = df[(df[ID].str.lower() == q.lower()) | (df[NAME].str.lower() == q.lower())]
    if m.empty:
        err("Student not found.")
        return None
    return m.index[0]


def next_roll(df):
    nums = pd.to_numeric(df[ID].str.extract(r"(\d+)")[0], errors="coerce").fillna(0)
    return f"S{int(nums.max()) + 1:03d}"


# ───────────────────────── Feature screens ─────────────────────────
@requires("analytics")
def analytics_dashboard(user):
    df = load_students()
    if df.empty:
        err("No students in the database.")
        return
    subs = subjects_of(df)
    d = enrich(df, subs)
    overview(d)
    leaderboard(d)
    subject_analysis(d, subs)
    grade_distribution(d)
    insights(d)
    log(user, "VIEW_ANALYTICS")


@requires("view_all")
def find_student(user):
    section("Find Student", "🔍")
    df = load_students()
    idx = pick_student(df)
    if idx is None:
        return
    subs = subjects_of(df)
    d = enrich(df, subs)
    s = d[d[ID] == df.loc[idx, ID]].iloc[0]
    student_card(s, subs, len(d))
    log(user, "VIEW_STUDENT", s[ID])


@requires("add_student")
def add_student(user):
    section("Add Student", "➕")
    df = load_students()
    subs = subjects_of(df)
    name = ask("Student name").title()
    roll = next_roll(df)
    print(c(f"  Roll number assigned: {roll}", DIM))
    row = {ID: roll, NAME: name}
    for sub in subs:
        row[sub] = ask(f"{sub} marks (0-100)", int, 0, 100)
    row[HOURS] = ask("Study hours per day (0-24)", float, 0, 24)
    row[ATT] = ask("Attendance % (0-100)", int, 0, 100)
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_students(df)
    add_user(make_user(roll.lower(), "student", f"Welcome@{roll}", roll))
    log(user, "ADD_STUDENT", f"{roll} {name}")
    ok(f"{name} added as {roll}.")
    print(c(f"  Student login → username: {roll.lower()}  password: Welcome@{roll}", DIM))


@requires("remove_student")
def remove_student(user):
    section("Remove Student", "🗑️")
    df = load_students()
    idx = pick_student(df)
    if idx is None:
        return
    s = df.loc[idx]
    print(f"\n  About to delete {c(s[NAME], BOLD)} ({s[ID]}) and the linked login.")
    typed = input(c(f"  Type the roll number ({s[ID]}) to confirm: ", YELLOW)).strip()
    if typed.lower() != s[ID].lower():
        err("Confirmation failed — nothing deleted.")
        return
    save_students(df.drop(idx).reset_index(drop=True))
    users = load_users()
    save_users(users[users["linked_roll"] != s[ID]])
    log(user, "REMOVE_STUDENT", f"{s[ID]} {s[NAME]}")
    ok(f"{s[NAME]} removed.")


@requires("edit_marks")
def edit_marks(user):
    section("Add / Alter Marks", "✏️")
    df = load_students()
    subs = subjects_of(df)
    idx = pick_student(df)
    if idx is None:
        return
    while True:
        s = df.loc[idx]
        print(f"\n  {c(s[NAME], BOLD + CYAN)} ({s[ID]})")
        for i, sub in enumerate(subs, 1):
            print(f"   {c(str(i), YELLOW)}. {sub:<12}{s[sub]:>4}  {bar(s[sub], width=18)}")
        n = ask("Subject number to change (Enter to finish)", int, 1, len(subs), blank=True)
        if n is None:
            break
        sub = subs[n - 1]
        old = int(s[sub])
        new = ask(f"New marks for {sub} (current {old})", int, 0, 100)
        if new == old:
            print(c("  No change.", DIM))
            continue
        df.loc[idx, sub] = new
        save_students(df)
        log(user, "EDIT_MARKS", f"{s[ID]} {sub}: {old} -> {new}")
        ok(f"{sub}: {old} → {new}")


@requires("add_subject")
def add_subject(user):
    section("Add New Subject", "📚")
    df = load_students()
    subs = subjects_of(df)
    name = ask("New subject name").title()
    if name in df.columns or name.lower() in (m.lower() for m in META):
        err("That column already exists.")
        return
    print(c("  Enter marks for every student:", DIM))
    values = [ask(f"{r[NAME]} ({r[ID]}) – {name}", int, 0, 100) for _, r in df.iterrows()]
    df[name] = values
    df = df[[ID, NAME] + subs + [name, HOURS, ATT]]
    save_students(df)
    log(user, "ADD_SUBJECT", name)
    ok(f"Subject '{name}' added.")


@requires("edit_attendance")
def edit_attendance(user):
    section("Update Attendance / Study Hours", "🗓️")
    df = load_students()
    idx = pick_student(df)
    if idx is None:
        return
    s = df.loc[idx]
    print(f"  {s[NAME]}: attendance {s[ATT]}%  |  study {s[HOURS]} h/day")
    att = ask("New attendance % (Enter to skip)", int, 0, 100, blank=True)
    hrs = ask("New study hours/day (Enter to skip)", float, 0, 24, blank=True)
    if att is not None:
        df.loc[idx, ATT] = att
    if hrs is not None:
        df.loc[idx, HOURS] = hrs
    if att is None and hrs is None:
        print(c("  Nothing changed.", DIM))
        return
    save_students(df)
    log(user, "EDIT_ATTENDANCE", f"{s[ID]} att={att} hours={hrs}")
    ok("Updated.")


@requires("export")
def export_report(user):
    df = load_students()
    d = enrich(df, subjects_of(df))
    path = f"report_{datetime.now():%Y%m%d_%H%M}.csv"
    d.round(2).to_csv(path, index=False)
    log(user, "EXPORT", path)
    ok(f"Ranked report saved → {path}")


@requires("view_self")
def my_report(user):
    section("My Report Card", "📘")
    df = load_students()
    subs = subjects_of(df)
    d = enrich(df, subs)
    me = d[d[ID] == user["linked_roll"]]
    if me.empty:
        err("No student record is linked to your account. Contact the admin.")
        return
    s = me.iloc[0]
    student_card(s, subs, len(d))

    section("You vs Class", "📈")
    print(c(f"  {'Subject':<12}{'You':>5}{'Class':>8}{'Top':>6}   Difference", GRAY + BOLD))
    for sub in subs:
        diff = s[sub] - d[sub].mean()
        col = GREEN if diff >= 0 else RED
        print(f"  {sub:<12}{s[sub]:>5}{d[sub].mean():>8.1f}{d[sub].max():>6}   {c(f'{diff:+.1f}', col + BOLD)}")

    section("Coach Tips", "💡")
    weak = [sub for sub in subs if s[sub] < d[sub].mean()]
    print(f"  🌟 Strongest subject: {c(s['Best'], GREEN + BOLD)}")
    print(f"  🎯 Focus on: {c(', '.join(weak) if weak else 'nothing — you are above class average everywhere!', YELLOW)}")
    if s[ATT] < 75:
        print(c("  ⚠ Attendance is below 75% — risk of shortage.", RED))
    if s[HOURS] < d[HOURS].mean():
        print(c(f"  ⏱ You study {s[HOURS]}h vs class average {d[HOURS].mean():.1f}h.", YELLOW))
    log(user, "VIEW_SELF", s[ID])


def valid_password(pw):
    return len(pw) >= 8 and any(ch.isdigit() for ch in pw) and any(ch.isalpha() for ch in pw)


def change_password(user, forced=False):
    section("Change Password", "🔑")
    if forced:
        print(c("  First login — you must set a new password.", YELLOW))
    cur = secret("  Current password: ")
    u = load_users().query("username == @user['username']").iloc[0]
    if not hmac.compare_digest(hash_pw(cur, u["salt"]), u["pwhash"]):
        err("Current password is wrong.")
        return False
    new = secret("  New password (min 8 chars, letters + digits): ")
    if not valid_password(new):
        err("Password too weak.")
        return False
    if new != secret("  Confirm new password: "):
        err("Passwords do not match.")
        return False
    salt = os.urandom(8).hex()
    update_user(user["username"], salt=salt, pwhash=hash_pw(new, salt), must_change=0)
    log(user, "CHANGE_PASSWORD")
    ok("Password updated.")
    return True


@requires("change_password")
def change_password_screen(user):
    change_password(user)


@requires("manage_users")
def manage_users(user):
    while True:
        clear()
        section("User Management", "👥")
        users = load_users()
        print(c(f"  {'Username':<12}{'Role':<9}{'Linked':<8}{'Failed':>7}  Status", GRAY + BOLD))
        for _, u in users.iterrows():
            status = c("🔒 locked", RED) if u["locked"] else c("active", GREEN)
            print(f"  {u['username']:<12}{c(u['role'].ljust(9), ROLE_COLOR[u['role']])}{u['linked_roll']:<8}{u['failed']:>7}  {status}")
        print(f"\n  {c('1', YELLOW)}. Create admin/HOD account   {c('2', YELLOW)}. Reset password")
        print(f"  {c('3', YELLOW)}. Unlock account             {c('4', YELLOW)}. Delete account")
        print(f"  {c('0', YELLOW)}. Back")
        ch = input(c("\n  ❯ ", MAGENTA + BOLD)).strip()
        if ch == "0":
            return
        if ch == "1":
            uname = ask("New username").lower()
            if (users["username"] == uname).any():
                err("Username already exists.")
            else:
                role = ask("Role (admin/hod)").lower()
                if role not in ("admin", "hod"):
                    err("Role must be admin or hod.")
                else:
                    pw = secret("  Temporary password: ")
                    if valid_password(pw):
                        add_user(make_user(uname, role, pw))
                        log(user, "CREATE_USER", f"{uname} ({role})")
                        ok("Account created (must change password at first login).")
                    else:
                        err("Password too weak (min 8 chars, letters + digits).")
        elif ch in ("2", "3", "4"):
            uname = ask("Username").lower()
            if not (users["username"] == uname).any():
                err("No such user.")
            elif ch == "2":
                pw = secret("  Temporary password: ")
                if valid_password(pw):
                    salt = os.urandom(8).hex()
                    update_user(uname, salt=salt, pwhash=hash_pw(pw, salt), must_change=1, failed=0, locked=0)
                    log(user, "RESET_PASSWORD", uname)
                    ok("Password reset.")
                else:
                    err("Password too weak.")
            elif ch == "3":
                update_user(uname, failed=0, locked=0)
                log(user, "UNLOCK_USER", uname)
                ok("Account unlocked.")
            else:
                target = users[users["username"] == uname].iloc[0]
                admins = (users["role"] == "admin").sum()
                if uname == user["username"]:
                    err("You cannot delete your own account.")
                elif target["role"] == "admin" and admins <= 1:
                    err("Cannot delete the last admin.")
                elif confirm(f"Delete account '{uname}'?"):
                    save_users(users[users["username"] != uname])
                    log(user, "DELETE_USER", uname)
                    ok("Account deleted.")
        pause()


@requires("view_audit")
def view_audit(user):
    section("Audit Log (latest 25)", "🕵️")
    if not os.path.exists(AUDIT_CSV):
        print(c("  No activity yet.", DIM))
        return
    a = pd.read_csv(AUDIT_CSV).fillna("")
    for _, r in a.tail(25).iterrows():
        col = RED if "FAIL" in r["action"] or "DENIED" in r["action"] or "LOCK" in r["action"] else GRAY
        print(f"  {c(r['time'], GRAY)} {r['user']:<9}{r['role']:<8}{c(r['action'].ljust(16), col)}{r['detail']}")
    top = a["action"].value_counts().head(3)
    print(c("\n  Most frequent: " + ", ".join(f"{k} ×{v}" for k, v in top.items()), DIM))


# ───────────────────────── Login ─────────────────────────
ROLE_CHOICES = {"1": "admin", "2": "hod", "3": "student"}


def authenticate(username, pw, role):
    users = load_users()
    m = users[users["username"] == username]
    if m.empty:
        log({"username": username, "role": role}, "LOGIN_FAIL", "unknown user")
        return "bad", None
    u = m.iloc[0]
    if u["locked"] == 1:
        return "locked", None
    good = hmac.compare_digest(hash_pw(pw, u["salt"]), u["pwhash"]) and u["role"] == role
    if good:
        update_user(username, failed=0)
        user = u.to_dict()
        log(user, "LOGIN")
        return "ok", user
    failed = int(u["failed"]) + 1
    locked = 1 if failed >= MAX_ATTEMPTS else 0
    update_user(username, failed=failed, locked=locked)
    log({"username": username, "role": role}, "ACCOUNT_LOCKED" if locked else "LOGIN_FAIL", f"attempt {failed}")
    return ("locked" if locked else "bad"), None


def login():
    while True:
        clear()
        banner()
        print(c("  ╭──────────── LOGIN AS ────────────╮", MAGENTA))
        print(c("  │ ", MAGENTA) + c("1", YELLOW) + "  👑  Admin    " + c("(full access)", DIM) + "       " + c("│", MAGENTA))
        print(c("  │ ", MAGENTA) + c("2", YELLOW) + "  🎓  HOD      " + c("(staff access)", DIM) + "      " + c("│", MAGENTA))
        print(c("  │ ", MAGENTA) + c("3", YELLOW) + "  📘  Student  " + c("(own records)", DIM) + "       " + c("│", MAGENTA))
        print(c("  │ ", MAGENTA) + c("0", YELLOW) + "  🚪  Exit" + " " * 24 + c("│", MAGENTA))
        print(c("  ╰──────────────────────────────────╯", MAGENTA))
        ch = input(c("\n  Select role ❯ ", MAGENTA + BOLD)).strip()
        if ch == "0":
            return None
        if ch not in ROLE_CHOICES:
            continue
        role = ROLE_CHOICES[ch]
        print(c(f"\n  {ROLE_ICON[role]}  {role.upper()} LOGIN", ROLE_COLOR[role] + BOLD))
        for attempt in range(MAX_ATTEMPTS):
            username = ask("Username").lower()
            pw = secret("  Password: ")
            status, user = authenticate(username, pw, role)
            if status == "ok":
                if user["must_change"] == 1:
                    while not change_password(user, forced=True):
                        pass
                ok(f"Welcome, {user['username']}!")
                time.sleep(0.6)
                return user
            if status == "locked":
                err("Account locked after too many failed attempts. Ask the admin to unlock it.")
                break
            err(f"Invalid credentials ({MAX_ATTEMPTS - attempt - 1} attempts left).")
        pause()


# ───────────────────────── Portal / menu ─────────────────────────
MENU = [
    ("📊 Analytics dashboard", "analytics", analytics_dashboard),
    ("📘 My report card", "view_self", my_report),
    ("🔍 Find student / report card", "view_all", find_student),
    ("➕ Add student", "add_student", add_student),
    ("🗑️  Remove student", "remove_student", remove_student),
    ("✏️  Add / alter marks", "edit_marks", edit_marks),
    ("📚 Add new subject", "add_subject", add_subject),
    ("🗓️  Update attendance & study hours", "edit_attendance", edit_attendance),
    ("💾 Export ranked report (CSV)", "export", export_report),
    ("👥 Manage users", "manage_users", manage_users),
    ("🕵️  View audit log", "view_audit", view_audit),
    ("🔑 Change password", "change_password", change_password_screen),
]


def portal(user):
    role = user["role"]
    items = [m for m in MENU if can(role, m[1])]
    while True:
        clear()
        print(c("  " + "═" * W, ROLE_COLOR[role]))
        print(f"  {ROLE_ICON[role]}  {c(user['username'], BOLD)}   "
              f"{c(f' {role.upper()} ', ROLE_COLOR[role] + BOLD)}   {c(datetime.now().strftime('%d %b %Y %H:%M'), GRAY)}")
        print(c("  " + "═" * W, ROLE_COLOR[role]))
        for i, (label, _, _) in enumerate(items, 1):
            print(f"   {c(f'{i:>2}', YELLOW + BOLD)}  {label}")
        print(f"   {c(' 0', YELLOW + BOLD)}  🚪 Logout")
        ch = input(c("\n  ❯ ", MAGENTA + BOLD)).strip()
        if ch == "0":
            log(user, "LOGOUT")
            return
        if ch.isdigit() and 1 <= int(ch) <= len(items):
            clear()
            items[int(ch) - 1][2](user)
            if items[int(ch) - 1][2] is not manage_users:
                pause()


def main():
    bootstrap()
    while True:
        user = login()
        if user is None:
            print(c("\n  Keep grinding. Data doesn't lie. ✨\n", CYAN + BOLD))
            return
        portal(user)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(c("\n\n  Bye! 👋\n", CYAN))