#!/usr/bin/env python3
"""
Email a weekly list of deeply discounted Steam games with strong user reviews.

Configuration is read from environment variables so credentials do not need to
be stored in this file. See README_STEAM_DEALS_EMAIL.md for setup examples.
"""

from __future__ import annotations

import html
import json
import os
import re
import smtplib
import ssl
import sys
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


STEAM_SEARCH_URL = "https://store.steampowered.com/search/results/"
REVIEW_LABELS = {
    "Overwhelmingly Positive": "好评如潮",
    "Very Positive": "特别好评",
}


@dataclass(frozen=True)
class Deal:
    title: str
    url: str
    discount: int
    final_price: str
    original_price: str
    review_label: str
    review_percent: int | None
    review_count: int | None


def env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value or ""


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, got {raw!r}") from exc


def fetch_json(url: str) -> dict:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 steam-weekly-deals-email/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset))


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def parse_review_tooltip(row_html: str) -> tuple[str, int | None, int | None] | None:
    match = re.search(r'data-tooltip-html="([^"]+)"', row_html)
    if not match:
        return None

    tooltip = html.unescape(match.group(1))
    label = tooltip.split("<br>", 1)[0].strip()
    if label not in REVIEW_LABELS:
        return None

    percent_match = re.search(r"(\d+)%", tooltip)
    count_match = re.search(r"([\d,]+)\s+user reviews", tooltip)
    percent = int(percent_match.group(1)) if percent_match else None
    count = int(count_match.group(1).replace(",", "")) if count_match else None
    return label, percent, count


def parse_price(row_html: str, class_name: str) -> str:
    match = re.search(
        rf'<div[^>]*class="[^"]*\b{re.escape(class_name)}\b[^"]*"[^>]*>(.*?)</div>',
        row_html,
        flags=re.DOTALL,
    )
    return strip_tags(match.group(1)) if match else ""


def parse_deals(results_html: str) -> list[Deal]:
    rows = re.findall(
        r'(<a[^>]+class="[^"]*\bsearch_result_row\b[^"]*"[\s\S]*?</a>)',
        results_html,
    )
    deals: list[Deal] = []

    for row in rows:
        discount_match = re.search(r'<div[^>]*class="[^"]*\bdiscount_pct\b[^"]*"[^>]*>\s*-(\d+)%', row)
        if not discount_match:
            continue

        review = parse_review_tooltip(row)
        if not review:
            continue

        title_match = re.search(r'<span[^>]*class="[^"]*\btitle\b[^"]*"[^>]*>(.*?)</span>', row, re.DOTALL)
        url_match = re.search(r'href="([^"]+)"', row)
        if not title_match or not url_match:
            continue

        review_label, review_percent, review_count = review
        deals.append(
            Deal(
                title=strip_tags(title_match.group(1)),
                url=html.unescape(url_match.group(1)).split("?", 1)[0],
                discount=int(discount_match.group(1)),
                original_price=parse_price(row, "discount_original_price"),
                final_price=parse_price(row, "discount_final_price"),
                review_label=review_label,
                review_percent=review_percent,
                review_count=review_count,
            )
        )

    return deals


def fetch_steam_deals(max_pages: int, page_size: int, country_code: str, language: str) -> list[Deal]:
    all_deals: list[Deal] = []
    for page in range(max_pages):
        query = urlencode(
            {
                "query": "",
                "start": page * page_size,
                "count": page_size,
                "dynamic_data": "",
                "sort_by": "_ASC",
                "specials": "1",
                "hidef2p": "1",
                "ndl": "1",
                "cc": country_code,
                "l": language,
                "infinite": "1",
            }
        )
        payload = fetch_json(f"{STEAM_SEARCH_URL}?{query}")
        all_deals.extend(parse_deals(payload.get("results_html", "")))

        total = int(payload.get("total_count") or 0)
        if (page + 1) * page_size >= total:
            break

    unique: dict[str, Deal] = {}
    for deal in all_deals:
        unique.setdefault(deal.url, deal)
    return sorted(unique.values(), key=lambda item: (-item.discount, item.title.lower()))


