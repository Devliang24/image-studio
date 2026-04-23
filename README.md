# Image Studio Skill

图像工坊 Skill，通过 APIMart 生成、编辑和迭代图片。当前固定使用 `gpt-image-2-official`，支持文生图、参考图生成、异步任务查询、轮询完成后自动下载图片到本地。

## 快速上手

1. 进入 skill 目录：

```bash
cd image-studio
```

2. 从示例复制本地密钥文件：

```bash
cp secrets.example.json secrets.local.json
```

3. 打开 `secrets.local.json`，填入你的 APIMart Key：

```json
{
  "APIMART_API_KEY": "你的 APIMart API Key"
}
```

4. 运行一次 dry-run，确认请求体正确且密钥能被读取：

```bash
python3 scripts/build_image_request.py \
  --config assets/provider.apimart.gpt-image-2-official.json \
  --prompt "星空下的古老城堡" \
  --size 16:9 \
  --resolution 2k \
  --quality high
```

5. 真实生成并自动保存到本地：

```bash
python3 scripts/build_image_request.py \
  --config assets/provider.apimart.gpt-image-2-official.json \
  --prompt "星空下的古老城堡" \
  --size 16:9 \
  --resolution 2k \
  --quality high \
  --execute \
  --poll
```

生成图片默认保存在：

```text
output/generated-images/
```

## 配置 API Key

1. 准备 APIMart API Key。
2. 如果还没有本地密钥文件，先执行 `cp secrets.example.json secrets.local.json`。
3. 把 Key 写入 `secrets.local.json`。
4. `secrets.local.json` 已加入 `.gitignore`，不要提交到远端仓库。

```json
{
  "APIMART_API_KEY": "你的 APIMart API Key"
}
```

如果 Key 曾经暴露在聊天、日志或截图中，按泄露处理并及时轮换。

`secrets.example.json` 只保留占位符，适合提交；`secrets.local.json` 存真实密钥，只留在本机。

## 安装与不同工具使用

复制整个 skill 目录到 Codex skills 目录，例如：

```bash
mkdir -p ~/.codex/skills
cp -R image-studio ~/.codex/skills/image-studio
```

重启 Codex 或开启新的会话后即可使用。

### Codex

个人级安装：

```bash
mkdir -p ~/.codex/skills
cp -R image-studio ~/.codex/skills/image-studio
```

使用时直接描述需求即可，例如：

```text
使用 image-studio 画一张星空下的古老城堡，16:9，2K，高质量，并保存到本地。
```

### Claude Code

Claude Code 支持 Agent Skills。个人级 skill 放在 `~/.claude/skills/`，项目级 skill 放在项目内 `.claude/skills/`。

个人级安装：

```bash
mkdir -p ~/.claude/skills
cp -R image-studio ~/.claude/skills/image-studio
```

项目级安装：

```bash
mkdir -p .claude/skills
cp -R image-studio .claude/skills/image-studio
```

使用方式：

```text
/image-studio 画一张星空下的古老城堡，16:9，2K，高质量，并保存到本地。
```

也可以不显式输入 slash command，直接描述“画图、生成图片、APIMart 生图、查询任务”等需求，Claude Code 会根据 `SKILL.md` 的 `description` 自动判断是否加载该 skill。

### OpenCode

OpenCode 支持 `AGENTS.md` 规则文件，也兼容 Claude Code 的 `~/.claude/skills/`。最简单的方式是复用 Claude Code 安装路径：

```bash
mkdir -p ~/.claude/skills
cp -R image-studio ~/.claude/skills/image-studio
```

如果你更希望在当前项目中显式提示 OpenCode 使用该 skill，可以在项目根目录的 `AGENTS.md` 中加入：

```markdown
# 图像工坊

当用户要求画图、生成图片、改图、图生图、查询 APIMart 任务或保存生成图片时，读取并遵循 `.claude/skills/image-studio/SKILL.md`。

默认使用 APIMart 配置：`.claude/skills/image-studio/assets/provider.apimart.gpt-image-2-official.json`。

执行脚本：`.claude/skills/image-studio/scripts/build_image_request.py`。

最终图片默认保存到：`.claude/skills/image-studio/output/generated-images/`。
```

对应项目级安装命令：

```bash
mkdir -p .claude/skills
cp -R image-studio .claude/skills/image-studio
```

