# WZU Scraper

> 温州大学教务系统爬虫 + 全站搜索引擎

一键登录温州大学 CAS 统一认证，查课表、查成绩、搜索 7 个学院网站的通知公告。

## 功能

**教务系统**
- 自动登录 CAS（处理 AES 加密 + OAuth2 跳转，登录一次后自动保存 session）
- 查课程表、查成绩（支持按学年学期筛选）

**全站搜索**
- 爬取 7 个学院/部门网站的文章，本地全文搜索
- 支持：教务处、数理学院、计算机与人工智能学院、化学与材料工程学院、建筑工程学院、机电工程学院、生环学院
- 搜索结果可直接查看全文内容

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
3. Student info (个人信息)
4. Website search (网站搜索)    ← 全站搜索在这里
5. Session status
0. Exit
```

进入「网站搜索」后可以：
- 输入关键词跨 7 个网站搜索
- 查看搜索结果的全文内容
- 爬取最新文章更新本地数据库

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

## 项目结构

```
wzu-scraper/
├── main.py                  # CLI 入口，交互式菜单
├── wzu_scraper/
│   ├── client.py            # CAS 登录 + 教务系统 API（课表/成绩）
│   ├── crypto.py            # AES-ECB 加密（匹配前端 CryptoJS）
│   ├── cms.py               # 通用 CMS 爬虫（支持 7 个站点 7 种模板）
│   └── jwc.py               # 教务处爬虫（旧版，已被 cms.py 替代）
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
- 博达站群 CMS 的 7 种列表模板格式
- 安全漏洞分析和日常使用建议

## 注意事项

- 本项目仅用于个人学习和研究，请勿用于任何恶意用途
- 请勿高频请求，对学校服务器友好一点
- 你的密码只存在本地 `.env` 文件中，不会上传到任何地方
