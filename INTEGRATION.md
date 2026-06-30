# Integration Notes

This repository is the public, license-safe packaging of the local XMU Study Toolkit integration.

## Core Files

- `zako_app_V2.0.py` - unified GUI launcher, teaching-platform session, rollcall monitor, QR/radar helpers, learning-platform tools, settings page.
- `zako_get_rollcall.py` - CLI teaching-platform rollcall query.
- `integrations/score_query/` - included score-query integration, based on MIT-licensed score-query work.
- `account.example.json` - local account template.
- `THIRD_PARTY_PROJECTS.md` - upstream references and license boundaries.

## Optional Local-Only Tools

The GUI has buttons for these tools, but this public repository does not vendor their source trees:

- `integrations/iqa_helper/` - automatic evaluation helper, expected entry `start.bat`.
- `integrations/course_helper/` - course-selection helper, expected entry `client.py`.

Reason: during local review, `XMUIQAHelper` was GPL-3.0 and `XMUCourseHelper` had no detected GitHub license file. Keeping them local avoids mixing unclear or incompatible licensing into the MIT public repository.

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

## Publishing Notes

1. Keep `integrations/iqa_helper/` and `integrations/course_helper/` ignored unless license and redistribution permission are explicitly resolved.
2. Preserve `integrations/score_query/LICENSE` when distributing the score-query integration.
3. Do not commit browser profiles, cache files, account configs, logs, generated reports, or local shortcuts.
4. Re-run `git add --dry-run .` before every public push.
