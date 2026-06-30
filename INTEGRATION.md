# Integration Notes

This repository is the public packaging of the local XMU Study Toolkit integration.

## Core Files

- `setup.bat` - creates the main virtual environment, installs dependencies, installs Playwright Chromium, and creates `account.local.json` from the template.
- `setup_full.bat` - runs both core setup and optional integration setup for users who want every launcher button to work after installation.
- `run.bat` - starts the GUI, running `setup.bat` first if the main virtual environment is missing.
- `setup_optional_integrations.bat` - downloads optional upstream tools into ignored local integration directories.
- `check_install.bat` - verifies core dependencies, Python syntax, and optional integration entry files.
- `tools/install_pyproject_dependencies.py` - installs dependencies declared by optional integrations without vendoring their source into this repository.
- `tools/pip_retry.py` - wraps pip install with retries, longer timeouts, and binary-wheel preference for unstable networks.
- `tools/verify_install.py` - local installation verifier used by `check_install.bat`.
- `tools/iqa_start_integrated.py` - local launcher shim copied into `integrations/iqa_helper/` so IQA can reuse this toolkit CAS profile and account environment variables.
- `tools/course_user.example.yaml` - local config template copied into `integrations/course_helper/config/` when upstream lacks one.
- `zako_app_V2.0.py` - unified GUI launcher, teaching-platform session, rollcall monitor, radar helper, learning-platform tools, settings page.
- `zako_get_rollcall.py` - CLI teaching-platform rollcall query.
- `integrations/score_query/` - included score-query integration, based on MIT-licensed score-query work.
- `account.example.json` - local account template.
- `THIRD_PARTY_PROJECTS.md` - upstream references and license boundaries.

## Optional Local Tools

The GUI has buttons for these tools. They are installed by running:

```powershell
.\setup_optional_integrations.bat
```

Expected local paths after installation:

- `integrations/iqa_helper/start.bat` - automatic evaluation helper launcher.
- `integrations/course_helper/client.py` - course-selection helper.

These directories remain ignored by Git. They are pulled by each user locally instead of being vendored into this repository.

## Login Model

All school systems use the same XMU account identity, but session storage differs by platform:

- Teaching platform / TronClass: CAS login through Playwright, persistent profile at `.zako_browser_profile/`.
- Score query: same XMU account, separate browser profile at `integrations/score_query/browser_profile/`.
- Optional IQA/evaluation: when installed locally, the GUI passes `XMU_CAS_PROFILE_DIR=.zako_browser_profile/` and `XMU_USERNAME` / `XMU_PASSWORD`.
- Optional course helper: when installed locally, it uses its own API login and may store token/cookies under `integrations/course_helper/cache/XMUClient.json`.

## Local Config Files

Runtime configs may exist locally but must not be committed:

- `account.local.json`
- `custom_radar_locations.json`
- `integrations/score_query/config.yaml`
- `integrations/score_query/scores.yaml`
- `integrations/score_query/browser_profile/`
- `integrations/course_helper/config/user.yaml`
- `integrations/course_helper/cache/XMUClient.json`

Templates kept in the repo:

- `account.example.json`
- `integrations/score_query/config.yaml.example`

Generated locally by optional setup:

- `integrations/course_helper/config/user.example.yaml`
- `integrations/iqa_helper/start.bat`

## Publishing Notes

1. Keep `integrations/iqa_helper/` and `integrations/course_helper/` ignored unless license and redistribution permission are explicitly resolved.
2. Preserve `integrations/score_query/LICENSE` when distributing the score-query integration.
3. Do not commit browser profiles, cache files, account configs, logs, generated reports, or local shortcuts.
4. Re-run `git add --dry-run .` before every public push.
