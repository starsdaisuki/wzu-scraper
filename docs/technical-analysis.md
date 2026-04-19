# 温州大学教务系统技术分析

> 2026-04-19 逆向分析记录
>
> 分析方法：浏览器 HAR 抓包 + 页面源码逆向 + API 探测
>
> 本文既是技术文档也是科普文档，尽量让非 CS 背景的人也能看懂。

---

## 一、温州大学的网络系统长什么样？

温州大学有一堆独立的系统，由不同公司/部门开发和维护，通过 CAS 单点登录勉强串在一起：

```
┌──────────────────────────────────────────────────────────────────┐
│                        你的浏览器                                 │
└──────┬──────────────┬──────────────┬──────────────┬──────────────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────┐
│ WebVPN   │   │ CAS 认证  │   │ 正方教务  │   │ 博达站群 CMS  │
│ 校外代理  │   │ 身份验证   │   │ 课表/成绩  │   │ 学院网站×7   │
│          │   │          │   │          │   │              │
│ 可能是    │   │ 联奕 公司  │   │ 正方 公司  │   │ 博达 公司    │
│ Ruby on  │   │ LinkID   │   │ ZFSoft   │   │ 各学院自己    │
│ Rails    │   │ Spring   │   │ jQuery   │   │ 定制前端     │
├──────────┤   ├──────────┤   ├──────────┤   ├──────────────┤
│ 218.75.  │   │ 210.33.  │   │ 210.33.  │   │ 各学院域名    │
│ 27.184   │   │ 46.28    │   │ 46.28    │   │ 公网可访问    │
│ 中国电信  │   │ CERNET   │   │ CERNET   │   │              │
│ 温州      │   │ 教育网    │   │ 教育网    │   │              │
└──────────┘   └──────────┘   └──────────┘   └──────────────┘
```

**有趣的发现**：WebVPN 服务器放在电信网（218.75.27.184）而不是教育网，说明运维考虑到了学生在家用电信/联通宽带访问的速度。这是个聪明的决定。

### 为什么登录教务系统要登录两次？

这不是安全需要，是**两个公司的系统没整合好**：

```
门户 (hall.wzu.edu.cn) → 联奕公司做的
教务 (jwxt.wzu.edu.cn) → 正方公司做的
```

虽然两边都接了 CAS 统一认证，但门户登录拿到的 session，教务系统不认。所以你得再认证一次。

技术上完全可以一次登录直达 — 我们的爬虫就是这么干的：直接构造 `service=jwxt` 的 CAS 登录 URL，跳过门户，一步到位。但学校 IT 可能改不了（合同问题）或者懒得改。

### WebVPN 到底是啥？跟我上网有关系吗？

**一句话：学校版的网页代理。**

学校有些系统只能在校园网内部访问（比如图书馆数据库），你在家用 4G 访问不了。WebVPN 是学校在公网放的一个"传话人"：

```
你的电脑 → webvpn.wzu.edu.cn（传话人）→ 校内系统
```

就像你让在学校的朋友帮你去图书馆查一本书然后拍照发给你。

**对日常上网完全没影响**：它只在你主动打开 `webvpn.wzu.edu.cn` 时才工作，不会代理你的其他流量，不会影响你看 B 站。

**更有趣的发现**：教务系统 `jwxt.wzu.edu.cn` 和 CAS `source.wzu.edu.cn` 从校外都能直接访问，根本不需要 WebVPN。所以大部分学生其实用不到 WebVPN，除非要访问图书馆数据库之类的真正内网资源。

### WebVPN 的 URL 重写规则

WebVPN 把校内地址编码成了一种特殊的 URL 格式：

```
原始地址:   https://source.wzu.edu.cn/login
WebVPN:    https://source-443.webvpn.wzu.edu.cn/login
                   ^^^^^^ ^^^
                   域名    端口
```

规则：`{域名中的点换成横杠}-{端口}.webvpn.wzu.edu.cn`

| 原始地址 | WebVPN 地址 |
|---------|-----------|
| `source.wzu.edu.cn:443` | `source-443.webvpn.wzu.edu.cn` |
| `hall.wzu.edu.cn:443` | `hall-443.webvpn.wzu.edu.cn` |
| `192.168.9.92` | `192-168-9-92.webvpn.wzu.edu.cn` |

WebVPN 上有 **114 个内部服务** 的入口，包括门户、教务、图书馆、心理测评、体质测试、运动啦、上课啦、离校系统……基本上是个校内系统大全。

### 换 IP / 换网络会怎样？

