# Third-Party Projects

This file records which projects were integrated, referenced, or installed optionally while building the public XMU Study Toolkit repository.

## Included In This Repository

| Project | Upstream / Source | Local Path | Role | License Notes |
| --- | --- | --- | --- | --- |
| `xmu_rollcall_zako_Tronclass` | https://github.com/YixuAnsensei/xmu_rollcall_zako_Tronclass | repository root | Base GUI, TronClass login/session handling, rollcall monitor, teaching-platform tools, settings page, radar helper. | MIT, see root `LICENSE`. |
| `XMUScoreAutoQuery` / completion-query variant | https://github.com/hankeke303/XMUScoreAutoQuery and https://github.com/AetherialSoul/XMUScoreCompletionQuery | `integrations/score_query` | Score-query backend launched by the unified GUI. Includes browser-login mode, standard score source, completion-plan source, local notifications, and SMTP option. | MIT; upstream notice is preserved in `integrations/score_query/LICENSE`. |

## Optional User-Installed Integrations

These projects are not vendored in this repository. Users can install them locally by running `setup_optional_integrations.bat`, which clones the upstream repositories into Git-ignored paths under `integrations/`.

| Project | URL | Installed Path | What This Toolkit Uses | License / Packaging Treatment |
| --- | --- | --- | --- | --- |
| `XMUIQAHelper` | https://github.com/vintcessun/XMUIQAHelper | `integrations/iqa_helper` | Automatic evaluation flow. The toolkit copies a local launcher shim and passes `XMU_CAS_PROFILE_DIR`, `XMU_USERNAME`, and `XMU_PASSWORD` when launching its `start.bat`. | Optional local install only. GitHub API reported GPL-3.0 during local review, so source is not bundled into this MIT repository. |
| `XMUCourseHelper` | https://github.com/wegret/XMUCourseHelper | `integrations/course_helper` | Course-selection helper, polling interval options, captcha configuration model, and local token cache behavior. | Optional local install only. No GitHub license file was detected during local review, so source is not bundled. |

## Referenced But Not Vendored

These projects informed feature design or local experiments, but their source code is not included in the public MIT distribution unless explicitly listed above.

| Project | URL | What Was Referenced | Public Repo Treatment |
| --- | --- | --- | --- |
| `xmu_assistant_sign_bot` | https://github.com/vintcessun/xmu_assistant_sign_bot | Teaching-platform command design, exam/homework list flow, question and answer retrieval ideas, classroom interaction querying, and web/rich-text exposure pattern. | Reference only. GitHub API reported AGPL-3.0 during local review, so code was not copied. |
| `xmu_sign_qr` | https://github.com/vintcessun/xmu_sign_qr | QR-code rollcall research and parsing/submission flow comparison. | Reference only; current public version does not include QR sign-in. |
| `XMU-Rollcall-bot_qrCode` | https://github.com/KrsMt-0113/XMU-Rollcall-bot_qrCode | Browser-front-end QR recognition and QR payload parsing research. | Reference only. No GitHub license file was detected during local review. |
| `xmu-rollcall-wechat-bot` | https://github.com/KrsMt-0113/xmu-rollcall-wechat-bot | Rollcall bot ecosystem and radar/location behavior research. | Reference only; no direct vendoring. |
| `xmu-rollcall-bot-new` | https://github.com/dangzitou/xmu-rollcall-bot-new | Rollcall bot/fork comparison and radar-sign behavior research. | Reference only; no direct vendoring. |
| `xmu-rollcall-app` | https://github.com/gammars/xmu-rollcall-app | Rollcall app ecosystem reference from the repository survey. | Reference only. |
| `xmulogin` | https://github.com/KrsMt-0113/xmulogin | XMU CAS/login SDK reference from the repository survey. | Reference only. |
| `xmu-question-bank` | https://github.com/F5Soft/xmu-question-bank | Question-bank ecosystem reference from the repository survey. | Reference only. |
| `xmu-xigai-question-bank` | https://github.com/CatNebulaaaa/xmu-xigai-question-bank | Learning-platform question/answer collection reference from the repository survey. | Reference only. |

## Do Not Commit

The repository `.gitignore` is configured to keep these local-only files out of Git:

```gitignore
account.local.json
custom_radar_locations.json
.zako_browser_profile/
browser_profile/
config.yaml
scores.yaml
Cookie.txt
integrations/score_query/config.yaml
integrations/score_query/scores.yaml
integrations/score_query/browser_profile/
integrations/iqa_helper/
integrations/course_helper/
integrations/course_helper/config/user.yaml
integrations/course_helper/cache/XMUClient.json
*.log
__pycache__/
*.pyc
```

Before publishing, always run:

```powershell
git status --short
git add --dry-run .
```

and confirm that no account, password, token, Cookie, browser profile, generated report, or local shortcut appears in the add list.
