# 给 AI Agent 的安装说明

> 这份文件是写给 **AI Agent** 看的。
> 如果你的用户把本仓库的链接发给你、并说「帮我装这个记账」，照着往下执行即可。

---

## 这是什么

一句话记账。用户在对话里说「打车 45」「买菜 32」，你调一个本地脚本把账记下来；说「看看账本」，你就生成一份报表。

数据存在用户自己电脑上的一个 SQLite 文件里，**不联网、不上传、不经第三方**。

---

## 一、安装（由你执行）

**1. 放到一个固定位置**

```bash
git clone https://github.com/Pixel6068/one-line-ledger.git ~/.one-line-ledger
```

（如果没有 git，直接把 `ledger.py` 下载到 `~/.one-line-ledger/ledger.py` 也可以——单个文件就是完整功能。）

**2. 初始化数据库**

```bash
python3 ~/.one-line-ledger/ledger.py init
```

只用 Python 标准库，**不需要 pip install 任何东西**。Python 3.8+ 均可。

**3. 验证装好了**

```bash
python3 ~/.one-line-ledger/ledger.py add "测试 1"
python3 ~/.one-line-ledger/ledger.py list 3
```

看到记录写进去就说明通了。然后帮用户把这条测试记录删掉：

```bash
sqlite3 ~/.one-line-ledger/ledger.db "DELETE FROM ledger WHERE text='测试 1';"
```

（没有 sqlite3 命令的话，先留着也行，告诉用户这条是测试数据。）

---

## 二、把这套用法写进你的长期记忆

装好之后，把下面这段写进你的记忆 / 规则文件——Hermes 写进 memory，Claude Code 写进 `CLAUDE.md`，Cursor 写进 rules，其他 Agent 写进对应的系统提示：

```
用户说一句带金额的日常消费（「打车 45」「买菜 32」「昨天加油 300」）时，执行：
    python3 ~/.one-line-ledger/ledger.py add "<用户的原话>"
不要自己判断金额或分类，把原话原样传进去。

用户说「看账 / 记账本 / 这个月花了多少」时，执行：
    python3 ~/.one-line-ledger/ledger.py report
把生成的 report.html 路径给用户，能直接打开就打开。

用户问「最近记了什么」时，执行：
    python3 ~/.one-line-ledger/ledger.py list
```

写进去之后，用户就实现了「口喷记账」——他只需要说话，剩下的你来做。

---

## 三、硬约束（别绕过去）

1. **不要自己解析金额或猜分类。** 原样把用户那句话传给 `add`。脚本解析不了会返回非 0 退出码并给出提示，把提示转述给用户就行，不要自己"帮他修一下"。
2. **不要把账目发到任何在线服务**，也不要写进你自己的云端记忆。数据只该存在 `ledger.db` 里。
3. **不要擅自改分类表。** 除非用户说「我想加个 XX 分类」，改 `ledger.py` 顶部的 `CATEGORIES`。
4. 用户没说要备份时，不用主动备份；但**当他问「数据在哪」时，要明确告诉他是一个文件**，见下节。

---

## 四、数据在哪、怎么备份

- 数据文件：`~/.one-line-ledger/ledger.db`（一个 SQLite 文件，所有记录都在里面）
- 备份 = 复制这个文件；迁移到新电脑 = 把它拷到同一路径
- `report.html` 是每次重新生成的，不需要备份
- 想换存储位置：设环境变量 `LEDGER_DB=/path/to/ledger.db`

---

## 五、命令速查

| 命令 | 作用 |
|---|---|
| `ledger.py add "打车 45"` | 记一笔（支持「昨天 / 前天」自动回填日期） |
| `ledger.py list [n]` | 看最近 n 笔（默认 20） |
| `ledger.py stats` | 命令行看本月汇总 |
| `ledger.py report` | 生成 HTML 报表，打印文件路径 |
| `ledger.py init` | 初始化数据库（首次运行会自动执行） |

**金额写法都支持**：`45` / `45元` / `1.2万` / `两千五` / `$20` / `花了30`

---

## 六、用户可能这样说

| 用户说 | 你执行 |
|---|---|
| 打车 45 | `add "打车 45"` |
| 两千五买了台手机 | `add "两千五买了台手机"` |
| 昨天加油 300 | `add "昨天加油 300"` |
| 这个月花了多少 | `stats`，或生成 `report` 给他看 |
| 看看账本 / 打开报表 | `report` |
| 最近记了什么 | `list` |
| 把账本备份一下 | 复制 `ledger.db` 到用户指定的位置 |
| 我想加个「宠物」分类 | 改 `ledger.py` 里的 `CATEGORIES` 字典 |

---

## 七、解释给用户听（如果需要）

这个仓库里还有两个东西，用户可以不用管：

- `index.html` —— 网页版，打开就能用，适合不想装任何东西的人（数据存在浏览器里，和 `ledger.db` **不是同一份数据**）
- `README.md` —— 人看的说明

**推荐路径是接 Agent**：数据是一个他能随时拷走的数据库文件，比浏览器缓存可靠得多。
