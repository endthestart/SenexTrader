# Contributing to Senex Trader

Thank you for your interest in contributing!

## Getting Started

1. **Setup**: Follow the [README.md](README.md) installation instructions
2. **Guidelines**: Read [AI.md](AI.md) for development patterns and conventions
3. **Architecture**: Review the service layer pattern in `docs/`

## Development Workflow

### Branch Naming
- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation updates
- `refactor/` - Code refactoring

### Before Committing

```bash
ruff check --fix .  # Lint and auto-fix
black .             # Format code
pytest              # Run tests
```

### Code Quality Standards

- **Simplicity First**: Smallest change that meets requirements
- **DRY**: Centralize shared logic in `services/`
- **YAGNI**: No speculative abstractions
- **Real Data Only**: Never fabricate values
- **No Legacy Code**: Remove old implementations when replacing

### Commit Messages

```
Short summary (50 chars or less)

Detailed explanation if needed. Reference issues: Fixes #123
```

## Pull Requests

1. Push your branch
2. Open PR against `main`
3. Include: description, related issues, testing performed

## Reporting Issues

**Bugs**: Include steps to reproduce, expected vs actual behavior, environment details
**Features**: Describe use case, proposed solution, alternatives considered

## Security

- Never commit secrets (API keys, passwords, tokens)
- Use environment variables for configuration
- Report vulnerabilities privately to maintainers

## License

Contributions are licensed under the project's [CC BY-NC-SA 4.0](LICENSE) license.
