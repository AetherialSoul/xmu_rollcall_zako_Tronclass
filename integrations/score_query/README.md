# 厦门大学成绩自动查询脚本（学业完成进度接口改造版）

一个用于自动查询厦门大学学生成绩的 Python 小程序。相比原项目，本改造版将查询来源改为“学业完成进度 / 培养方案详情”接口，可在常规成绩查询入口因评教限制暂不展示时，读取培养方案中已经同步的课程成绩，并通过系统通知或邮件推送提醒。

## 功能

- 默认使用浏览器会话登录：首次运行在 Edge 中手动登录，后续复用本地浏览器登录态。
- 可选在浏览器登录页自动提交一次账号密码；失败后不会继续重试，避免账号冻结。
- 定时查询成绩并与本地缓存 `scores.yaml` 对比。
- 发现新增成绩或成绩变化后自动推送。
- 支持按学期、课程名或课程号过滤。
- 支持系统通知、SMTP 邮件通知，或两者同时开启。
- 遇到教务接口 `401/403` 时会自动清理登录态、重新登录，并在成功后立即补查一次。
- 支持百分制与“合格”等非数字成绩。
- 通过 `browser_profile/` 保存本机浏览器会话；该目录已加入 `.gitignore`。

## 原理

原项目主要调用教务系统成绩查询接口：

```text
/jwapp/sys/cjcx/modules/cjcx/xscjcx.do
```

本改造版改为调用“学业完成进度 / 培养方案详情”页面使用的接口：

```text
/jwapp/sys/xywcjdMobile/modules/kzkcxq/cxscfakzkc.do
```

该接口返回培养方案内课程的修读情况，其中包含课程号、课程名、学期、学分和成绩字段。脚本会筛选出已有成绩的课程，和本地缓存比较；如果课程是第一次出现，或分数发生变化，就发送提醒。

## 安装

```shell
git clone https://github.com/AetherialSoul/XMUScoreCompletionQuery.git
cd XMUScoreCompletionQuery
pip install -r requirements.txt
```

Windows 用户也可以自行写 `.bat` 启动脚本，先进入项目目录再运行 `python browser_query.py`。

如果要使用系统通知，请确保安装了 `plyer`。`requirements.txt` 已包含该依赖；如果是自行精简安装环境，请补装：

```shell
pip install plyer
```

如果 macOS 系统通知不可用，可以额外安装：

```shell
pip install pyobjus
```

## 配置

复制配置文件：

```shell
cp config.yaml.example config.yaml
```

填写 `config.yaml`：

```yaml
info:
  username:       # 统一身份认证用户名（学号）
  password:       # 默认可留空；仅 browser.auto_login_once=true 时会在浏览器登录页自动提交一次
browser:
  auto_login_once: false # true: 每次程序启动最多自动提交一次密码；失败后只等待手动登录
  start_url:       # 可选；留空时 completion 模式自动打开培养方案详情页
interval: 10      # 检查间隔（分钟）
terms:            # 留空查询所有学期
  # - 2025-2026学年 第二学期
courses:          # 留空查询所有课程
  # - 微积分I-2
notify: system    # system / email / both / none / 留空
email:
  host:           # 例如 smtp.163.com
  port:           # 例如 465
  username:       # 邮箱地址
  password:       # SMTP 授权码，不是邮箱登录密码
  use_ssl: false
  receiver:
show_score: true
score_query:
  source: completion # completion / standard / auto
completion_query:
  pyfadm:         # 从培养方案详情页面 URL 的 PYFADM 参数复制
  pyfamc:         # 从培养方案详情页面 URL 的 PYFAMC 参数复制
  pcdm: '-'
  ymjs: '0'
  bynjdm: '-'
  sclbdm: '04'
```

### 如何获取 `completion_query`

`completion_query` 不是账号密码，而是“学业完成进度”页面用来定位培养方案的一组查询参数。不同年级、专业、培养方案的参数可能不同，所以需要从自己的教务系统页面 URL 中复制。

