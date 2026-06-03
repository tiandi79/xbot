# 自动评论标记说明（仅你自己看）

脚本发出的评论，会在**文中某个标点后面**插入 **1 个特殊空格**（肉眼像多打了个空格），手动评论没有。

## 规则

```
digest = SHA256(COMMENT_MARKER_SECRET + 帖ID + UTC日期YYYYMMDD)
空格字符 = MARKERS[ digest[0:8] mod 12 ]   （各类 Unicode 空格，不是普通半角空格）
插入位置 = 标点后的候选位置[ digest[8:16] mod 候选数 ]
```

- 插在 **。，！？、** 等标点**后面**，位置随帖子和日期变  
- 用的是 `\u2009` 薄空格、`\u3000` 全角空格等，**不会**动正文里正常的半角空格  

## 配置

```env
COMMENT_MARKER_SECRET=你的私密字符串
COMMENT_MARKER_DISABLED=1
```

## 怎么认

1. 标点旁好像多了一个略宽/略窄的空隙（不仔细看看不出）  
2. `published_log.json` 里有 `"marker"`（Unicode 名）和 `"marker_pos"`  
3. 手动回复无 marker  

## 本地验证

```python
from utils.comment_marker import apply_auto_marker
text, m, pos = apply_auto_marker("看不懂正常，核心是后面那句。", "2061696817775984978")
print(len(text), pos, hex(ord(m)))
```
