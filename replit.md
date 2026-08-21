# Guardian Bot — Group Protection + AI Commerce System

## Project Overview

A production-grade Telegram bot combining group moderation/protection with a full Self-Optimizing AI Commerce System (store). Built with Python 3.11+, python-telegram-bot v22+, PostgreSQL, Redis, and Celery.

## Architecture

```
Guardian Bot
├── Group Protection System (existing)
│   ├── 11-layer security pipeline
│   ├── AI moderation (toxicity, NSFW)
│   ├── Anti-raid, CAPTCHA, flood detection
│   └── Admin management suite
├── Game System (existing)
│   ├── 8 text-based games (Mafia, Chameleon, etc.)
│   └── 10+ Mini App games
└── Commerce System (NEW — src/shop/)
    ├── User Engine (XP, levels, VIP tiers)
    ├── Service Engine (catalog, dynamic pricing)
    ├── Order Engine (lifecycle, queue, SLA)
    ├── Wallet Engine (double-entry ledger)
    ├── Coupon Engine (advanced rules)
    ├── Affiliate Engine (referral + commissions)
    ├── AI Engine (recommendations, fraud detection)
    ├── Support Engine (tickets + SLA)
    ├── Notification Engine
    └── Admin Panel (full control)
```

## Running the Bot

1. Copy `.env.example` to `.env` and fill in values
2. Ensure PostgreSQL and Redis are running
3. Run: `uv run python main.py`

## User Commands (Shop)

| Command | Description |
|---------|-------------|
| `/start` | Welcome + referral handling |
| `/shop` | Open the store main menu |

## Admin Commands (Shop)

| Command | Description |
|---------|-------------|
| `/shop_dashboard` | Revenue & analytics overview |
| `/shop_orders` | Recent orders list |
| `/shop_order <ref>` | Order details + actions |
| `/shop_user <tid>` | User profile + fraud score |
| `/shop_addbalance <tid> <amount>` | Add balance to user |
| `/shop_services` | List all services |
| `/shop_addservice <cat_id> <price> <type> <name EN> \| <name AR>` | Add service |
| `/shop_addcat <icon> <name EN> \| <name AR>` | Add category |
| `/shop_coupons` | List coupons |
| `/shop_addcoupon <code> <discount%> [limit] [min_order]` | Create coupon |
| `/shop_tickets` | Open support tickets |
| `/shop_ticket <ref> [reply]` | View/reply to ticket |
| `/shop_broadcast <message>` | Flash sale broadcast |

## Commerce System Features

### User System
- XP leveling: Bronze → Silver → Gold → Elite
- VIP tiers: Basic (5%) → Pro (10%) → Elite (20% discount)
- Auto-upgrade based on total spending
- Referral codes with lifetime commissions

### Dynamic Pricing
- Demand-based surge pricing
- Low stock premium
- Time-of-day discounts (off-peak 5% off)
- User level/VIP discounts

### Order Lifecycle
`CREATED → VALIDATED → PAID → PROCESSING → COMPLETED`
- Auto-retry system (3 attempts)
- SLA tracking (60/120/240 min by VIP tier)
- Priority queue (VIP gets faster processing)

### Wallet
- Double-entry accounting
- Anti-fraud checks (daily limits, velocity)
- Balance locking during active orders

### Affiliate System
- First purchase: 5% commission
- Lifetime recurring: 2% commission
- Anti-fraud flagging

### AI Features
- Collaborative filtering recommendations
- Co-purchase upsell suggestions
- Behavioral fraud scoring (0-100)
- Revenue insights dashboard

## Environment Variables

See `.env.example` for full list. Key additions for shop:
- All shop settings use existing DB/Redis infrastructure
- No additional environment variables required

## Tech Stack

- **Language:** Python 3.11+
- **Framework:** python-telegram-bot v22.7+
- **Database:** PostgreSQL (SQLAlchemy async + asyncpg)
- **Cache:** Redis
- **Tasks:** Celery
- **Package Manager:** uv

## User Preferences

- Arabic-first UI in the bot (bilingual where needed)
- Modular file structure — each engine in its own file
- No external payment gateway (wallet system is internal)
- All new shop modules go under `src/shop/`