其中最重要的是：

- `pyfadm`：培养方案代码，对应 URL 里的 `PYFADM=...`
- `pyfamc`：培养方案名称，对应 URL 里的 `PYFAMC=...`
- `pcdm`：批次代码，对应 URL 里的 `PCDM=...`，通常是 `-`
- `ymjs`：页面参数，对应 URL 里的 `YMJS=...`，通常是 `0`

获取步骤：

1. 打开厦门大学教务系统。
2. 进入“学业完成进度”或“培养方案详情”。
3. 复制浏览器地址栏中 `#/pyfaxq?...` 后面的参数，例如：

```text
#/pyfaxq?PCDM=-&PYFADM=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx&PYFAMC=2025级计算机类主修培养方案&XH=学号&YMJS=0
```

4. 将其中的 `PYFADM` 填到 `completion_query.pyfadm`，`PYFAMC` 填到 `completion_query.pyfamc`。

## 查询接口选择

可以通过 `score_query.source` 选择查询来源：

- `completion`：学业完成进度 / 培养方案详情接口。本改造版默认值，适合常规成绩查询被评教限制、但培养方案中已经同步成绩的情况。
- `standard`：原项目使用的常规成绩查询接口。优点是无需填写培养方案参数；缺点是可能受评教或教务系统开放状态影响。
- `auto`：先查 `completion`，如果没有返回成绩，再回退到 `standard`。

```yaml
score_query:
  source: completion
```

## 邮件通知示例

163 邮箱：

```yaml
notify: email
email:
  host: smtp.163.com
  port: 465
  username: yourname@163.com
  password: your_smtp_authorization_code
  use_ssl: true
  receiver: yourname@163.com
```

QQ 邮箱：

```yaml
notify: email
email:
  host: smtp.qq.com
  port: 465
  username: yourname@qq.com
  password: your_smtp_authorization_code
  use_ssl: true
  receiver: yourname@qq.com
```

## 使用

```shell
python browser_query.py
```

程序会打开 Edge 并进入教务系统。首次运行时请在浏览器里完成统一身份认证；之后程序会按 `interval` 设置的间隔刷新页面并查询成绩。如果登录态过期，程序会先自动清理登录态并重新登录；重登成功后会立即补查一次，不必等到下一个轮询周期。如果学校登录流程需要人工处理，程序会提示你在浏览器里继续完成，不会后台反复提交密码。

当 `score_query.source` 为 `completion` 或 `auto` 时，浏览器默认打开“学业完成进度 / 培养方案详情”页面；当 `source` 为 `standard` 时，才打开常规成绩查询页面。如果学校页面地址变化，可以在 `config.yaml` 里手动覆盖：

```yaml
browser:
  start_url: "https://jw.xmu.edu.cn/jwapp/sys/xywcjdMobile/*default/index.do#/pyfaxq?..."
```

如果你确认要让程序自动填一次登录表单，可以在 `config.yaml` 中开启：

```yaml
browser:
  auto_login_once: true
```

该开关每次程序启动最多提交一次密码。登录失败、验证码、二次验证、账号冻结或页面未跳转时，程序只会等待手动登录。

自动登录会先进入统一认证的账号密码登录页，再把登录成功后的 `service` 跳转到目标教务页面。脚本会尝试点击常见登录按钮；如果学校登录页结构变化，可能出现“已填入但未点击登录”的情况，此时请手动点击登录，或根据页面结构调整 `browser_query.py` 中的按钮选择器。

`app.py` 是旧版后台密码登录入口，默认已禁用。只有显式运行 `python app.py --allow-password-login` 才会启用，并且每次运行最多提交一次密码。不建议在公开环境或无人值守环境使用旧入口。

程序会立即查询一次成绩，然后按 `interval` 设置的间隔循环查询。如果第一次运行没有 `scores.yaml`，已有成绩会被写入缓存并触发一次提醒；之后只有新增成绩或成绩变化才会提醒。

