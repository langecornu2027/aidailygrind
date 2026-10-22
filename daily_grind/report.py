"""Weekly analytics report: a dashboard email built from Google Analytics 4.

    python -m daily_grind.report              print a summary
    python -m daily_grind.report --html F     also write the HTML report to file F
    python -m daily_grind.report --email      email it to CONTACT_EMAIL

Runs every Monday in GitHub Actions (.github/workflows/weekly-report.yml). Google access
uses Workload Identity Federation: GitHub gets a short-lived pass, no key is stored.
"""

import argparse
import html
import json
import os
import smtplib
from datetime import date, timedelta
from email.message import EmailMessage

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Filter, FilterExpression, Metric, OrderBy, RunReportRequest,
)

from . import render

PROPERTY = "properties/560249343"
DAYS = 7


def period(offset_days: int = 0) -> DateRange:
    end = date.today() - timedelta(days=1 + offset_days)
    start = end - timedelta(days=DAYS - 1)
    return DateRange(start_date=start.isoformat(), end_date=end.isoformat())


class GA:
    def __init__(self):
        self.client = BetaAnalyticsDataClient()

    def rows(self, dims, metrics, limit=10, where=None, order_metric=True, ranges=None):
        req = RunReportRequest(
            property=PROPERTY,
            dimensions=[Dimension(name=d) for d in dims],
            metrics=[Metric(name=m) for m in metrics],
            date_ranges=ranges or [period()],
            dimension_filter=where,
            limit=limit,
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name=metrics[0]), desc=True)]
            if order_metric else [OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name=dims[0]))],
        )
        try:
            resp = self.client.run_report(req)
        except Exception as exc:  # e.g. a custom dimension with no data yet
            print(f"  (skipped {dims}: {type(exc).__name__})")
            return []
        return [([d.value for d in r.dimension_values], [float(m.value or 0) for m in r.metric_values])
                for r in resp.rows]

    def totals(self, metrics, offset_days=0):
        rows = self.rows([], metrics, limit=1, ranges=[period(offset_days)], order_metric=True) if metrics else []
        return rows[0][1] if rows else [0.0] * len(metrics)


def event_is(name: str) -> FilterExpression:
    return FilterExpression(filter=Filter(field_name="eventName",
                                          string_filter=Filter.StringFilter(value=name)))


def path_contains(text: str) -> FilterExpression:
    return FilterExpression(filter=Filter(field_name="pagePath", string_filter=Filter.StringFilter(
        value=text, match_type=Filter.StringFilter.MatchType.CONTAINS)))


def token_titles() -> dict[str, str]:
    """Page path -> title, from the saved editions."""
    titles = {}
    for e in render.load_editions():
        titles[f"/{e['date']}.html"] = f"Edition: {e['headline']}"
        for n, t in enumerate(e["tokens"], start=1):
            titles[f"/{e['date']}-token-{n}.html"] = f"#{n} {t['title']}"
    return titles


