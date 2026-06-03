# xbot — X 自动浏览评论

**xbot** 帮你在 X（Twitter）上批量、半自动地参与中文讨论，而不必逐条手动刷帖、写评论。

运行后工具会：

1. 启动或连接 xbot 专用 Chrome（不影响日常浏览器），用 cookies 保持登录；
2. 滚动浏览时间线，抓取中文帖及浏览量；
3. 对符合条件的帖子，调用你在 `.env` 里配置的 LLM API 生成评论；
4. 自动点击回复并发布（也可 `--dry-run` 只看生成结果、不发送）。

模型通过 OpenAI 兼容接口接入（API Key、Base URL、模型名均在 `.env` 配置，可按需更换服务商）。评论风格由本地 `comment_style.md` 和范例文件定义，不会进 Git 仓库。已评论记录、手动回复同步、回复串查重等功能，用于避免对同一帖重复评论。

技术栈：Chrome CDP · Playwright · OpenAI 兼容 LLM API · Python

> **免责声明：** 该项目仅供技术研究与学习，因使用该脚本导致的封号风险由使用者自行承担。

## 快速开始

```bat
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
```

编辑 `.env`（LLM API、cookies、CHROME_PROXY 等）。

**配置评论风格**（本地私有，默认不在仓库里）：

```bat
copy data\comment_style.md.example data\comment_style.md
copy data\comment_style_examples.md.example data\comment_style_examples.md
```

然后编辑这两个文件，定义你的立场、语气和范例。没有它们程序也能跑，但评论会是通用 AI 语气。

```bat
python run.py
```

或 `run.bat` / `scripts\run_auto_comment.bat`

## 常用参数

```bat
python run.py --dry-run
python run.py --skip-chrome
python run.py --max-comments 3
```

配置项见 `.env.example`。

## 评论风格文件

两个文件控制 AI 怎么写评论，**建议只放本地、不要提交仓库**（已在 `.gitignore`）。

| 文件 | 作用 |
|------|------|
| `data/comment_style.md` | 人设、立场、语气、禁止说法（Markdown 自由写） |
| `data/comment_style_examples.md` | few-shot 范例：「原帖大意 → 我的评论」 |

### `comment_style.md` 写什么

任意 Markdown，整段会作为 system prompt 里的「用户风格说明」。建议包含：

- **人设**：说话像什么人、什么场合该硬/该软
- **语气**：是否口语化、是否允许脏字及频率
- **核心观点**：常遇话题的立场（越具体越好）
- **求助帖规则**：真诚提问时帮解释，不嘲讽提问者
- **禁止说法**：踩了就算失败的句式

缺文件时不报错，但只剩代码里的通用规则，评论会偏「套话 AI」。

### `comment_style_examples.md` 格式

每条范例一个块，**块与块之间用单独一行的 `---` 分隔**：

```markdown
---
原帖大意：作者求助，说某段话看不懂。
我的评论：看不懂正常，核心其实在讲……你卡住的可能是中间那个概念。

---
原帖大意：某帖逻辑明显有问题还在带节奏。
我的评论：这说法把因果搞反了，根因不在这。
```

规则（与 `utils/comment_utils.py` 解析一致）：

- 必须含 `我的评论：` 或 `我的评论:`
- `#` 开头段落、含「在此粘贴」「在此写你会」的占位块会被跳过
- 默认取**最后 4 条**有效范例

文件可放在任意路径，在 `.env` 指定：

```env
COMMENT_STYLE_PATH=D:/private/my_style.md
COMMENT_STYLE_EXAMPLES_PATH=D:/private/my_examples.md
COMMENT_STYLE_EXTRA=一两句临时补充
```

## 目录

| 路径 | 说明 |
|------|------|
| `run.py` | 一键入口 |
| `scripts/auto_browse_comment.py` | 主逻辑 |
| `scripts/start_chrome_cdp.ps1` | xbot 专用 Chrome（CDP） |
| `data/comment_style.md.example` | 风格模板（复制后编辑） |
| `data/comment_style_examples.md.example` | 范例模板（复制后编辑） |
| `data/published_log.json` | 已评论记录（本地） |