如果你设置过 `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1`，OpenCode 将不会读取 Claude Code skills，需要取消该环境变量或改用 `AGENTS.md` / `opencode.json` 显式引用。

## 使用示例

直接对 Codex 说：

| 说法 | 效果 |
| --- | --- |
| `画一张星空下的古老城堡，16:9，2K，高质量` | 文生图并保存到本地 |
| `用 APIMart 生成一张赛博朋克城市海报` | 调用 APIMart 生成任务 |
| `根据这张图 URL 生成类似风格，但改成夜景` | 参考图生成 |
| `只把遮罩区域改成霓虹招牌，其他不变` | 局部重绘，需要 `mask_url` |
| `查询任务 task_xxx 的结果` | 查询已有异步任务 |

也可以直接运行脚本：

```bash
python3 scripts/build_image_request.py \
  --config assets/provider.apimart.gpt-image-2-official.json \
  --prompt "星空下的古老城堡" \
  --size 16:9 \
  --resolution 2k \
  --quality high \
  --execute \
  --poll
```

如果你不想使用默认 `secrets.local.json`，可以显式指定密钥文件：

```bash
python3 scripts/build_image_request.py \
  --config assets/provider.apimart.gpt-image-2-official.json \
  --secrets-file /path/to/secrets.json \
  --prompt "星空下的古老城堡" \
  --execute \
  --poll
```

指定本地保存目录：

```bash
python3 scripts/build_image_request.py \
  --config assets/provider.apimart.gpt-image-2-official.json \
  --prompt "星空下的古老城堡" \
  --size 16:9 \
  --resolution 2k \
  --quality high \
  --execute \
  --poll \
  --download-dir output/my-images
```

## 本地输出

默认输出目录：

```text
output/generated-images/
```

当供应商返回图片 URL 时，脚本会自动下载图片到该目录。当供应商返回 base64 图片时，也会写入该目录；如果传入 `--output-file`，则写入指定文件。

## 文件说明

```text
image-studio/
├── .gitignore                                    # 忽略本地密钥和生成图片
├── SKILL.md                                      # Skill 入口和执行规则
├── README.md                                     # 用户安装和使用说明
├── secrets.example.json                          # 密钥文件示例
├── secrets.local.json                            # 本地密钥文件，不要提交
├── agents/openai.yaml                            # UI 元信息
├── assets/provider.apimart.gpt-image-2-official.json
│                                                  # 唯一模型配置
├── references/provider-contract.md                # APIMart 请求和响应路径说明
├── references/prompt-recipes.md                   # 提示词模板
├── scripts/build_image_request.py                 # 请求构造、执行、轮询和下载脚本
└── output/generated-images/                       # 默认图片保存目录
```

## 当前支持的模型

| 模型 | 说明 |
| --- | --- |
| `gpt-image-2-official` | APIMart 图像工坊默认模型 |

## 常用参数

| 参数 | 示例 | 说明 |
| --- | --- | --- |
| `--prompt` | `"星空下的古老城堡"` | 图片生成提示词 |
| `--size` | `16:9` | 画幅比例或供应商支持的尺寸 |
| `--resolution` | `2k` | 分辨率档位 |
| `--quality` | `high` | 质量档位 |
| `--count` | `1` | 生成数量 |
| `--reference-image` | `https://example.com/input.png` | 参考图 URL，可重复传入 |
| `--extra mask_url=...` | `--extra mask_url=https://example.com/mask.png` | 局部重绘遮罩图 |
| `--poll` | 无 | 提交任务后轮询到完成 |
| `--download-dir` | `output/my-images` | 覆盖默认保存目录 |
| `--secrets-file` | `/path/to/secrets.json` | 覆盖默认密钥文件 |

## 支持的尺寸

APIMart 当前示例使用 `16:9`。如果供应商支持更多比例，可直接通过 `--size` 传入，例如：

```text
1:1、16:9、9:16、4:3、3:4、3:2、2:3、4:5、5:4、21:9
```

实际可用范围以供应商 API 为准。

## 固定模型和文件精简

当前 skill 只保留一个模型和一个 provider 配置：

```text
assets/provider.apimart.gpt-image-2-official.json
```

保持单模型结构即可，当前只需要这一份配置文件。

真实密钥写入 `secrets.local.json`，不要写进 provider JSON 配置，也不要提交到远端仓库。
