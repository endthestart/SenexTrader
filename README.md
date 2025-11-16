# Senex Trader

**Automated Options Trading System**

Multi-strategy trading platform with intelligent strategy selection, real-time market data streaming, and order execution via TastyTrade API.


---

## Core Features

### Trading Engine
- **14 Automated Strategies**: Vertical spreads (4), Iron condors (2), Butterflies (2), Straddles/Strangles (4), Senex Trident (2)
- **Intelligent Selection**: Auto mode with market condition scoring and strategy comparison
- **Daily Automation**: Scheduled execution via Celery Beat at 10 AM ET
- **Order Management**: Complete execution workflow with profit targets and cancellation support

### Real-Time Data
- **Live Streaming**: DXLinkStreamer integration for quotes, Greeks, and account data
- **WebSocket Communication**: Real-time updates for positions, orders, and market conditions
- **Smart Caching**: 5-second cache for Greeks, 5-minute TTL for option chains

### Risk Management
- **Position Sizing**: Automated capital allocation based on account size
- **Greeks Calculations**: Portfolio and position-level Greeks with health scoring
- **Market Validation**: Bollinger Bands, ATR, trend analysis for strategy selection

### Security & Authentication
- **OAuth Integration**: Complete TastyTrade OAuth flow with token refresh
- **Encrypted Storage**: Django encrypted model fields for sensitive data
- **Session-Based Auth**: Secure user authentication without JWT complexity

---

## Technology Stack

**Backend**: Python 3.12, Django 5.2
**Database**: SQLite (dev), PostgreSQL (prod)
**Async**: Celery + Redis, Django Channels
**Trading API**: TastyTrade SDK 10.3
**Testing**: pytest
**Code Quality**: ruff, black, mypy, bandit

---

## Quick Start

### Prerequisites
- Python 3.12+
- Podman and podman-compose (for Redis container)
- TastyTrade account (for OAuth authentication)

### Installation

1. **Clone the repository**
   ```bash
   git clone <senextrader-url> senextrader
   cd senextrader
   ```

2. **Install Podman and podman-compose** (if not already installed)
   ```bash
   # Fedora/RHEL
   sudo dnf install podman podman-compose
   
   # Ubuntu/Debian
   sudo apt-get install podman podman-compose
   ```

3. **Set up Redis with Podman**
   ```bash
   # Start Redis container using the development docker-compose file
   cd docker
   podman-compose -f docker-compose.dev.yml up -d
   cd ..
   ```

4. **Create virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # bash/zsh
   # OR for fish shell:
   source .venv/bin/activate.fish
   ```

5. **Install dependencies**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

6. **Create .env file**
   ```bash
   cp .env.example .env
   ```

7. **Generate encryption key and update .env**
   
   Generate `FIELD_ENCRYPTION_KEY`:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   
   Copy the output and add to `.env`:
   ```bash
   FIELD_ENCRYPTION_KEY=<paste-generated-key-here>
   ```
   
   **Optional**: If developing remotely (over SSH), also set:
   ```bash
   ALLOWED_HOSTS=localhost,127.0.0.1,your-remote-host
   WS_ALLOWED_ORIGINS=http://localhost:8000,http://your-remote-host:8000
   ```

8. **Run database migrations**
   ```bash
   python manage.py migrate
   ```

9. **Create superuser (optional, for admin access)**
   ```bash
   python manage.py createsuperuser
   ```

### Running the Application

```bash
# Terminal 1: Django development server
python manage.py runserver

# Terminal 2: Celery worker + beat (convenience script)
./run_celery.sh  # Runs both worker and beat, cleans stale schedule files

# Alternative: Run Celery manually
# Terminal 2: celery -A senextrader worker -l info
# Terminal 3: celery -A senextrader beat -l info
```

**Note**: Redis should already be running from step 3. If you need to restart it:
```bash
cd docker
podman-compose -f docker-compose.dev.yml restart
```

### Initial Configuration

1. Access admin at `http://localhost:8000/admin`
2. Navigate to Settings → Brokerage
3. Complete TastyTrade OAuth authentication
4. Configure risk tolerance and strategy preferences
5. Enable automated trading (optional)

---

## Project Structure

