# Quality Tools Guide - Ruff-First Approach

**Last Updated**: October 2, 2025
**Status**: Active - Ruff-based quality stack

---

## Quick Reference

### Primary Workflow (Recommended)

```bash
# 1. Format code (opinionated, consistent)
black .

# 2. Lint and auto-fix (primary - handles most issues)
ruff check --fix .

# 3. Type check
mypy .

# 4. Security scan (before production)
bandit -r . -ll

# 5. Run tests
pytest
```

### One-Line Quality Check

```bash
# Run all checks in sequence
black . && ruff check --fix . && mypy . && pytest
```

---

## Tool Details

### 1. Ruff (Primary Linter)

**Purpose**: Fast, comprehensive linting with auto-fix
**Version**: 0.13.2
**Speed**: 10-100x faster than flake8/pylint

**What it replaces:**
- ✅ flake8 (style checking)
- ✅ isort (import sorting)
- ✅ pyupgrade (code modernization)
- ✅ Many flake8 plugins

**Common commands:**
```bash
# Check all files
ruff check .

# Auto-fix issues
ruff check --fix .

# Watch mode (fix on save)
ruff check --watch .

# Only check imports
ruff check --select I .

# Ignore specific rules
ruff check --ignore E501 .
```

**Configuration**: `pyproject.toml` (already configured for Django)

---

### 2. Black (Code Formatting)

**Purpose**: Opinionated code formatting
**Version**: 25.9.0
**Philosophy**: "Any color you want, as long as it's black"

**Common commands:**
```bash
# Format all files
black .

# Check without modifying
black --check .

# Show diffs
black --diff .

# Format specific files
black accounts/ services/
```

**Configuration**: `pyproject.toml` (line-length: 100)

---

### 3. Mypy (Type Checking)

**Purpose**: Static type checking
**Version**: 1.18.2
**Includes**: django-stubs (5.2.5) for Django support

**Common commands:**
```bash
# Type check all files
mypy .

# Check specific module
mypy services/

# Ignore missing imports
mypy --ignore-missing-imports .

# Show error codes
mypy --show-error-codes .
```

**Configuration**: `pyproject.toml` (gradual typing enabled)

---

### 4. Bandit (Security Scanning)

**Purpose**: Security vulnerability detection
**Version**: 1.8.6

**Common commands:**
```bash
# Scan with medium/high severity (-ll)
bandit -r . -ll

# Scan all severity levels
bandit -r .

# Skip tests
bandit -r . --exclude tests/

# Generate report
bandit -r . -f json -o bandit-report.json
```

**Configuration**: `pyproject.toml` (excludes tests, migrations)

---

### 5. Pytest (Testing)

**Purpose**: Test framework
**Version**: 8.4.2
**Plugins**: pytest-django (4.11.1), pytest-asyncio (1.2.0)

**Common commands:**
```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest services/tests/test_account_state.py

# Run specific test
pytest services/tests/test_account_state.py::test_balance_normalizes

# Run with coverage
pytest --cov=services --cov-report=html

# Stop on first failure
pytest -x
```

**Configuration**: `pyproject.toml` (Django settings auto-loaded)

---

## Supplementary Tools

### Autoflake (Cleanup)

**Purpose**: Remove unused imports and variables
**Version**: 2.3.1
**Note**: Ruff handles most cases, but autoflake can be more aggressive

```bash
# Check for unused imports
autoflake --check --remove-all-unused-imports -r .

# Auto-remove unused imports
autoflake --in-place --remove-all-unused-imports -r .
```

### isort (Import Sorting)

**Purpose**: Organize imports
**Version**: 6.1.0
**Note**: Ruff's import sorting (`ruff check --select I`) is recommended

```bash
# Check import order
isort --check-only .

# Fix import order
isort .
```

### Pylint (Deep Analysis)

**Purpose**: Additional code analysis
**Version**: 3.3.8
**Note**: Slower than Ruff, use for deeper analysis

