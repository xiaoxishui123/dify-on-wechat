# ChinesePUA 插件（汉语新解）

为中文词语生成讽刺风格的「汉语新解」卡片。

> 本插件基于原作者仓库 [BenedictKing/chinesepua](https://github.com/BenedictKing/chinesepua) 整理改写，
> 已**移除 Claude 依赖**，全部能力统一走一个 OpenAI 兼容接口。

## 功能与触发词

| 触发词 | 功能 |
| --- | --- |
| `解释` / `吐槽` / `PUA` / `槽点` / `新解` | 汉语新解（主功能） |
| `解字` / `字典` / `字源` | 说文解字 |
| `设计` / `名片` | 社交名片 |
| `翻译` | 翻译 |
| `论证` / `分析` | 论证分析 |
| `思考` / `撕考` / `思考者` / `撕考者` | 思考者 |
| `沉思` / `琢磨` / `深度思考` | 沉思者 |
| `概念` / `概念解释` | 概念解释 |
| `哲学` / `哲学家` | 哲学思考 |
| `互联网` / `web2` | 互联网黑话 |
| `知识` / `知识卡` | 知识卡片 |
| `单词` / `单词卡` | 单词卡片 |

用法示例：`解释 金融杠杆`、`吐槽 内卷`、`解字 仁`。
关键词需包含中文字符且长度不超过 10。

## 安装

1. 将插件目录放入项目的 `plugins/` 下
2. `pip install -r requirements.txt`
3. `playwright install chromium`
4. 填写 `config.json`
5. 重启程序

## 配置

配置读取顺序与 `JinaSum` 等插件一致：

1. **优先**：项目根目录下 `plugins/config.json` 中 `chinesepua` 段
2. 回退：`plugins/chinesepua/config.json`
3. 再回退：`plugins/chinesepua/config.json.template`

推荐直接写在 `plugins/config.json`（与其它插件的 API 配置放在一起）：

```json
"chinesepua": {
    "open_ai_api_base": "https://api.siliconflow.cn/v1",
    "open_ai_api_key": "sk-xxxxxxxx",
    "open_ai_model": "deepseek-ai/DeepSeek-V3",
    "max_tokens": 4096,
    "with_text": false
}
```

| 字段 | 说明 |
| --- | --- |
| `open_ai_api_base` | API 地址，必须包含版本路径（如 `https://api.openai.com/v1`、`https://api.ppinfra.com/v3/openai`），插件直接拼接 `/chat/completions`，**不会**自动补 `/v1` |
| `open_ai_api_key` | API 密钥 |
| `open_ai_model` | 模型名，默认 `gpt-4o-mini` |
| `max_tokens` | 生成上限；若卡片生成失败可调大（如 `4096`） |
| `with_text` | `true` 时同时返回文本解释；`false`（默认）只返回图片卡片 |

> 兼容旧键名：`api_base` / `api_key` / `api_model` 仍可识别，但建议使用 `open_ai_*`。

## 说明

- 卡片由模型直接输出 HTML（或 SVG），插件用 Playwright 无头浏览器截图后发送图片。
- 需要可用的 OpenAI 兼容接口（OpenAI / 硅基流动 / DeepSeek 等）。
- 生成内容仅供娱乐，可能带有讽刺或夸张色彩，请遵守相关法律法规。

## 致谢

原作者 BenedictKing，以及提示词作者 云中江树、李继刚。

MIT License
