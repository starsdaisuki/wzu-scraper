# WZU Scraper

> 温州大学教务系统爬虫 + 全站搜索引擎 + 抢课工具

一键登录温州大学 CAS 统一认证，查课表、查成绩、搜索 7 个学院网站的通知公告，选课期间还能自动抢课。

## 功能

**教务系统**
- 自动登录 CAS（处理 AES 加密 + OAuth2 跳转，登录一次后自动保存 session）
- 查课程表、查成绩（支持按学年学期筛选）
- 查考试安排（考场、座位号、时间）
- 查询后可导出：课表/成绩/考试/已选课程支持 `CSV`、`JSON`，课表和考试额外支持 `ICS`

**选课/抢课**
- 搜索可选课程和教学班
- 查看我的已选课程 / 教学班列表
- 一键选课/退课
- 抢课模式：自动重试 N 次，可设置间隔、最大尝试次数、随机抖动和定时开抢
- 课程余量监控：支持多门课同时监控、JSONL 日志、空位变化提醒，并可自动抢位
- 提醒渠道：铃声 / macOS 桌面 / Telegram
- 支持 Ctrl+C 随时中断

**全站搜索**
- 爬取 7 个学院/部门网站的文章，本地全文搜索
- 支持：教务处、数理学院、计算机与人工智能学院、化学与材料工程学院、建筑工程学院、机电工程学院、生环学院
- 搜索结果可直接查看全文内容
- 支持按站点过滤 + 任意页大小分页（`n` 下一页 / `p` 上一页 / `g 3` 跳到第 3 页）

**WebVPN 直通**
- 自动登录学校 WebVPN，解锁只对校园网开放的 JSP 分类（教务处的 `学生公告`/`教师公告`/`信息服务`、机电学院的 `学生通知` 等）
- 所有请求在 Python 层透明改写成 `xxx-443.webvpn.wzu.edu.cn`，不改你的系统路由
- Cookie 独立存到 `.webvpn-cookies.json`，和教务系统 session 隔离

## 快速开始

### 1. 安装

需要 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)（Python 包管理器）。

```bash
# 安装 uv（如果还没有的话）
# macOS / Linux:
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows:
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 克隆项目
git clone https://github.com/starsdaisuki/wzu-scraper.git
cd wzu-scraper

# 安装依赖（uv 会自动创建虚拟环境）
uv sync
```

### 2. 配置账号

在项目根目录创建 `.env` 文件：

```
WZU_USERNAME=你的学号
WZU_PASSWORD=你的密码
```

> `.env` 已在 `.gitignore` 中，不会被提交到 git。不配置也行，运行时会提示你手动输入。

### 3. 运行

```bash
uv run python main.py
```

首次运行会登录 CAS 并保存 session，之后运行直接复用，不需要重复登录。

如果你想用带界面的终端版助手，可以直接启动 TUI：

```bash
uv run python main.py --tui
# 或者更短
uv run python main.py -t
```

TUI 目前支持：
- 课表 / 成绩 / 考试 / 已选课程 / 学生信息查看
- 课程搜索
- 课程监控页：可把搜索结果加入监控列表，再在 TUI 里手动轮询检查空位
- 在课程搜索页直接选课，在已选课程页直接退课
- 在 TUI 里直接导出当前列表
- 右侧详情面板会显示当前高亮记录的完整信息
- `↑↓` 切换页面，`j/k` 选列表行，`Enter` / `r` 刷新，`/` 搜索
- `x` 选课，`d` 退课，`m` 加入监控，`u` 移出监控，`c` 轮询监控，`a` 切换自动抢课，`e` 导出，`q` 退出

**可选：设置快捷命令**

```bash
# macOS / Linux: 在 ~/.zshrc 或 ~/.bashrc 中添加
alias wzu='cd /你的路径/wzu-scraper && uv run python main.py'

# 之后直接输入 wzu 就能启动
```

### 4. 使用

```
--- WZU Scraper ---
1. Course schedule (课程表)
2. Grades (成绩)
3. Exams (考试安排)              ← 考场、座位号
4. Student info (个人信息)
5. Website search (网站搜索)
6. Course selection (选课/抢课)  ← 抢课在这里
7. Course monitor (课程余量监控) ← 自动蹲位
8. Session status
0. Exit
```

进入「网站搜索」后可以搜索 7 个网站的通知公告并查看全文。