def collect() -> dict:
    ga = GA()
    kpi_names = ["activeUsers", "sessions", "screenPageViews", "userEngagementDuration", "newUsers"]
    now = ga.totals(kpi_names)
    before = ga.totals(kpi_names, offset_days=DAYS)
    titles = token_titles()

    def label(path):
        return titles.get(path, path)

    return {
        "range": f"{period().start_date} → {period().end_date}",
        "kpis": [
            ("Readers", now[0], before[0], ""),
            ("Visits", now[1], before[1], ""),
            ("Page views", now[2], before[2], ""),
            ("Avg reading time", now[3] / now[0] if now[0] else 0, before[3] / before[0] if before[0] else 0, "s"),
            ("New readers", now[4], before[4], ""),
        ],
        "daily": ga.rows(["date"], ["activeUsers"], limit=31, order_metric=False),
        "tokens": [([label(p)], m) for (p,), m in ga.rows(["pagePath"], ["screenPageViews"], 10,
                                                           path_contains("-token-"))],
        "editions": [([label(p)], m) for (p,), m in ga.rows(["pagePath"], ["screenPageViews"], 10)
                     if p == "/" or (p.endswith(".html") and "-token-" not in p and p[1:5].isdigit())],
        "topics": ga.rows(["customEvent:token_tag"], ["screenPageViews"], 10,
                          FilterExpression(not_expression=FilterExpression(filter=Filter(
                              field_name="customEvent:token_tag",
                              string_filter=Filter.StringFilter(value="(not set)"))))),
        "sources": ga.rows(["sessionSource", "sessionMedium"], ["sessions"], 10),
        "listens": ga.rows(["eventName", "customEvent:voice"], ["eventCount"], 10,
                           FilterExpression(filter=Filter(field_name="eventName", string_filter=Filter.StringFilter(
                               value="listen_", match_type=Filter.StringFilter.MatchType.BEGINS_WITH)))),
        "shares": ga.rows(["customEvent:method"], ["eventCount"], 10, event_is("share")),
        "signups": {name: (ga.rows(["eventName"], ["eventCount"], 1, event_is(name)) or [([name], [0])])[0][1][0]
                    for name in ("sign_up", "subscribe_confirmed")},
        "countries": ga.rows(["country"], ["activeUsers"], 8),
        "devices": ga.rows(["deviceCategory"], ["activeUsers"], 5),
    }


# ---------- HTML (email-safe: tables and inline styles) ----------

AMBER, CYAN, INK, MUTED, LINE = "#b5652b", "#0f766e", "#1d232b", "#6b7785", "#e6e8eb"


def fmt(value: float, unit: str = "") -> str:
    if unit == "s":
        return f"{int(value // 60)}m {int(value % 60):02d}s"
    return f"{int(round(value)):,}"


def change(now: float, before: float) -> str:
    if not before:
        return '<span style="color:#6b7785">new</span>' if now else ""
    pct = (now - before) / before * 100
    color = "#15803d" if pct >= 0 else "#b91c1c"
    return f'<span style="color:{color}">{"▲" if pct >= 0 else "▼"} {abs(pct):.0f}%</span>'


def bars(rows, title, unit="", empty="No data yet."):
    if not rows:
        return section(title, f'<p style="color:{MUTED};margin:0">{empty}</p>')
    top = max(m[0] for _, m in rows) or 1
    lines = []
    for dims, m in rows:
        name = html.escape(" · ".join(d for d in dims if d and d != "(not set)") or "(other)")
        width = max(2, int(m[0] / top * 100))
        lines.append(
            f'<tr><td style="padding:4px 8px 4px 0;font-size:13px;color:{INK};width:55%">{name}</td>'
            f'<td style="padding:4px 0;width:35%"><div style="background:{AMBER};height:10px;border-radius:5px;'
            f'width:{width}%"></div></td>'
            f'<td style="padding:4px 0 4px 8px;font-size:13px;text-align:right;color:{INK}">{fmt(m[0], unit)}</td></tr>')
    return section(title, f'<table width="100%" cellpadding="0" cellspacing="0">{"".join(lines)}</table>')


def section(title, body):
    return (f'<tr><td style="padding:18px 20px;border-top:1px solid {LINE}">'
            f'<div style="font-size:12px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;'
            f'color:{CYAN};margin-bottom:10px">{title}</div>{body}</td></tr>')