**完全没影响。** 认证是基于 cookie，不绑定 IP。从 WiFi 切到 4G、换了地方连网，只要浏览器 cookie 还在就行。Session 一般几小时有效，过期了重新登录即可。

---

## 二、CAS 登录流程：一次登录到底发生了什么？

CAS (Central Authentication Service) 是大学常用的单点登录协议。温州大学用的是**联奕 LinkID** 的 CAS 实现，基于 Spring WebFlow + Apereo CAS。

### 2.1 用浏览器登录时的完整跳转链

我们用 HAR 抓包记录了从打开登录页到进入教务系统的每一个 HTTP 请求。整个过程有 **9 次跳转**：

```
1. GET source.wzu.edu.cn/login?service=jwxt.wzu.edu.cn/sso/zfiotlogin
   │
   │  浏览器收到登录页 HTML（21KB），里面嵌入了：
   │  ├── execution token（Spring WebFlow 状态，约 6000 字符的 Base64 数据）
   │  ├── login-croypto（AES 密钥，16 字节的 base64）
   │  └── 6 个 CryptoJS 加密库（md5、core、aes、ecb、pkcs7……）
   │
2. 浏览器端 JS 加密密码（详见下文）
   │
3. POST source.wzu.edu.cn/login
   │  提交：学号 + 加密后的密码 + AES 密钥 + execution token
   │
   │  302 重定向 ↓
4. GET source.wzu.edu.cn/oauth2.0/callbackAuthorize?client_id=menhu&code=OC-xxxxx
   │  302 ↓
5. GET source.wzu.edu.cn/oauth2.0/authorize?code=...
   │  302 ↓
6. GET jwxt.wzu.edu.cn/sso/zfiotlogin?ticket=ST-xxxxx  ← CAS 票据诞生
   │  302 ↓（注意！这里跳到了 HTTP！）
7. GET http://jwxt.wzu.edu.cn/sso/zfiotlogin           ← 明文传输！
   │  307 ↓（再跳回 HTTPS）
8. GET https://jwxt.wzu.edu.cn/jwglxt/ticketlogin?uid=学号&timestamp=xxx&verify=MD5
   │  302 ↓
9. GET jwxt.wzu.edu.cn/jwglxt/xtgl/index_initMenu.html ← 终于进来了！
```

一共 176 个 HTTP 请求，光是加载登录页就发了 **74 个请求**（JS、CSS、图片、各种 API 配置调用）。登录页调用了 16 次 `/linkid/protected/api/dictconfig/get` 来获取各种配置——完全可以合并成一个请求，但它偏要调 16 次。

### 2.2 密码到底怎么加密的？

登录页加载了 6 个 CryptoJS 库文件来加密密码：

```
/public/crypto/md5.min.js
/public/crypto/core.min.js
/public/crypto/crypto-js.min.js
/public/crypto/enc-base64.min.js
/public/crypto/mode-ecb.min.js       ← ECB 模式（最弱的 AES 模式）
/public/crypto/pad-pkcs7.min.js      ← PKCS7 填充
```

从混淆的 `deploy.js` 中逆向提取出的加密函数：

```javascript
aesEncrypt = function(key, plaintext) {
    const keyBytes = CryptoJS.enc.Utf8.parse(key);
    const encrypted = CryptoJS.AES.encrypt(plaintext, keyBytes, {
        mode: CryptoJS.mode.ECB,    // ECB 模式：相同输入 → 相同输出
        padding: CryptoJS.pad.Pkcs7
    });
    return encrypted.toString();     // 返回 base64
}
```

然后看看实际发送的 POST 数据：

```
username:  2021XXXXXXX                    ← 学号，明文
password:  wL0fY8X1cSa0DAmA69tviQ==      ← AES 加密后的密码
croypto:   hz/gCMdUIwkABYwSC1fvLQ==      ← 加密用的 AES 密钥
execution: 42154002-b6ee-4274-b14b-...    ← 6041 字符的 Spring WebFlow token
```

**问题来了**：密钥（`croypto`）和密文（`password`）一起发给了服务器。这就像你把保险箱和钥匙绑在一起寄快递，快递员想打开就能打开。

为什么说这个加密**形同虚设**？

1. 密钥和密文一起传输 → 拦截者同时拿到两个，直接解密
2. 使用 AES-ECB 模式 → 最弱的分组模式，相同明文永远产生相同密文
3. 密钥是前端随机生成的 → 服务器不可能提前知道密钥，所以密钥必须随请求发送

**那为什么还要加密？** 真正保护你密码的是 HTTPS（传输层加密），AES 只是多套了一层"装饰"。可能是甲方要求"密码必须加密传输"，开发者就加了个 AES 应付需求，虽然从密码学角度来看毫无意义。

