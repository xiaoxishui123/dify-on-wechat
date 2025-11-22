# ChinesePUA 插件

这是一个基于AI的中文解释和吐槽生成插件，可以对用户提供的关键词进行有趣的解释或吐槽。

## 功能

- 解释命令：对中文词语进行有趣且夸张的解释
- 吐槽命令：以关键词为主题，生成幽默的吐槽内容
- 圆角图片：自动为生成的图片添加圆角效果，提升视觉效果

## 使用方法

1. 解释功能：发送 `解释 [关键词]`，如 `解释 程序员`
2. 吐槽功能：发送 `吐槽 [关键词]`，如 `吐槽 加班`

## 配置说明

1. 复制 `config.json.template` 为 `config.json`
2. 编辑 `config.json` 文件，填入必要的配置信息：

```json
{
    "enabled": true,
    "api_key": "YOUR_DIFY_API_KEY_HERE",
    "api_base_url": "https://api.dify.ai",
    "template_file": "plugins/chinesepua/templates/prompt_template.txt",
    "log_level": "INFO"
}
```

### 配置项说明

- `enabled`: 是否启用插件，设置为 `true` 或 `false`
- `api_key`: Dify API 密钥，必填
- `api_base_url`: Dify API 基础 URL，默认为 "https://api.dify.ai"
- `template_file`: 提示词模板文件路径
- `log_level`: 日志级别，可设置为 "DEBUG", "INFO", "WARNING", "ERROR"
- `rounded_corner_radius`: 图片圆角半径，默认为 20 像素

## 关键词要求

- 关键词必须包含中文字符
- 关键词长度在1-10个字符之间

## 错误排查

如果插件无法正常工作，请检查以下几点：

1. 确认 `config.json` 中的 API 密钥已正确设置
2. 检查日志输出中是否有错误信息
3. 确认模板文件路径是否正确

## 模板定制

可以通过修改 `templates/prompt_template.txt` 文件来自定义生成内容的风格和特点。模板中可使用以下变量：

- `{{command_type}}`: 命令类型，值为 "explain" 或 "complain"
- `{{keyword}}`: 用户输入的关键词

## 安装

1. 将插件文件夹复制到 `plugins` 目录下
2. 安装playwright `pip install playwright`
3. 安装chromium `playwright install chromium`
4. 配置相关的key和base
4. 在 `config.json` 中启用插件
5. 重启 chatgpt-on-wechat

## 配置

可以在 `config.json` 中进行以下配置:

- `api_key`: API密钥
- `api_base`: API基础URL, 例如 `https://api.openai.com/v1`
- `api_model`: 使用的API模型, 默认 `gpt-4o-mini`
- `claude_key`: Claude API密钥（可选）
- `claude_base`: Claude API基础URL（可选）
- `claude_model`: 使用的Claude模型, 默认 `claude-3-5-sonnet-20240620`
- `with_text`: 是否在卡片中显示解释文本, 默认 `false`
- `max_tokens`: 生成的文本最大长度, 如果无法生成图片，可以适当增加这个值，例如4096

## 圆角图片功能

插件会自动为生成的图片添加圆角效果，让图片看起来更加美观和现代化。您可以通过配置文件调整圆角的大小：

```json
{
    "rounded_corner_radius": 20
}
```

- `rounded_corner_radius`: 圆角半径值（像素），数值越大圆角越明显
- 默认值为 20 像素
- 设置为 0 可以禁用圆角效果
- 推荐范围：10-50 像素

## 注意事项

- 本插件仅供娱乐使用,生成的内容可能具有讽刺或夸张性质
- 请遵守相关法律法规,不要生成违法或不当内容
- 本插件依赖于 `chatgpt-on-wechat` 项目，请确保你已经安装了该项目

## 贡献

欢迎提交 Issue 或 Pull Request 来帮助改进此插件!

## 许可证

MIT License

## 更新日志

### 0.5版本
- 新增更多Claude模型可用的提示词

### 0.4版本
- 新增"解字"、"字典"和"字源"触发词功能
- 增加了对Claude API的支持，某些功能可以选择使用Claude模型

### 0.3版本
- 新增"设计"和"名片"触发词功能
- 支持生成精美的社交名片，包含姓名、职位、公司和联系方式等个人信息
- 优化图片生成算法，提高名片设计的美观度和专业性