如果你不想要任何通知，只想在控制台看输出，可以把 `notify` 设为 `none`，或留空。

如果运行在个人电脑或笔记本上，系统休眠期间脚本不会继续查询。需要持续监控时，建议运行在不休眠的主机或服务器上。

## 与原项目相比的优化点

- 查询来源改为“学业完成进度 / 培养方案详情”接口，能读取培养方案中已同步的成绩。
- 默认入口改为浏览器会话模式，避免后台多次提交统一认证密码导致账号冻结。
- 遇到 `401/403` 时自动清理登录态、重新登录，并在恢复后立即补查一次。
- 旧版后台密码登录入口默认禁用，并限制每次运行最多提交一次密码。
- 支持非百分制成绩，如“合格”。
- 学分、成绩等字段做了类型兼容，避免 GPA 计算或字符串乘法导致崩溃。
- 使用 `ast.literal_eval` 读取 Cookie 缓存，替代直接 `eval`。
- 将培养方案参数抽到 `config.yaml`，避免把个人培养方案写死在代码里。
- 通知模块改为按需加载配置和依赖；即使暂时没配置通知或缺少系统通知依赖，也不会在程序启动阶段直接崩溃。
- README 增加接口原理、配置方法、邮箱推送示例和注意事项。

## 参考项目与许可证

本项目是基于 [hankeke303/XMUScoreAutoQuery](https://github.com/hankeke303/XMUScoreAutoQuery) 的改造版本，原项目采用 MIT License。仓库中保留了原项目的 `LICENSE` 文件及版权声明（Copyright (c) 2023 Inorka），本改造版同样按 MIT License 公开。

登录与加密逻辑还参考了 [kirainmoe/auto-daily-health-report](https://github.com/kirainmoe/auto-daily-health-report)。

## 注意事项

1. 请合理设置查询间隔，避免过于频繁访问统一身份认证或教务系统。
2. `config.yaml`、`Cookie.txt`、`scores.yaml`、`browser_profile/` 包含个人信息或登录状态，已加入 `.gitignore`，不要上传到公开仓库。
3. 邮件密码应填写 SMTP 授权码，不要填写邮箱登录密码。
4. 本项目仅用于个人学习与自用提醒，请遵守学校相关系统使用规范。
5. 系统通知受操作系统限制，短时间内多门课程出分时可能显示不完整；需要稳定推送到手机时建议使用邮件通知。
6. 如果只需要邮件通知或完全不需要通知，系统通知依赖缺失不会阻止主程序运行；只有真正调用系统通知时才会提示缺少 `plyer`。
7. 开启 `browser.auto_login_once` 后，每次程序启动最多自动提交一次统一认证表单；不要改成循环重试，否则可能触发账号冻结。
8. 如果统一认证出现验证码、短信/扫码/二次验证、密码过期、账号冻结等状态，请在浏览器中手动处理，脚本不会绕过这些校验。
9. 如果浏览器已经停在登录页但没有自动点击，通常是学校登录页按钮结构变化；手动点击一次即可继续使用，后续可按实际页面更新按钮选择器。
10. 不建议在服务器、共享电脑或无人值守环境保存统一认证密码；更稳妥的方式是手动登录一次后复用 `browser_profile/` 中的本机浏览器会话。

## 如果已经误传敏感信息

如果曾经把 `config.yaml`、`Cookie.txt`、`scores.yaml`、`browser_profile/` 或真实账号密码推送到 GitHub：

1. 立即修改统一身份认证密码。
2. 重新生成邮箱 SMTP 授权码，旧授权码作废。
3. 删除 GitHub 上的敏感文件，并清理 Git 历史或重建仓库后重新推送。
4. 即使清理了提交历史，也应把已泄露的密码和授权码视为永久泄露。

## 免责声明

本项目为个人学习和自用工具改造版本，仅用于查询本人教务信息。使用者应自行承担使用风险，包括但不限于账号登录异常、接口变化、通知延迟、成绩显示差异等问题。请勿用于未授权账号或任何违反学校规定的用途。