**实际风险**：低。只要你不在恶意 WiFi（比如被人做了 HTTPS 中间人攻击的）上登录，密码就是安全的。

### 2.3 "croypto" — 从未被修复的拼写错误

页面 HTML 里有这个隐藏字段：

```html
<p id="login-croypto">MoeJ5/QDeqBaXHGMR9A1dg==</p>
```

`croypto`，不是 `crypto`。这个拼写错误出现在：

- HTML 的 id 属性里
- POST 表单的字段名里
- 后端接收参数的代码里

也就是说前端和后端都用了这个错误的拼写，而且从来没人改过。联奕 LinkID 这套 CAS 系统被全国很多高校使用，这个 typo 可能到处都是。

### 2.4 execution token：6000 字符的怪物

登录表单里最大的字段是 `execution`，大约 6000 字符，长这样：

```
42154002-b6ee-4274-b14b-444e9698f88f_H4sIAAAAAAAAAKU6a4wbx3lzvPdD...
```

前半部分是 UUID，后半部分是 Base64 编码的 GZip 压缩的 **Java 序列化数据**。这是 Spring WebFlow 框架的设计：把服务器端的会话状态序列化后塞给客户端（类似 ASP.NET 的 ViewState）。好处是服务器不用存状态，坏处是每次请求都要传 6KB 的垃圾数据。

### 2.5 验证码机制

登录页调用了一个 API 来决定是否弹验证码：

```
GET /api/protected/user/findCaptchaCount/学号
```

返回该学号的错误登录次数，低于阈值就不弹验证码。正常使用基本不会触发。

同时页面配了 Google reCAPTCHA v3（无感验证，用户看不到），但实际上对简单的 HTTP 请求爬虫**没有强制检查**。我们的爬虫从来没被验证码拦过。

### 2.6 登录后的 19 种第三方登录

CAS 登录页还支持 **19 种第三方 OAuth 登录**：微信、QQ、钉钉、飞书、支付宝、企业微信……基本上国内能想到的社交平台都接了。每种登录都会把你的身份信息传给对应平台。

### 2.7 一个实战坑：别只看跳转 URL 判断登录成功

刚开始写爬虫时，很容易偷懒：只要重定向 URL 里出现了 `jwxt.wzu.edu.cn`、`index`、`zfiotlogin` 之类的字符串，就当作登录成功。

但温州大学这套链路里，**登录页自己的 URL** 就会带上：

```text
https://source.wzu.edu.cn/login?service=https://jwxt.wzu.edu.cn/sso/zfiotlogin
```

也就是说，哪怕你还停留在 CAS 登录页，URL 字符串里也已经出现了 `jwxt.wzu.edu.cn/sso/zfiotlogin`。如果只是做字符串包含判断，很容易把"还没登录成功"误判成"已经进教务了"。

更稳妥的做法是两步：

1. 先严格检查当前响应的 **host 和 path**，确认它真的落到了 `jwxt.wzu.edu.cn`
2. 再请求一个已登录页面做最终确认，例如 `/jwglxt/xtgl/index_cxYhxxIndex.html`

我们的实现后来就是这样改的：**redirect URL 只能做初筛，真正的登录成功必须靠已登录接口验证。**

---

## 三、正方教务系统：全国高校的"远古神器"

正方 (ZFSoft) 教务系统是国内高校最广泛使用的教务管理系统，温州大学用的版本代号 `zftal-ui-v5-1.0.2`。前端技术栈：jQuery + Bootstrap + jqGrid — 上一代 Web 技术的全明星阵容。

### 3.1 API 结构

正方系统的 API 遵循一个固定的 URL 模式：

```
POST /jwglxt/{模块}/{功能}_{操作}.html?gnmkdm={功能模块代码}
```

我们通过调用菜单 API `/xtgl/index_cxMenuList.html` 发现了所有可用的功能模块：

| 功能 | URL | gnmkdm | 说明 |
|------|-----|--------|------|
| 个人课表 | `/kbcx/xskbcx_cxXsgrkb.html` | **N2151** | 返回 JSON |
| 成绩查询 | `/cjcx/cjcx_cxDgXscj.html` | N305005 | 返回 JSON |
| 考试查询 | `/kwgl/kscx_cxXsksxxIndex.html` | N358105 | 返回 JSON |
| 班级课表 | `/kbdy/bjkbdy_cxBjkbdyIndex.html` | N214505 | 返回 HTML |
| 选课确认 | `/kbcx/xskbqr_cxXskbqrIndex.html` | N2158 | 返回 HTML |

