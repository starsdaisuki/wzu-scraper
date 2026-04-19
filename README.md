# WZU Scraper - 温州大学教务系统爬虫

自动登录温州大学 CAS 统一认证平台，爬取正方教务系统的课程表、成绩等数据。

## 功能

- CAS 单点登录（自动处理 AES 加密、CSRF、OAuth2 跳转）
- Cookie 持久化（登录一次，后续自动复用 session）
- 查询课程表
- 查询成绩（支持按学年学期筛选）
- 查询个人信息

## 快速开始

### 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器

### 安装

```bash
git clone git@github.com:starsdaisuki/wzu-scraper.git
cd wzu-scraper
uv sync
```

### 配置

创建 `.env` 文件（不会被 git 跟踪）：

```
WZU_USERNAME=你的学号
WZU_PASSWORD=你的密码
```

或者运行时手动输入也可以。

### 运行

```bash
uv run python main.py
```

如果配置了 alias（在 `~/.zshrc` 中）：

```bash
alias wzu='cd ~/Documents/projects/WZU/wzu-scraper && uv run python main.py'
```

直接敲 `wzu` 就行。

### 作为库使用

```python
from wzu_scraper.client import WZUClient

with WZUClient() as client:
    client.login_cas("学号", "密码")
    
    # 获取课程表
    courses = client.get_course_schedule("2025-2026", "2")
    for c in courses:
        print(f"{c['weekday']} {c['name']} {c['teacher']} {c['location']}")
    
    # 获取全部成绩
    grades = client.get_grades("", "")
    for g in grades:
        print(f"{g['name']} {g['grade']} GPA:{g['gpa_point']}")
```

## 项目结构

```
wzu-scraper/
├── main.py                  # CLI 入口，交互式菜单
├── wzu_scraper/
│   ├── __init__.py
│   ├── client.py            # 核心：CAS 登录 + 教务系统 API
│   └── crypto.py            # AES-ECB 加密（匹配前端 CryptoJS）
├── .env                     # 账号密码（不进 git）
├── .cookies.json            # Session 持久化（不进 git）
└── docs/
    └── technical-analysis.md # 技术分析文档
```

## 注意事项

- 本项目仅用于个人学习和研究
- `.env` 和 `.cookies.json` 包含敏感信息，已在 `.gitignore` 中排除
- Session 通常几小时内有效，过期后会自动重新登录
- 请勿高频请求，对学校服务器友好一点
