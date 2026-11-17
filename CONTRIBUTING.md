# Contributing

- Open an issue for bugs or feature ideas. For larger changes, discuss the approach first.
- Fork the repository and create your feature or fix branch from `develop`.
- Open your pull request against **develop**, not the default `main` branch.
- Keep each PR focused on one feature or fix, and explain how you checked it.
- Use fixture histories and fake agent commands for tests. Do not change real session history.
- Read [development.md](docs/development.md) for setup and tests.
- Website-only changes can target `main` and should include a local preview check.

Maintainers combine changes on `develop`, then merge a release PR into `main`.
Herdr users receive code from `main`, so only changes ready for users belong there.