**踩坑经历**：网上很多正方系统的教程用 `gnmkdm=N253508` 来查课表，但在温州大学返回"没有访问权限！"。折腾了一圈才发现温州大学的课表 gnmkdm 是 `N2151`。**不同学校的 gnmkdm 编码不同！** 正确的做法是先调用菜单 API 获取当前学校的编码。

### 3.1.1 考试查询接口

考试安排接口和成绩查询很像，也是一个标准的 JSON 列表接口：

```text
POST /jwglxt/kwgl/kscx_cxXsksxxIndex.html?doType=query&gnmkdm=N358105
```

请求体里最关键的还是 `xnm` 和 `xqm`：

```python
{
    "xnm": "2025",
    "xqm": "3",   # 秋季学期
    "ksmcdm": "",
    "queryModel.showCount": "50",
    "queryModel.currentPage": "1",
}
```

返回字段里最有用的是：

- `kcmc`：课程名
- `kssj`：考试时间，格式像 `2026-01-19(09:00-11:00)`
- `cdmc` / `cdxqmc`：考场和校区
- `zwh`：座位号
- `ksmc`：考试名称（比如公共课期末考试）
- `jsxx`：教师信息

因为 `kssj` 已经带了具体日期和开始结束时间，所以考试安排特别适合导出成 `ICS`，直接塞进系统日历里。

课程表虽然接口里没有直接返回具体日期，但它给了三样足够关键的信息：

- `xqjmc`：星期几
- `jcor`：第几节课
- `zcd`：第几周上课

所以只要用户额外告诉程序“**第 1 周周一是哪一天**”，就能把整学期课表展开成一串具体日期的日历事件。也就是说，课表 `ICS` 的本质不是截图式导出，而是把“周课表”变成真正可导入日历的时间序列。

### 3.1.2 选课接口和余量监控

这次新增的选课模块用的是正方的 `zzxkYzb` 这一套接口，核心入口页是：

```text
GET /jwglxt/xsxk/zzxkyzb_cxZzxkYzbIndex.html?gnmkdm=N253512
```

这个页面会塞进一堆隐藏字段，像：

- `xkkz_id`
- `xkxnm`
- `xkxqm`
- `kklxdm`
- `njdm_id`
- `zyh_id`
- `iskxk`

这些字段就是后续所有选课/退课/查询教学班请求的上下文。`iskxk=0` 时，页面会直接显示：

```text
对不起，当前不属于选课阶段，如有需要，请与管理员联系！
```

所以一个健壮的客户端不能只看 HTTP 200，而要额外判断这些隐藏字段是否完整，否则很容易拿着一组空参数继续乱发请求。

教学班搜索接口是：

```text
POST /jwglxt/xsxk/zzxkyzbjk_cxJxbWithKchZzxkYzb.html?gnmkdm=N253512
```

真正容易漏掉的是右侧“已选课程”面板。前端 `zzxkYzb.js` 不是直接把它写死在 index 页里，而是在页面加载后又额外发了一次：

```text
GET /jwglxt/xsxk/zzxkyzb_cxZzxkYzbChoosed.html
```

返回的是一段 HTML 片段，不是 JSON。里面每个已选教学班都会带一组隐藏字段和一个退课按钮：

```javascript
cancelCourseZzxk('leftpage', jxb_id, do_jxb_id, kch_id, jxbzls, xkkz_id)
```

也就是说，退课并不是只靠 `jxb_id` 就够，至少还要把 `do_jxb_id`、`kch_id` 和 `xkkz_id` 这些参数一起拿出来。单纯复用“搜索结果列表”来做退课，在语义上其实是不稳的。

### 3.1.3 抢课策略和提醒

最初版的抢课逻辑只是“固定间隔无限重试”，能用，但很傻。后来补成了三个更实用的点：

1. **定时开抢**：CLI 支持输入 `HH:MM[:SS]`，到点再开始发第一次请求，适合整点放课。
2. **随机抖动**：每次重试在固定间隔上加一个小的随机延迟，避免请求节奏过于机械。
3. **余量提醒**：余量监控发现空位后，除了 CLI 打印，还可以走铃声、macOS 桌面通知，或者 Telegram Bot 推送。

这里的提醒系统本质上只是外挂在轮询逻辑外面的 notifier，不改变选课接口本身。好处是：即使以后要接别的提醒渠道（邮件、企业微信、Server 酱），也不需要重写监控主循环。

后来 CLI 里又补了两个很实用但实现成本不高的增强：