def filter_deals(deals: Iterable[Deal], min_discount: int, min_reviews: int, limit: int) -> list[Deal]:
    filtered = [
        deal
        for deal in deals
        if deal.discount >= min_discount and (deal.review_count is None or deal.review_count >= min_reviews)
    ]
    return filtered[:limit]


def review_summary(deal: Deal) -> str:
    zh_label = REVIEW_LABELS[deal.review_label]
    review_bits = [f"{zh_label} / {deal.review_label}"]
    if deal.review_percent is not None:
        review_bits.append(f"{deal.review_percent}% positive")
    if deal.review_count is not None:
        review_bits.append(f"{deal.review_count:,} reviews")
    return ", ".join(review_bits)


def render_text_email(deals: list[Deal], min_discount: int, min_reviews: int) -> str:
    lines = [
        "Steam weekly deals",
        "",
        f"Filters: discount >= {min_discount}%, reviews >= {min_reviews}, rating is Very Positive or Overwhelmingly Positive.",
        "",
    ]

    if not deals:
        lines.append("No matching deals found this week.")
        return "\n".join(lines).strip() + "\n"

    for index, deal in enumerate(deals, start=1):
        lines.extend(
            [
                f"{index}. {deal.title}",
                f"   Discount: -{deal.discount}%",
                f"   Price: {deal.original_price or '?'} -> {deal.final_price or '?'}",
                f"   Reviews: {review_summary(deal)}",
                f"   Open on Steam: {deal.url}",
                "",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def render_html_email(deals: list[Deal], min_discount: int, min_reviews: int) -> str:
    if not deals:
        body = """
          <div class="empty">
            <h2>No matching deals found this week</h2>
            <p>Try lowering the minimum discount or review-count filter.</p>
          </div>
        """
    else:
        cards = []
        for index, deal in enumerate(deals, start=1):
            title = html.escape(deal.title)
            url = html.escape(deal.url, quote=True)
            original_price = html.escape(deal.original_price or "?")
            final_price = html.escape(deal.final_price or "?")
            reviews = html.escape(review_summary(deal))
            cards.append(
                f"""
                <tr>
                  <td class="rank">#{index}</td>
                  <td class="content">
                    <a class="title" href="{url}">{title}</a>
                    <div class="deal-row">
                      <span class="discount">-{deal.discount}%</span>
                      <span class="price">{final_price}</span>
                      <span class="original">{original_price}</span>
                    </div>
                    <div class="reviews">{reviews}</div>
                  </td>
                  <td class="action">
                    <a class="button" href="{url}">View</a>
                  </td>
                </tr>
                """
            )
        body = f"""
          <table class="deals" role="presentation" cellspacing="0" cellpadding="0">
            {''.join(cards)}
          </table>
        """

    return f"""\
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <style>
      body {{
        margin: 0;
        padding: 0;
        background: #f3f4f6;
        color: #111827;
        font-family: Arial, Helvetica, sans-serif;
      }}
      .wrap {{
        max-width: 760px;
        margin: 0 auto;
        padding: 28px 16px;
      }}
      .header {{
        background: #111827;
        color: #ffffff;
        padding: 24px;
        border-radius: 8px 8px 0 0;
      }}
      h1 {{
        margin: 0 0 8px;
        font-size: 26px;
        line-height: 1.2;
      }}
      .subtitle {{
        margin: 0;
        color: #d1d5db;
        font-size: 14px;
        line-height: 1.5;
      }}
      .deals {{
        width: 100%;
        background: #ffffff;
        border-collapse: collapse;
        border-radius: 0 0 8px 8px;
        overflow: hidden;
      }}
      .deals tr {{
        border-bottom: 1px solid #e5e7eb;
      }}
      .deals tr:last-child {{
        border-bottom: 0;
      }}
      .rank {{
        width: 52px;
        padding: 20px 12px 20px 20px;
        color: #6b7280;
        font-weight: 700;
        vertical-align: top;
      }}
      .content {{
        padding: 18px 8px;
        vertical-align: top;
      }}
      .title {{
        color: #111827;
        font-size: 20px;
        font-weight: 800;
        line-height: 1.25;
        text-decoration: none;
      }}
      .deal-row {{
        margin-top: 10px;
      }}
      .discount {{
        display: inline-block;
        background: #16a34a;
        color: #ffffff;
        padding: 5px 9px;
        border-radius: 6px;
        font-size: 16px;
        font-weight: 800;
      }}
      .price {{
        display: inline-block;
        margin-left: 10px;
        color: #dc2626;
        font-size: 22px;
        font-weight: 900;
      }}
      .original {{
        display: inline-block;
        margin-left: 8px;
        color: #6b7280;
        font-size: 14px;
        text-decoration: line-through;
      }}
      .reviews {{
        margin-top: 9px;
        color: #4b5563;
        font-size: 14px;
        line-height: 1.4;
      }}
      .action {{
        width: 82px;
        padding: 20px 20px 20px 8px;
        text-align: right;
        vertical-align: top;
      }}
      .button {{
        display: inline-block;
        background: #2563eb;
        color: #ffffff;
        padding: 9px 14px;
        border-radius: 6px;
        font-size: 14px;
        font-weight: 700;
        text-decoration: none;
      }}
      .empty {{
        background: #ffffff;
        padding: 24px;
        border-radius: 0 0 8px 8px;
      }}
      .empty h2 {{
        margin: 0 0 8px;
        font-size: 20px;
      }}
      .empty p {{
        margin: 0;
        color: #4b5563;
      }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="header">
        <h1>Steam Weekly Deals</h1>
        <p class="subtitle">Discount >= {min_discount}% · Reviews >= {min_reviews} · Very Positive or Overwhelmingly Positive</p>
      </div>
      {body}
    </div>
  </body>
</html>
"""


def render_email(deals: list[Deal], min_discount: int, min_reviews: int) -> tuple[str, str, str]:
    subject = f"Steam weekly deals: {len(deals)} highly rated games"
    return subject, render_text_email(deals, min_discount, min_reviews), render_html_email(deals, min_discount, min_reviews)


def send_email(subject: str, text_body: str, html_body: str) -> None:
    smtp_host = env("SMTP_HOST", required=True)
    smtp_port = env_int("SMTP_PORT", 587)
    smtp_user = env("SMTP_USER", required=True)
    smtp_password = env("SMTP_PASSWORD", required=True)
    mail_from = env("MAIL_FROM", smtp_user)
    mail_to = env("MAIL_TO", required=True)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = mail_from
    message["To"] = mail_to
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    if smtp_port == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
            server.login(smtp_user, smtp_password)
            server.send_message(message)
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(smtp_user, smtp_password)
            server.send_message(message)


def main() -> int:
    max_pages = env_int("STEAM_MAX_PAGES", 8)
    page_size = env_int("STEAM_PAGE_SIZE", 50)
    min_discount = env_int("STEAM_MIN_DISCOUNT", 50)
    min_reviews = env_int("STEAM_MIN_REVIEWS", 500)
    limit = env_int("STEAM_DEAL_LIMIT", 25)
    country_code = env("STEAM_COUNTRY", "US")
    language = env("STEAM_LANGUAGE", "english")
    dry_run = env("DRY_RUN", "0") == "1"

    deals = fetch_steam_deals(max_pages, page_size, country_code, language)
    selected = filter_deals(deals, min_discount, min_reviews, limit)
    subject, text_body, html_body = render_email(selected, min_discount, min_reviews)

    if dry_run:
        print(f"Subject: {subject}\n")
        print(text_body)
        return 0

    send_email(subject, text_body, html_body)
    print(f"Sent {len(selected)} Steam deals.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"steam_weekly_deals_email.py failed: {exc}", file=sys.stderr)
        raise