进入「选课/抢课」后可以：
- 搜索可选课程，查看教学班详情（教师、时间、已选/容量）
- 查看当前已选课程，再从已选列表里退课
- 开启抢课模式：设置重试次数、间隔、抖动，或者定时到整点开抢

进入「课程余量监控」后可以：
- 一次选中多门课一起蹲位
- 有空位时自动抢课，或者通过铃声 / macOS 通知 / Telegram 提醒你
- 把每次轮询结果写到 `JSONL` 日志里，后面自己分析

如果要启用 Telegram 提醒，在 `.env` 里额外加：

```
WZU_TELEGRAM_BOT_TOKEN=你的机器人 token
WZU_TELEGRAM_CHAT_ID=你的 chat id
```

查询课表 / 成绩 / 考试 / 已选课程后，CLI 会顺手问你要不要导出：
- `CSV`：适合表格整理
- `JSON`：适合继续编程处理
- `ICS`：课表 / 考试可直接导入日历应用

课表导出为 `ICS` 时，会额外问你“第 1 周周一是哪一天”，因为教务接口只给了`星期几 + 节次 + 周次`，没有直接给出具体日期。你还可以顺手给日历事件加前缀、分类和颜色。

### 作为 Python 库使用

```python
from wzu_scraper.client import WZUClient

with WZUClient() as client:
    client.login_cas("学号", "密码")

    # 获取课程表
    for c in client.get_course_schedule("2025-2026", "2"):
        print(f"{c['weekday']} {c['name']} {c['teacher']} {c['location']}")

    # 获取全部成绩
    for g in client.get_grades("", ""):
        print(f"{g['name']} {g['grade']} GPA:{g['gpa_point']}")
```

```python
from wzu_scraper.cms import CMSScraper

with CMSScraper() as s:
    s.crawl("slxy", max_pages=5)           # 爬取数理学院最近 5 页
    for art in s.search("建模"):            # 搜索
        print(f"[{art.date}] {art.title}")
```

```python
# 抢课示例
from wzu_scraper.client import WZUClient

with WZUClient() as client:
    client.login_cas("学号", "密码")
    config = client.get_xk_config()

    if config and config.is_open:
        courses = client.query_courses(config, "高等数学")
        if courses:
            tc = courses[0]  # 选第一个教学班
            ok, msg, attempts = client.grab_course(
                config,
                tc,
                max_attempts=100,
                interval=0.3,
                jitter=0.1,
            )
            print(f"{'成功' if ok else '失败'}: {msg} (尝试 {attempts} 次)")

    for tc in client.get_selected_courses():
        print(f"已选: {tc.course_name} - {tc.class_name}")
```

## 项目结构

```
wzu-scraper/
├── main.py                  # CLI 入口，交互式菜单
├── wzu_scraper/
│   ├── client.py            # CAS 登录 + 教务系统 API（课表/成绩/选课）
│   ├── crypto.py            # AES-ECB 加密（匹配前端 CryptoJS）
│   ├── exporters.py         # CSV/JSON/ICS 导出工具
│   ├── xk.py                # 选课/抢课模块（逆向自 zzxkYzb.js）
│   ├── cms.py               # 通用 CMS 爬虫（支持 7 个站点 7 种模板）
│   └── cms_parsers.py       # CMS 列表页解析器（7 种 HTML 模板）
├── docs/
│   └── technical-analysis.md # 技术分析：登录流程逆向、安全分析、CMS 架构
├── .env                     # 账号密码（不进 git）
├── .cookies.json            # Session 持久化（不进 git）
└── data/                    # 爬取的文章数据库（不进 git）
```

## 技术细节

详见 [docs/technical-analysis.md](docs/technical-analysis.md)，包括：

- CAS 单点登录的完整 9 步跳转链
- AES-ECB 密码加密的逆向分析（以及为什么它形同虚设）
- 正方教务系统 API 结构（gnmkdm 编码、学期参数等）
- 课表 / 考试查询接口和导出格式（CSV/JSON/ICS）
- 选课系统 API 逆向（从 zzxkYzb.js 提取的接口和参数）
- 已选课程右侧面板解析、定时开抢和余量提醒策略
- 博达站群 CMS 的 7 种列表模板格式
- 安全漏洞分析和日常使用建议

## 注意事项

- 本项目仅用于个人学习和研究，请勿用于任何恶意用途
- 请勿高频请求，对学校服务器友好一点
- 你的密码只存在本地 `.env` 文件中，不会上传到任何地方