1. **多门课同时监控**：一次选多个教学班，主循环逐个查询并分别判断余量。
2. **JSONL 日志**：每次轮询都会落一条结构化记录，方便后面统计“哪门课最容易掉人”或者回放抢课过程。

这种设计的好处是：提醒、自动抢课、日志记录三件事被拆成了相对独立的层。轮询逻辑只负责得到“当前余量是多少”，至于要不要提醒、要不要写日志、要不要自动发起选课请求，都是在外层做决策。

查询教学班的接口是：

```text
POST /jwglxt/xsxk/zzxkyzbjk_cxJxbWithKchZzxkYzb.html?gnmkdm=N253512
```

真正提交选课/退课时，除了 `kch_id` 和选课上下文，还要特别注意 `do_jxb_id`。前端页面的按钮处理函数会同时传 `jxb_id` 和 `do_jxb_id`，所以逆向时不能只盯着一个教学班 ID。

现在项目里的“课程余量监控”本质上还是一个轻量原型：它靠定时重查教学班列表来观察 `yxzrs/jxbrl` 是否出现空位，然后在控制台提示，或者立刻调用选课接口尝试抢位。它已经能用来蹲位，但还没有做到真正意义上的通知系统。

### 3.2 学期参数的迷惑编码

正方系统的学期参数编码是个谜：

| 参数 | 含义 | 编码 |
|------|------|------|
| `xnm` | 学年 | 起始年份，如 2025-2026 学年填 `2025` |
| `xqm` | 学期 | `3` = 秋季学期, `12` = 春季学期, `16` = 暑期 |

为什么学期用 3、12、16？没人知道。这三个数字没有任何明显的数学关系。猜测是早期版本用的某种内部枚举值，后来改不掉了。

### 3.2.1 个人信息页的真实 DOM 结构

教务系统的"个人信息"页不是 JSON API，而是直接返回一段 HTML。实际页面里，核心信息长这样：

```html
<h4 class="media-heading">姓名&nbsp;&nbsp;学生</h4>
<p>学院 班级</p>
```

例如实测页面会是：

```html
<h4 class="media-heading">张三&nbsp;&nbsp;学生</h4>
<p>数理学院 23统计1</p>
```

这里有两个实际经验：

1. 姓名和角色被塞在同一个 `<h4>` 里，中间是 `&nbsp;&nbsp;`
2. 学院和班级通常放在紧跟着的第一个 `<p>` 里

所以如果要解析这个页面，不能假设它会出现 `用户名：张三` 这种特别规整的文本，而应该按 DOM 结构来取值。这个细节后来也被补进了测试夹具里，避免测试用假数据把真实回归掩盖掉。

### 3.3 CSRF 防护的漏洞

正方系统有 CSRF token：

```html
<input type="hidden" id="csrftoken" name="csrftoken" 
       value="2dc6ae6c-e4ce-4599-bfb3-f480abb0b263,..."/>
```

但这个 token 只在普通页面请求时检查，**AJAX 请求完全不检查**：

```
普通请求（无 X-Requested-With 头）→ 检查 CSRF → 失败返回错误页面
AJAX 请求（有 X-Requested-With 头）→ 不检查 CSRF → 直接返回 JSON
```

这意味着我们的爬虫只需要加一个请求头就能绕过所有 CSRF 防护：

```python
headers={"X-Requested-With": "XMLHttpRequest"}
```

**这有什么风险？** CSRF（跨站请求伪造）是指：你在登录教务系统的状态下，打开了一个恶意网页，那个网页可以"假装是你"向教务系统发请求（比如帮你选课、改信息）。不过浏览器的同源策略（CORS）会阻止大部分跨域 AJAX 请求，所以实际利用难度不低。但如果教务系统配置了宽松的 CORS 头，那就真的危险了。

### 3.4 登录跳转中的明文传输

登录成功后的跳转链里有两个安全问题：

**问题一**：学号和 MD5 出现在 URL 里

```
/jwglxt/ticketlogin?uid=学号&timestamp=1776574665&verify=MD5哈希
```

浏览器历史记录、服务器日志、Referer 头都能看到你的学号。不过好消息是 verify 是一次性的（跟时间戳绑定），过期就没用了。

**问题二**：HTTP→HTTPS 跳转缝隙

```
jwxt.wzu.edu.cn/sso/zfiotlogin?ticket=ST-xxxxx
  302 → http://...     ← 这一步是 HTTP 明文！CAS ticket 裸奔了一瞬间
    307 → https://...   ← 才跳到 HTTPS
```

