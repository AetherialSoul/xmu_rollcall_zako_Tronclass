# XMU Study Toolkit

厦门大学 CAS 本机学习工具整合版。项目把原来的畅课 / 教学平台签到工具、成绩查询入口和若干可选校园工具收拢到一个 CustomTkinter 桌面启动器中，目标是减少重复登录、重复打开脚本和手动改配置的成本。

> 本项目仅用于本人账号、本机环境下的学习与自动化研究。请遵守学校教学管理要求、课程要求和平台使用规范；不要把账号、Cookie、浏览器配置、成绩缓存或验证码服务 Key 上传到公开仓库。

## 功能概览

- 统一主页：启动后提供 `成绩查询`、`教学平台`、`自动评教`、`选课`、`设置` 五个入口。
- 教学平台：使用 Playwright 打开 XMU CAS / TronClass，登录态保存在本机 `.zako_browser_profile/`，返回主页再进入时会优先复用当前会话。
- 签到工具：支持课程列表、数字签到码查询、签到提醒、自动监听和确认后提交。
- 二维码签到：内置本地扫码页，浏览器前端调用摄像头识别二维码，也支持手动粘贴二维码内容后提交。
- 雷达点名：提供校区 / 教学楼预设、失败诊断、坐标微调和自定义位置库，便于现场确认后调整提交。
- 学习通 / 畅课工具：可查询课程考试 / 作业列表、试题内容、答案 / 解析接口返回，以及课堂互动列表和互动题目。
- 成绩查询：集成 `XMUScoreAutoQuery` / 培养方案完成度查询思路，支持标准成绩接口、培养方案完成度接口和自动优先模式。
- 个性化设置：在 GUI 内配置统一账号、登录方式、成绩查询方式、通知方式、教务链接参数、默认雷达位置、选课间隔和验证码参数。
- 可选外部工具：自动评教和选课入口保留为本地集成目录，公开仓库不直接分发授权不明确的第三方源码。

## 目录结构

```text
.
├─ zako_app_V2.0.py              # 主 GUI：统一启动器 + 教学平台工具
├─ zako_get_rollcall.py          # CLI 版教学平台签到查询
├─ account.example.json          # 本地账号配置模板
├─ integrations/
│  └─ score_query/               # 成绩查询集成，保留原 MIT License
├─ THIRD_PARTY_PROJECTS.md       # 参考项目与许可证边界
└─ INTEGRATION.md                # 本地集成目录和配置说明
```

运行时会生成的个人文件已加入 `.gitignore`，包括 `account.local.json`、`.zako_browser_profile/`、`custom_radar_locations.json`、成绩查询配置、浏览器缓存、Cookie、日志和报告文件。

## 安装

环境建议：

- Windows 10/11
- Python 3.11+
- Microsoft Edge 或 Google Chrome；也可以安装 Playwright 自带 Chromium

```powershell
git clone https://github.com/AetherialSoul/xmu_rollcall_zako_Tronclass.git
cd xmu_rollcall_zako_Tronclass

py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium

copy account.example.json account.local.json
notepad account.local.json
```

`account.local.json` 示例：

```json
{
  "username": "your_student_id",
  "password": "your_password"
}
```

启动：

```powershell
.\.venv\Scripts\python.exe .\zako_app_V2.0.py
```

首次使用教学平台或成绩查询时，按弹出的浏览器完成 XMU CAS 登录。后续会尽量复用本机登录态。

## 成绩查询配置

成绩查询代码位于 `integrations/score_query/`，配置由主程序设置页写入：

- `integrations/score_query/config.yaml`
- `integrations/score_query/scores.yaml`
- `integrations/score_query/browser_profile/`

这些文件都只保存在本机，不会被 Git 跟踪。设置页中可以配置：

- 查询来源：标准成绩接口、培养方案完成度、自动优先完成度。
- 检查间隔、通知方式、是否在通知中显示具体分数。
- 教务系统入口链接 `browser.start_url`。
- 培养方案完成度接口参数，例如 `PYFADM`、`PYFAMC`、`PCDM`、`YMJS`、`BYNJDM`、`SCLBDM`。

如果教务系统页面或参数变化，可以先在浏览器里打开对应页面，再把当前链接和接口参数填入设置页。

## 可选本地集成

公开仓库默认只包含本项目代码和可确认 MIT 授权的成绩查询集成。以下工具在 GUI 中保留入口，但源码不随本仓库分发；如果你确认有使用和再分发权限，可以自行放到对应目录：

- 自动评教：`integrations/iqa_helper/start.bat`
- 选课助手：`integrations/course_helper/client.py`

主程序会在入口缺失时给出提示，不会影响教学平台和成绩查询功能。

## 参考项目

本整合版参考或集成过以下项目的思路，详细边界见 [THIRD_PARTY_PROJECTS.md](THIRD_PARTY_PROJECTS.md)：

- `hankeke303/XMUScoreAutoQuery`：成绩查询与通知基础。
- `AetherialSoul/XMUScoreCompletionQuery`：培养方案完成度成绩来源。
- `vintcessun/XMUIQAHelper`：自动评教入口与 CAS 登录态复用思路。
- `wegret/XMUCourseHelper`：选课助手入口、间隔和验证码配置项。
- `vintcessun/xmu_assistant_sign_bot`：教学平台工具命令设计、考试 / 作业 / 答案 / 课堂互动查询思路。
- `vintcessun/xmu_sign_qr`、`KrsMt-0113/XMU-Rollcall-bot_qrCode`：二维码签到流程调研。
- `dangzitou/xmu-rollcall-bot-new`、`KrsMt-0113/xmu-rollcall-wechat-bot`：雷达点名与签到生态调研。

## 开发与检查

语法检查：

```powershell
.\.venv\Scripts\python.exe -m py_compile .\zako_app_V2.0.py .\zako_get_rollcall.py
```

提交前建议确认不会上传个人数据：

```powershell
git status --short
git add --dry-run .
```

## 许可证

本仓库主项目使用 MIT License。`integrations/score_query/` 保留其上游 MIT License 与版权声明。未直接随仓库分发的第三方项目不受本仓库 MIT License 覆盖，请分别遵守对应上游项目许可证。

