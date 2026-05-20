# Steam Weekly Deals Email

This script emails a weekly list of discounted Steam games whose review label is
`Overwhelmingly Positive` or `Very Positive` (`好评如潮` / `特别好评`).

It uses only Python's standard library.

## 1. Configure Email

Set these environment variables:

```sh
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USER="your_email@gmail.com"
export SMTP_PASSWORD="your_app_password"
export MAIL_TO="your_email@gmail.com"
export MAIL_FROM="your_email@gmail.com"
```

For Gmail, use an app password rather than your normal account password.

Optional filters:

```sh
export STEAM_MIN_DISCOUNT="50"
export STEAM_MIN_REVIEWS="500"
export STEAM_DEAL_LIMIT="25"
export STEAM_COUNTRY="US"
export STEAM_LANGUAGE="english"
```

## 2. Test Without Sending

```sh
DRY_RUN=1 python3 steam_weekly_deals_email.py
```

## 3. Send Once

```sh
python3 steam_weekly_deals_email.py
```

## 4. Run Weekly With Cron

Open your crontab:

```sh
crontab -e
```

Example: send every Monday at 9:00 AM:

```cron
0 9 * * 1 SMTP_HOST="smtp.gmail.com" SMTP_PORT="587" SMTP_USER="your_email@gmail.com" SMTP_PASSWORD="your_app_password" MAIL_TO="your_email@gmail.com" MAIL_FROM="your_email@gmail.com" /usr/bin/python3 /Users/jerryjiao/Documents/Codex/2026-05-18/give-the-actual-data-of-price/steam_weekly_deals_email.py
```

## 5. Run With GitHub Actions

The repository includes `.github/workflows/steam-deals.yml`. It runs every
5 minutes for testing, and can also be run manually from the GitHub Actions tab.
After testing, change the cron value back to `0 13 * * 1` for a weekly Monday
9:00 AM Eastern schedule during daylight saving time.

Create these repository secrets in GitHub:

```text
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
MAIL_TO=your_email@gmail.com
MAIL_FROM=your_email@gmail.com
```

Go to:

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

For Gmail, use an app password rather than your normal account password.