教务系统同时监听 80 和 443 端口，没有在前端代理层强制 HTTPS。CAS ticket 在明文中传输了一瞬间，理论上可以被校园网内的 ARP 欺骗截获。但 ticket 是一次性的，攻击者需要在那一瞬间截获并使用，实际操作难度很高。

### 3.5 API 返回数据结构

课程表 API 返回的 JSON：

```json
{
  "kbList": [
    {
      "kcmc": "高等数学A(一)",    // 课程名称
      "xm": "张三",              // 教师姓名
      "cdmc": "南1-A101",        // 上课地点
      "xqjmc": "星期一",          // 星期几
      "jcor": "1-2",            // 第几节课
      "zcd": "1-16周",           // 上课周次
      "xf": "4.0",              // 学分
      "kcxzmc": "必选课"          // 课程性质
    }
  ],
  "xsxx": { ... },              // 学生信息
  "xqjmcMap": { ... },          // 星期映射
  "sjkList": [ ... ]            // 时间框列表
}
```

成绩 API 返回的 JSON：

```json
{
  "items": [
    {
      "kcmc": "大学英语(一)",     // 课程名称
      "cj": "85",               // 成绩
      "jd": "3.50",             // 绩点
      "xf": "4.0",              // 学分
      "kcxzmc": "必选课",         // 课程性质
      "xnmc": "2024-2025",      // 学年
      "xqmmc": "1"              // 学期
    }
  ],
  "totalCount": 30,
  "currentPage": 1
}
```

---

## 四、爬虫怎么做的：绕过层层限制

### 4.1 跳过门户，一步直达

正常用户的访问路径很长：

```
www.wzu.edu.cn → 点"访问内网" → WebVPN → 门户 → 点教务 → 再次登录 → 教务系统
```

我们的爬虫直接构造 CAS 登录 URL：

```python
login_url = "https://source.wzu.edu.cn/login?service=https://jwxt.wzu.edu.cn/sso/zfiotlogin"
```

`service` 参数告诉 CAS "登录成功后跳到哪"，直接跳过门户和 WebVPN。就像你知道教室在哪，直接走过去，不需要先去学校大门看地图。

### 4.2 Python 复现 AES 加密

用 `pycryptodome` 库复现前端的 CryptoJS 加密：

```python
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import os, base64

key = os.urandom(16)                          # 随机生成 16 字节密钥
cipher = AES.new(key, AES.MODE_ECB)           # AES-ECB 模式
padded = pad(password.encode(), AES.block_size) # PKCS7 填充
encrypted = base64.b64encode(cipher.encrypt(padded)).decode()

# POST 时：password=encrypted, croypto=base64(key)
```

### 4.3 Cookie 持久化

登录成功后涉及多个域名的 cookie：

| Cookie | 域名 | 用途 |
|--------|------|------|
| `SESSION` | source.wzu.edu.cn | CAS 会话 |
| `SOURCEID_TGC` | source.wzu.edu.cn | CAS 的 TGC，相当于"记住登录"，**最重要的 cookie** |
| `JSESSIONID` | jwxt.wzu.edu.cn | 教务系统会话 |
| `javajw` | jwxt.wzu.edu.cn | 正方内部会话标识 |

`SOURCEID_TGC` 是单点登录的核心：只要它还有效，访问任何 CAS 保护的系统都自动通过，不用再输密码。

**踩坑**：`source.wzu.edu.cn` 和 `jwxt.wzu.edu.cn` 都设了叫 `JSESSIONID` 的 cookie。用 `dict(client.cookies)` 直接报 `CookieConflict` 错误。解决方法是保存 cookie 时带上 domain 信息。

### 4.4 绕过"没有访问权限"

正方系统对不同请求类型有不同的权限检查。加上一个 HTTP 头就能获取 JSON 数据：

```python
headers = {"X-Requested-With": "XMLHttpRequest"}
```

不加这个头 → 返回"没有访问权限！"的 HTML 错误页
加了这个头 → 返回 JSON 数据

---

## 五、学院网站 CMS：同一套系统，七种写法

温州大学的各学院和部门网站使用同一套 CMS — **博达站群系统**。但每个学院的前端模板不同，导致了相当混乱的 HTML 结构差异。

### 5.1 统一的底层特征

所有学院网站共享这些特征（因为是同一个 CMS）：

- 文章 URL：`info/{分类ID}/{文章ID}.htm`
- 文章内容：`<div class="v_news_content">` 里
- 分页：`{栏目名}/{页码}.htm`（从最大到 1）
- 无需登录，全部公开可访问
- 搜索功能全部失效（`search/tplsearch.jsp` 返回 404）

