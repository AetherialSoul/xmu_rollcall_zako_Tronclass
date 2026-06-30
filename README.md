# XMU Study Toolkit

厦门大学 CAS 本机学习工具整合版。项目把畅课 / 教学平台签到工具、成绩查询入口、自动评教入口和选课助手入口收拢到一个 CustomTkinter 桌面启动器中，目标是减少重复登录、重复打开脚本和手动改配置的成本。

> 本项目仅用于本人账号、本机环境下的学习与自动化研究。请遵守学校教学管理要求、课程要求和平台使用规范；不要把账号、Cookie、浏览器配置、成绩缓存或验证码服务 Key 上传到公开仓库。

## 功能概览

开箱随仓库提供：

- 统一主页：`成绩查询`、`教学平台`、`自动评教`、`选课`、`设置` 五个入口。
- 教学平台：使用 Playwright 打开 XMU CAS / TronClass，登录态保存在本机 `.zako_browser_profile/`，返回主页再进入时会优先复用当前会话。
- 签到工具：课程列表、数字签到码查询、签到提醒、自动监听、确认后提交数字签到。
- 雷达点名：校区 / 教学楼预设、失败诊断、坐标微调和自定义位置库，便于现场确认后调整提交。
- 学习通 / 畅课工具：考试 / 作业列表、试题内容、答案 / 解析接口返回、课堂互动列表和互动题目。
- 成绩查询：集成 `XMUScoreAutoQuery` / 培养方案完成度查询思路，支持标准成绩接口、培养方案完成度接口和自动优先模式。
- 个性化设置：统一账号、登录方式、成绩查询方式、通知方式、教务链接参数、默认雷达位置、选课间隔和验证码参数。

通过可选脚本安装：

- 自动评教：从 `vintcessun/XMUIQAHelper` 拉取到本机 `integrations/iqa_helper/`。
- 选课助手：从 `wegret/XMUCourseHelper` 拉取到本机 `integrations/course_helper/`。

这两个目录默认被 Git 忽略，因为它们由用户本机按需拉取，不直接作为本仓库源码再分发。

## 快速开始

环境建议：

- Windows 10/11
- Python 3.11+
- Git for Windows 可选；没有 Git 时，可选集成脚本会尝试下载 GitHub ZIP
- Microsoft Edge 或 Google Chrome；也可以使用 Playwright 自带 Chromium

```powershell
git clone https://github.com/AetherialSoul/xmu_rollcall_zako_Tronclass.git
cd xmu_rollcall_zako_Tronclass
.\setup_full.bat
.\run.bat
```

`setup_full.bat` 会完成核心安装和完整按钮功能安装：

- 创建 `.venv`
- 安装主项目依赖
- 安装 Playwright Chromium
- 复制 `account.example.json` 为本地 `account.local.json`
- 拉取自动评教和选课助手上游项目到本机 `integrations/`
- 安装可选集成依赖，并生成本地启动器 / 配置模板

只需要教学平台、签到和成绩查询时，也可以只运行：

```powershell
.\setup.bat
.\run.bat
```

首次运行后，到 `设置` 页面填写统一认证账号密码，或手动编辑：

```json
{
  "username": "your_student_id",
  "password": "your_password"
}
```

## 安装完整按钮功能

如果之前只跑过 `setup.bat`，后来需要 `自动评教` 和 `选课` 两个按钮也能直接启动，运行：

```powershell
.\setup_optional_integrations.bat
```

这个脚本会：

- 从 GitHub 拉取自动评教和选课助手上游项目到 `integrations/`。
- 为自动评教复制 `tools/iqa_start_integrated.py`，并生成适配本项目虚拟环境和 CAS 登录态的 `start.bat`。
- 为选课助手生成 `config/user.example.yaml` 和本地 `config/user.yaml`。
- 把可选依赖安装进主项目 `.venv`。

可选集成优先使用 `git clone` / `git pull`；网络不稳定导致 Git 失败时，会尝试下载 GitHub ZIP 压缩包作为兜底。

安装完成后重新打开 `run.bat`，再点击 `自动评教` 或 `选课`。

