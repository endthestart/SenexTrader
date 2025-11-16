# Contributing to Senex Trader

Thank you for your interest in contributing to Senex Trader! This document provides guidelines for contributing to the project.

## 📋 Prerequisites

Before contributing, please:

1. Read the [README.md](README.md) for project overview and setup instructions
2. Review [AI.md](AI.md) for development guidelines and architectural patterns
3. Understand the project's coding standards and conventions

## 🚀 Getting Started

### Development Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd senex_trader
   ```

2. **Set up Python environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. **Run migrations**
   ```bash
   python manage.py migrate
   ```

5. **Run tests**
   ```bash
   pytest
   ```

## 🔧 Development Workflow

### 1. Create a Branch

Create a feature branch from `main`:
```bash
git checkout -b feature/your-feature-name
```

Use descriptive branch names:
- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation updates
- `refactor/` - Code refactoring
- `test/` - Test additions or updates

### 2. Make Changes

Follow the coding standards defined in [AI.md](AI.md):

- **Simplicity First**: Make the smallest change that meets requirements
- **DRY (Don't Repeat Yourself)**: Centralize shared logic in `services/`
- **YAGNI (You Aren't Gonna Need It)**: No speculative abstractions
- **Real Data Only**: Never fabricate values in production code
- **No Legacy Code**: Remove old implementations when adding new ones

### 3. Code Quality

Before committing:

```bash
# Format code
black . --line-length 100

# Run linter
ruff check .

# Run tests
pytest

# Check types (if applicable)
mypy .
```

### 4. Commit Messages

Write clear, descriptive commit messages:

```
Short summary (50 chars or less)

More detailed explanation if necessary. Wrap at 72 characters.
Explain what changed, why it changed, and any context needed.

- Bullet points for specific changes
- Reference issue numbers if applicable: Fixes #123
```

### 5. Submit Pull Request

1. Push your branch to the repository
2. Open a Pull Request against `main`
3. Fill out the PR template with:
   - Description of changes
   - Related issues
   - Testing performed
   - Screenshots (if UI changes)

## 🧪 Testing

- Write tests for new features and bug fixes
- Ensure all tests pass before submitting PR
- Aim for high test coverage
- Use pytest fixtures and Django test utilities

Test locations:
- Unit tests: `tests/`
- Integration tests: `tests/integration/`
- Service tests: `tests/services/`

## 📝 Documentation

Update documentation when:
- Adding new features
- Changing APIs or interfaces
- Modifying configuration options
- Updating deployment procedures

Documentation files:
- `README.md` - Project overview and setup
- `AI.md` - Development guidelines and patterns
- `deployment/README.md` - Deployment instructions
- Docstrings in code

## 🔒 Security

- Never commit sensitive data (API keys, passwords, tokens)
- Use environment variables for configuration
- Follow secure coding practices
- Report security vulnerabilities privately to maintainers

## 📐 Code Style

### Python

- Follow PEP 8
- Use Black formatter with 100 character line length
- Use type hints where appropriate
- Write docstrings for public functions and classes
- Keep functions focused and small

### Django

- Follow Django best practices
- Use Django ORM efficiently
- Leverage Django's security features
- Follow the project's service layer pattern

### Services Architecture

The project uses a service layer architecture:
- **Models** (`trading/models.py`, `accounts/models.py`): Database schema only
- **Services** (`services/`): Business logic and external integrations
- **Views** (`trading/views.py`): Request handling and response formatting

See [AI.md Section 5](AI.md#5-architectural-patterns) for details.

## 🐛 Bug Reports

When reporting bugs, include:

1. **Description**: Clear description of the issue
2. **Steps to Reproduce**: Detailed steps to reproduce the bug
3. **Expected Behavior**: What should happen
4. **Actual Behavior**: What actually happens
5. **Environment**: OS, Python version, dependencies
6. **Logs/Screenshots**: Any relevant error messages or screenshots

## 💡 Feature Requests

When requesting features:

1. **Use Case**: Describe the problem you're trying to solve
2. **Proposed Solution**: Your suggested approach
3. **Alternatives**: Other approaches you've considered
4. **Context**: Any additional context or examples

## ❓ Questions

For questions:
- Check existing documentation
- Search existing issues
- Open a new issue with the "question" label

## 📜 License

By contributing, you agree that your contributions will be licensed under the same license as the project.

## 🙏 Thank You

Your contributions help make Senex Trader better for everyone. We appreciate your time and effort!