### 5.2 七种不同的列表 HTML 格式

同一套 CMS，7 个学院，7 种不同的文章列表写法。以下是每种格式的实际 HTML（从真实页面中提取）：

**Style A — 教务处 (jwc.wzu.edu.cn)**
```html
<li>
  <span class="w"><a href="info/1188/38224.htm">标题</a></span>
  <span class="time">2026年01月16日</span>
</li>
```

**Style B — 数理学院 (slxy.wzu.edu.cn)**
```html
<li>
  <a href="../info/1046/37386.htm" title="完整标题">截断的标题...</a>
  <samp>2026年04月14日</samp>    <!-- 用 samp 标签！ -->
</li>
```

**Style C — 生环学院 (shxy.wzu.edu.cn)**
```html
<li data-aos="fade-up">
  <a href="../info/1030/155911.htm" title="完整标题">
    <div class="span flex">
      <h3>标题</h3>
      <span class="flex"><i>17</i>/ 2026-04</span>  <!-- 日/年-月，需要重组 -->
    </div>
  </a>
</li>
```

**Style D — 计算机与人工智能学院 (ai.wzu.edu.cn)**
```html
<li>
  <a href="../info/1337/28100.htm">标题</a>
  <span class="time">2026-04-18</span>    <!-- 类似 A 但没有 span.w 包裹 -->
</li>
```

**Style E — 化学与材料工程学院 (chem.wzu.edu.cn)**
```html
<li>
  <a href="../../info/2536/72678.htm">
    <b class="sl amn4">标题</b>           <!-- 标题和日期都在 <a> 内部 -->
    <span class="amn4">2026-04-17</span>
  </a>
</li>
```

**Style F — 机电工程学院 (jdxy.wzu.edu.cn)**
```html
<div class="main_list_box">
  <a href="info/1641/42700.htm">
    <div class="main_list_time">2026-04-16</div>  <!-- 日期在标题前面 -->
    <div class="main_list_tit">标题</div>
  </a>
</div>
```

**Style G — 建筑工程学院 (cace.wzu.edu.cn)**
```html
<a href="../info/1622/158395.htm">
  <div class="newp">
    <p>标题</p>
    <h4>2026-04-16</h4>    <!-- 日期用 h4 标签 -->
  </div>
</a>
```

七种格式，用了 `<span class="time">`、`<samp>`、`<i>DD</i>/ YYYY-MM`、`<b>` + `<span>`、`<div class="main_list_time">`、`<h4>`……同一个 CMS 的输出格式如此混乱，大概是因为各学院独立定制前端模板，没有统一的前端规范。

### 5.3 已接入的 7 个站点

| 站点 | 域名 | 栏目数 | 列表格式 |
|------|------|--------|---------|
| 教务处 | jwc.wzu.edu.cn | 3 | Style A |
| 计算机与人工智能学院 | ai.wzu.edu.cn | 5 | Style D |
| 化学与材料工程学院 | chem.wzu.edu.cn | 4 | Style E |
| 建筑工程学院 | cace.wzu.edu.cn | 3 | Style G |
| 机电工程学院 | jdxy.wzu.edu.cn | 4 | Style F |
| 生环学院 | shxy.wzu.edu.cn | 5 | Style C |
| 数理学院 | slxy.wzu.edu.cn | 8 | Style B |

共计 **32 个栏目**，爬取了 **654+ 篇文章**，支持跨站全文搜索。

### 5.4 如何添加新学院

由于所有学院都是同一套 CMS，添加新站点只需要在 `cms.py` 中加几行配置：

```python
SITES["new_site"] = SiteConfig(
    key="new_site",
    name="XX学院",
    base_url="https://xxx.wzu.edu.cn",
    categories={
        "xxzx/xydt": "学院动态",
        "xxzx/tzgg": "通知公告",
    },
)
```

不需要写任何新的解析代码 — 解析器会自动尝试 7 种格式，匹配到哪种就用哪种。

### 5.5 为什么自己做搜索？

教务处官网的搜索功能（`search/tplsearch.jsp`）返回 **404**——搜索功能直接挂了，不知道挂了多久，也没人修。

我们的本地搜索：先把所有文章爬到本地 JSON 文件，然后关键词匹配标题和正文。速度快（本地匹配毫秒级）、跨 7 个站点搜索、可离线使用。

---

## 六、WebVPN 的 SSL 和安全头

### SSL 证书