```
senextrader/
├── accounts/           # User auth, broker OAuth, account settings
├── trading/            # Trading logic, positions, orders
├── streaming/          # Real-time WebSocket consumers
├── services/           # Business logic layer (ALL logic here)
│   ├── *_strategy.py   # 14 strategy implementations
│   ├── strategy_selector.py
│   ├── strategy_registry.py
│   ├── greeks_service.py
│   ├── market_analysis.py
│   ├── option_chain_service.py
│   └── execution/      # Order placement and management
├── templates/          # Dark theme UI
└── static/             # Frontend assets (UI only, no business logic)
```

**Available Strategies:**
- Vertical Spreads: Bull Put, Bear Call, Bull Call, Bear Put
- Iron Condors: Long, Short
- Butterflies: Iron Butterfly
- Straddles/Strangles: Long Straddle, Long Strangle
- Advanced: Senex Trident, Calendar Spread, Call Backspread
- Basic: Cash Secured Put, Covered Call

---

## Development

### Code Quality
```bash
# Format code
black .

# Lint and auto-fix
ruff check --fix .

# Type check
mypy .

# Security scan
bandit -r . -ll

# Run tests
pytest

# Run tests with coverage report
pytest  # Coverage report automatically generated (terminal + HTML)
# HTML report: htmlcov/index.html
```

### Development Dry-Run Mode

**Dry-Run Mode** enables safe development and testing without real API calls or database writes.

#### What It Does
- **Calls TastyTrade API** with `dry_run=True` parameter for validation
- **Gets real buying power impact** and fee calculations from TastyTrade
- **Skips database writes** (no Position/Trade records created)
- **Returns DryRunResult** with order validation and simulated details
- **Perfect for testing** strategy logic end-to-end with real TastyTrade validation

#### Usage

**Enabled by default in development** (defined in `settings/development.py`):
```python
TASTYTRADE_DRY_RUN = True  # Default in development
```

**Disable dry-run in development** (for real sandbox testing):
```bash
# In your .env file
TASTYTRADE_DRY_RUN=False
```

**Production** (automatically enforced in `settings/production.py`):
```python
TASTYTRADE_DRY_RUN = False  # Hardcoded - attempts to enable will raise ValueError
```

#### Expected Behavior
- ✅ All validation logic runs normally
- ✅ Strategy selection and market analysis execute
- ✅ TastyTrade API validates order via `/orders/dry-run` endpoint
- ✅ Returns buying power impact and fee calculations from TastyTrade
- ✅ Order gets `order.id = -1` (TastyTrade sentinel for dry-run)
- ❌ Order is NOT queued or executed by TastyTrade
- ❌ No database records created (Position/Trade models)
- ℹ️ Returns `DryRunResult` dataclass with validation results

#### Re-running Real Executions
After testing in dry-run mode:
1. Set `TASTYTRADE_DRY_RUN=False` in `.env`
2. Restart Django server
3. Execute trades normally - full API calls and database persistence

⚠️ Dry-run mode cannot be enabled in production (raises `ValueError` on startup).

### Key Conventions
- **Simplicity First**: Choose the simplest solution that works
- **DRY Principle**: Search existing code before writing new
- **Service Layer**: All business logic in `services/`, never in frontend
- **Dark Theme**: All UI follows dark theme variables
- **Session Auth**: No JWT, session-based authentication only

---

## Documentation

**In-Repo Documentation:**
- `docs/` directory
- AI Configuration: `AGENTS.md`, `CLAUDE.md`, `AI.md` (in `.claude/` directory)

---

## Contributing

1. **Environment Setup**: Follow the Installation section to set up your development environment
2. **AI Guidelines**: Read `AGENTS.md` / `CLAUDE.md` for development patterns
3. **Code Quality**: Run linting/formatting tools before commits
   ```bash
   ruff check --fix .
   black .
   pytest
   ```
4. **Pre-Implementation Checks**:
   - Search existing code before writing new (`/pre-impl <feature>`)
   - Verify TastyTrade SDK usage (`/tt-check <function>`)
5. **Testing**: Write tests for new features (maintain 100% pass rate)
6. **Documentation**: Update README and code comments as needed

---

## License

[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)

This project is licensed under the **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License**.

- ✅ **Free** for personal, educational, and research use
- ❌ **Commercial use prohibited** without explicit permission
- 📋 **Attribution required** - Give appropriate credit
- 🔄 **Share-Alike** - Derivatives must use the same license

See the [LICENSE](LICENSE) file for full details.

For commercial licensing inquiries, please contact the project maintainers.

---

## Support

- **Issues**: GitHub Issues
- **Questions**: Open a discussion
- **Development**: See Contributing section above

---

**Built with Django, powered by TastyTrade API**