选课验证码默认为手动输入；如果要使用多模态 LLM 自动识别验证码，在 `设置` 页面填写验证码接口地址、模型和 API Key。

安装后可以运行检查脚本确认本机完整功能文件和依赖齐全：

```powershell
.\check_install.bat
```

## 目录结构

```text
.
├─ setup.bat                         # 初始化主项目环境
├─ setup_full.bat                    # 初始化主项目 + 拉取可选完整功能
├─ run.bat                           # 启动 GUI
├─ setup_optional_integrations.bat    # 拉取自动评教/选课可选集成
├─ check_install.bat                  # 检查完整安装是否齐全
├─ tools/                             # 可选集成启动器和配置模板
├─ zako_app_V2.0.py                   # 主 GUI：统一启动器 + 教学平台工具
├─ zako_get_rollcall.py               # CLI 版教学平台签到查询
├─ account.example.json               # 本地账号配置模板
├─ integrations/
│  └─ score_query/                    # 成绩查询集成，保留原 MIT License
├─ THIRD_PARTY_PROJECTS.md            # 参考项目与许可证边界
└─ INTEGRATION.md                     # 本地集成目录和配置说明
```

运行时会生成的个人文件已加入 `.gitignore`，包括 `account.local.json`、`.zako_browser_profile/`、`custom_radar_locations.json`、成绩查询配置、浏览器缓存、Cookie、日志和报告文件。

## 成绩查询配置

成绩查询代码位于 `integrations/score_query/`，配置由主程序设置页写入：

- `integrations/score_query/config.yaml`
- `integrations/score_query/scores.yaml`
- `integrations/score_query/browser_profile/`

设置页中可以配置：

- 查询来源：标准成绩接口、培养方案完成度、自动优先完成度。
- 检查间隔、通知方式、是否在通知中显示具体分数。
- 教务系统入口链接 `browser.start_url`。
- 培养方案完成度接口参数，例如 `PYFADM`、`PYFAMC`、`PCDM`、`YMJS`、`BYNJDM`、`SCLBDM`。

如果教务系统页面或参数变化，可以先在浏览器里打开对应页面，再把当前链接和接口参数填入设置页。

## 可选集成说明

`自动评教` 和 `选课` 不是手动复制源码进本仓库，而是由 `setup_optional_integrations.bat` 在用户本机拉取上游项目。这样可以让功能可用，同时避免把许可证不一致或没有明确再分发授权的第三方源码直接混入本仓库。

如果按钮提示“可选集成尚未安装”，运行：

```powershell
.\setup_optional_integrations.bat
```

## 参考项目

本整合版参考或集成过以下项目的思路，详细边界见 [THIRD_PARTY_PROJECTS.md](THIRD_PARTY_PROJECTS.md)：

- `hankeke303/XMUScoreAutoQuery`：成绩查询与通知基础。
- `AetherialSoul/XMUScoreCompletionQuery`：培养方案完成度成绩来源。
- `vintcessun/XMUIQAHelper`：自动评教入口与 CAS 登录态复用思路。
- `wegret/XMUCourseHelper`：选课助手入口、间隔和验证码配置项。
- `vintcessun/xmu_assistant_sign_bot`：教学平台工具命令设计、考试 / 作业 / 答案 / 课堂互动查询思路。
- `vintcessun/xmu_sign_qr`、`KrsMt-0113/XMU-Rollcall-bot_qrCode`：二维码签到流程调研；当前公开版不内置二维码签到。
- `dangzitou/xmu-rollcall-bot-new`、`KrsMt-0113/xmu-rollcall-wechat-bot`：雷达点名与签到生态调研。

## 开发与检查

语法检查：

```powershell
.\.venv\Scripts\python.exe -m py_compile .\zako_app_V2.0.py .\zako_get_rollcall.py
.\check_install.bat /nopause
```

提交前建议确认不会上传个人数据：

```powershell
git status --short
git add --dry-run .
```

## 许可证

本仓库主项目使用 MIT License。`integrations/score_query/` 保留其上游 MIT License 与版权声明。通过 `setup_optional_integrations.bat` 拉取的第三方项目不受本仓库 MIT License 覆盖，请分别遵守对应上游项目许可证。