def build_html(d: dict) -> str:
    kpi_cells = "".join(
        f'<td style="padding:10px;text-align:center;border:1px solid {LINE};border-radius:8px">'
        f'<div style="font-size:11px;color:{MUTED};text-transform:uppercase">{name}</div>'
        f'<div style="font-size:22px;font-weight:bold;color:{INK};margin:4px 0">{fmt(now, unit)}</div>'
        f'<div style="font-size:12px">{change(now, before)}</div></td>'
        for name, now, before, unit in d["kpis"])
    daily = [([date.fromisoformat(f"{r[0][0][:4]}-{r[0][0][4:6]}-{r[0][0][6:]}").strftime("%a %b %-d")], r[1])
             for r in d["daily"]]
    listens = [([("Started" if n == "listen_start" else "Finished" if n == "listen_complete" else "Fell back"),
                 "AI voice" if v == "ai" else "Browser voice" if v == "browser" else v], m)
               for (n, v), m in d["listens"]]
    signups = (f'<p style="margin:0;font-size:14px;color:{INK}">Sign-up forms sent: '
               f'<b>{fmt(d["signups"]["sign_up"])}</b> · Confirmed: <b>{fmt(d["signups"]["subscribe_confirmed"])}</b></p>'
               f'<p style="margin:6px 0 0;font-size:12px;color:{MUTED}">Only visitors who accepted cookies are counted.</p>')
    body = "".join([
        section("This week at a glance", f'<table width="100%" cellpadding="0" cellspacing="6"><tr>{kpi_cells}</tr></table>'),
        bars(daily, "Readers per day"),
        bars(d["tokens"], "Top Morning Tokens (views)"),
        bars(d["editions"], "Editions read (views)"),
        bars(d["topics"], "Topics readers like (views by tag)"),
        bars([([f"{s} / {m}"], v) for (s, m), v in d["sources"]], "Where readers come from (visits)"),
        bars(listens, "Listening"),
        bars(d["shares"], "Shares by network"),
        section("Newsletter", signups),
        bars(d["countries"], "Countries (readers)"),
        bars(d["devices"], "Devices (readers)"),
    ])
    return f"""<!doctype html><html><body style="margin:0;background:#f4f5f7;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7"><tr><td align="center" style="padding:24px 12px">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:#fff;border-radius:14px;overflow:hidden">
<tr><td style="background:#07090c;padding:22px 20px">
<div style="color:#ffb454;font-size:12px;letter-spacing:1px;font-family:monospace">AI DAILY GRIND · WEEKLY REPORT</div>
<div style="color:#fff;font-size:22px;font-weight:bold;margin-top:6px">Your week in numbers ☕</div>
<div style="color:#8592a0;font-size:13px;margin-top:4px">{html.escape(d["range"])} · compared with the 7 days before</div>
</td></tr>
{body}
<tr><td style="padding:16px 20px;border-top:1px solid {LINE};font-size:12px;color:{MUTED}">
Full details: <a href="https://analytics.google.com/analytics/web/#/p560249343/reports/intelligenthome" style="color:{AMBER}">Google Analytics</a>.
Numbers include only visitors who accepted cookies.</td></tr>
</table></td></tr></table></body></html>"""


def summary(d: dict) -> str:
    lines = [f"AI Daily Grind · {d['range']}"]
    for name, now, before, unit in d["kpis"]:
        lines.append(f"  {name}: {fmt(now, unit)} (before: {fmt(before, unit)})")
    for key in ("tokens", "sources", "shares", "listens"):
        lines.append(f"  {key}: " + ", ".join(f"{' · '.join(dims)}={fmt(m[0])}" for dims, m in d[key][:5]))
    return "\n".join(lines)


def send(html_body: str, text: str, subject: str) -> None:
    msg = EmailMessage()
    msg["From"] = "The AI Daily Grind <welcome@aidailygrind.com>"
    msg["To"] = render.CONTACT_EMAIL
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP_SSL("smtp.mx.cloudflare.net", 465, timeout=30) as server:
        server.login("api_token", os.environ["CLOUDFLARE_API_TOKEN"])
        server.send_message(msg)


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly Google Analytics report.")
    parser.add_argument("--html")
    parser.add_argument("--email", action="store_true")
    args = parser.parse_args()

    data = collect()
    text = summary(data)
    print(text)
    page = build_html(data)
    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(page)
    if args.email:
        send(page, text, f"☕ AI Daily Grind · weekly report · {data['range']}")
        print(f"emailed to {render.CONTACT_EMAIL}")


if __name__ == "__main__":
    main()