```
签发方:   Let's Encrypt R13（免费证书，但完全合规）
域名:     *.webvpn.wzu.edu.cn（通配符证书）
有效期:   2026-02-26 ~ 2026-05-27（3 个月，需要自动续期）
IPv6:     支持（2001:250:640b:6666:a3e:22::）
```

### HTTP 安全头

| 安全头 | WebVPN | 教务系统 |
|--------|--------|---------|
| HSTS (强制 HTTPS) | 有 (182天) | 无 |
| X-XSS-Protection | 有 | 无 |
| Cache-Control (不缓存) | 有 | 无 |
| Content-Security-Policy | **缺失** | **缺失** |
| X-Frame-Options | **缺失** | **缺失** |

缺少 CSP 和 X-Frame-Options 意味着理论上可以进行点击劫持（clickjacking）攻击 — 把登录页嵌入一个透明的 iframe 里，诱导用户点击。

---

## 七、安全性总评

| 项目 | 评分 | 说明 |
|------|------|------|
| 传输加密 | B | HTTPS 有，但有 HTTP→HTTPS 跳转缝隙 |
| 密码安全 | C | AES 加密形同虚设（密钥随密文一起发送） |
| Session 管理 | B | TGC + JSESSIONID 机制正常，cookie 属性还行 |
| CSRF 防护 | C | 有 token 但 AJAX 请求不检查 |
| URL 安全 | D | 学号、时间戳、MD5 明文出现在 URL 中 |
| 反爬虫 | D | 基本没有。无 WAF、无 rate limiting、验证码阈值极高 |
| 安全头 | C | WebVPN 有部分安全头，教务系统几乎没有 |

### 日常使用建议

| 建议 | 原因 |
|------|------|
| 别在不信任的 WiFi 上登录教务系统 | HTTP 跳转缝隙 + AES 加密是装饰品 |
| 定期清理浏览器历史记录 | URL 里有学号和 token |
| 教务系统用完关掉标签页 | 减少 CSRF 攻击窗口 |
| 教务系统密码别跟其他网站一样 | 万一泄露不会连累其他账号 |
| 教务系统从校外也能直连 | 大部分情况下不需要 WebVPN |

**总的来说**：日常使用不用太担心。这些漏洞的利用门槛都不低，而且学校系统里最值钱的也就是你的成绩和课表，不太会成为攻击目标。

---

## 八、有趣的发现汇总

1. **croypto** — `crypto` 被拼成了 `croypto`，贯穿前后端代码，从未修复
2. **AES 密钥和密文一起发送** — 加密约等于没加密，安全全靠 HTTPS
3. **gnmkdm 各校不同** — 网上教程的 `N253508` 在温州大学返回"没有访问权限"，正确的是 `N2151`
4. **学期编码 3/12/16** — 没人知道为什么正方系统用这三个数字表示三个学期
5. **教务系统先 HTTP 再跳 HTTPS** — CAS ticket 在明文中裸奔了一瞬间
6. **学号和 MD5 出现在 URL 里** — 浏览器历史记录就能看到
7. **教务处搜索 404** — 官方搜索功能直接挂了，不知道挂了多久
8. **CSRF 对 AJAX 不检查** — 加个 `X-Requested-With` 头就绕过了
9. **同一套 CMS 七种 HTML 格式** — 7 个学院，7 种列表模板，没有统一前端规范
10. **WebVPN 放在电信而非教育网** — 运维聪明，学生在家访问更快
11. **登录页发了 16 次配置请求** — 完全可以合并成 1 次
12. **支持 19 种第三方登录** — 微信、QQ、钉钉、飞书、支付宝全接了
13. **WebVPN 有 114 个内部服务** — 校内系统大全
14. **654+ 篇文章跨 7 个站点搜索** — 比任何一个官网的搜索都好用

---

## 九、技术栈推测

| 系统 | 技术栈 | 依据 |
|------|--------|------|
| CAS 认证 | Java (Spring WebFlow + Apereo CAS) | execution token 是 Java 序列化数据 |
| CAS 前端 | Angular (cas-login) | 打包文件名 `main-es2015.xxx.js` |
| 教务系统 | Java (Spring) + jQuery + Bootstrap + jqGrid | 前端 JS 文件名和 API 风格 |
| WebVPN | Ruby on Rails | `/users/sign_in` 路由风格 |
| 学院网站 | 博达站群 CMS (Java) | URL 结构和 JSP 页面 |
| 数据库 | 大概率 Oracle | 正方系统的传统配置 |
| CAS 供应商 | 联奕 LinkID | API 路径 `/linkid/` |
| 教务系统供应商 | 正方 ZFSoft | UI 框架 `zftal-ui-v5` |