```bash
# Analyze specific module
pylint services/

# Disable specific messages
pylint --disable=C0114 services/
```

---

## IDE Integration

### VS Code

**Recommended extensions:**
- Ruff (charliermarsh.ruff)
- Python (ms-python.python)
- Black Formatter (ms-python.black-formatter)
- Mypy Type Checker (ms-python.mypy-type-checker)

**Settings** (`.vscode/settings.json`):
```json
{
  "[python]": {
    "editor.defaultFormatter": "ms-python.black-formatter",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    }
  },
  "ruff.lint.run": "onSave",
  "ruff.organizeImports": true
}
```

### PyCharm

1. Install Ruff plugin from marketplace
2. Configure Black as external tool
3. Enable mypy plugin
4. Set up pytest as test runner

---

## CI/CD Integration

### Pre-commit Hook (Recommended)

Create `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 25.9.0
    hooks:
      - id: black
        language_version: python3.12

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.13.2
    hooks:
      - id: ruff
        args: [--fix]

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.18.2
    hooks:
      - id: mypy
        additional_dependencies: [django-stubs]
```

Install: `pip install pre-commit && pre-commit install`

### GitHub Actions

```yaml
name: Quality Checks

on: [push, pull_request]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: black --check .
      - run: ruff check .
      - run: mypy .
      - run: bandit -r . -ll
      - run: pytest
```

---

## Common Issues & Solutions

### Import Sorting Conflicts

**Problem**: Ruff and isort disagree on import order

**Solution**: Use Ruff exclusively for imports
```bash
# Disable isort, use Ruff
ruff check --fix --select I .
```

### Type Checking Errors

**Problem**: Mypy complains about missing type stubs

**Solution**: Install django-stubs (already in requirements)
```bash
pip install django-stubs
```

### Ruff Too Strict

**Problem**: Ruff reports too many issues

**Solution**: Configure `pyproject.toml` to ignore specific rules
```toml
[tool.ruff.lint]
ignore = ["E501", "PLR0913"]  # Line too long, too many arguments
```

---

## Migration from Old Tools

### From flake8 to Ruff

```bash
# Old workflow
flake8 .

# New workflow (equivalent + more)
ruff check .
```

### From isort to Ruff

```bash
# Old workflow
isort .

# New workflow
ruff check --fix --select I .
```

### From pyupgrade to Ruff

```bash
# Old workflow
pyupgrade --py312-plus **/*.py

# New workflow (integrated)
ruff check --fix --select UP .
```

---

## Performance Comparison

| Tool | Speed | Coverage |
|------|-------|----------|
| Ruff | ⚡⚡⚡⚡⚡ | 800+ rules |
| flake8 | ⚡ | ~100 rules |
| pylint | ⚡ | ~200 rules |
| Black | ⚡⚡⚡⚡ | Formatting |
| isort | ⚡⚡⚡ | Imports |

**Ruff advantage**: Runs all checks in ~100ms vs 5-10 seconds for traditional stack

---

## Best Practices

### Daily Development

1. **Format first**: `black .` before committing
2. **Fix automatically**: `ruff check --fix .` catches most issues
3. **Type check**: `mypy .` before pushing
4. **Test always**: `pytest` before commits

### Before Pull Requests

```bash
# Complete quality check
black . && \
ruff check --fix . && \
mypy . && \
bandit -r . -ll && \
pytest -v
```

### Pre-Production

```bash
# Strict checks (no auto-fix)
black --check . && \
ruff check . && \
mypy --strict . && \
bandit -r . -ll -f json -o security-report.json && \
pytest --cov=. --cov-report=html
```

---

## Additional Resources

- **Ruff**: https://docs.astral.sh/ruff/
- **Black**: https://black.readthedocs.io/
- **Mypy**: https://mypy.readthedocs.io/
- **Bandit**: https://bandit.readthedocs.io/
- **Pytest**: https://docs.pytest.org/

---

**Next Steps**: See `/validate-and-fix` Claude Code command for automated quality checks and fixes.
