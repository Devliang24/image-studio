---
name: image-studio
description: 当 Codex 需要通过 APIMart `gpt-image-2-official` 生成、编辑或迭代位图图像时使用此技能，包括海报、产品图、概念图、社媒创意以及参考图驱动的变体。适用于主要工作是整理提示词、规划画幅比例、多图参考、构造 APIMart 请求并保存最终图片到本地，而不是直接产出 SVG、HTML/CSS 或其他代码原生图形的场景。
---

# 图像工坊

当输出应来自外部图像模型时使用此技能，核心工作是把用户需求整理成高质量提示词，并生成有效的供应商请求。

## 工作流

1. 先判定请求类型。
   - 全新出图归为 `generate`。
   - 保留原图主体、只修改局部或部分内容时归为 `edit`。
   - 同一概念出多个相近版本时归为 `variation`。
   - 用户提供的图片默认视为参考图，除非明确说明它是编辑目标。

2. 只收集会阻塞结果的关键信息。
   - 询问主体、风格、宽高比、精确文案、输出数量和硬性限制。
   - 如果用户已经说得很具体，不要继续追问无关的创意细节。
   - 如果文本还原非常关键，尤其是中文海报或长文案场景，要提前说明后期排版通常更稳。

3. 把原始需求改写成可执行提示词。
   - 使用 `references/prompt-recipes.md` 里的结构。
   - 明确每张参考图的作用：主体、风格、构图、颜色或细节。
   - 需要严格出现的文字必须逐字引用。
   - 改图请求要重复写清不变量，例如“只改 X，保持 Y 不变”。

4. 选择供应商接入路径。
   - 固定使用 APIMart `gpt-image-2-official`。
   - 固定配置文件为 `assets/provider.apimart.gpt-image-2-official.json`。
   - 不要切换其他模型或供应商配置，除非用户明确要求重构 skill。

5. 先构造请求，再执行。
   - 先用 `scripts/build_image_request.py` 做 dry-run。
   - 传入 provider config、提示词、尺寸或宽高比，以及额外的供应商参数。
   - 如果是首次使用，先确认 `secrets.local.json` 存在，并且包含 provider config 需要的 secret 名称。
   - 在真正调用前确认 URL、请求头和 JSON body 都正确。
   - 如果供应商是异步任务模式，还要一并检查生成的任务查询请求。

6. 配置完整后再执行。
   - 只有在 provider config 真实可用、且 `secrets.local.json` 已经写入所需 API key 时才用 `--execute`。
   - 如果返回的是图片 URL，脚本会自动下载到本地目录，默认保存到 `output/generated-images/`。
   - 如果返回的是 base64 图片数据，未指定 `--output-file` 时也会默认落到 `output/generated-images/`；指定了 `--output-file` 时则按指定路径写入。
   - 如果返回的是任务 ID，则继续输出后续查询请求，或直接使用 `--poll` 等待完成。

7. 结果验证和迭代要收敛。
   - 检查主体、构图、风格、文字准确性和用户要求保持不变的部分。
   - 每次迭代只改一个维度。
   - 如果第一次结果已经接近目标，优先做小幅提示词修正，而不是整段重写。

## 规则

- 这个技能只用于位图图像生成和改图，不用于 SVG 图标系统或应直接在仓库中实现的代码原生图形。
- 不要假设供应商一定支持改图、参考图、seed 或宽高比参数，只有 provider config 明确支持时才能使用。
- 供应商密钥默认从 `secrets.local.json` 读取；该文件是本地密钥文件，不要提交到远端仓库。
- 精确排版要单独评估风险。涉及海报、广告或 UI mockup 时，必要时先确认用户要“图内直接出字”还是“预留空位后期排字”。
- 海报、广告和界面稿场景下，要确认图片是最终成品，还是仅用于构图草稿。

## 资源说明

- `scripts/build_image_request.py`：校验 provider config、构造请求、输出可复现的 `curl` 命令，并可选直接调用接口。
- `references/provider-contract.md`：APIMart `gpt-image-2-official` 的请求、查询和响应路径说明。
- `references/prompt-recipes.md`：海报、产品图、概念图、改图和精确文字场景的提示词结构。
- `assets/provider.apimart.gpt-image-2-official.json`：唯一供应商配置，固定使用 APIMart `gpt-image-2-official`。
- `secrets.example.json`：本地密钥文件示例，用于复制生成 `secrets.local.json`。
- `secrets.local.json`：本地 API Key 文件，脚本默认从这里读取 `APIMART_API_KEY`。
- `output/generated-images/`：默认本地落图目录。执行成功后，最终图片会保存到这里，除非使用 `--download-dir` 或 `--output-file` 覆盖。

## 常用命令

APIMart dry-run：

```bash
python3 scripts/build_image_request.py \
  --config assets/provider.apimart.gpt-image-2-official.json \
  --prompt "星空下的古老城堡" \
  --size 16:9 \
  --resolution 2k \
  --quality high
```

提交 APIMart 任务，并打印后续查询请求：

```bash
python3 scripts/build_image_request.py \
  --config assets/provider.apimart.gpt-image-2-official.json \
  --prompt "星空下的古老城堡" \
  --size 16:9 \
  --resolution 2k \
  --quality high \
  --execute
```

首次使用前，如果缺少本地密钥文件：

```bash
cp secrets.example.json secrets.local.json
```

然后编辑 `secrets.local.json`，填入：

```json
{
  "APIMART_API_KEY": "你的 APIMart API Key"
}
```

提交 APIMart 任务并轮询到最终图片 URL：

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

使用参考图提交 APIMart 图生图任务：

```bash
python3 scripts/build_image_request.py \
  --config assets/provider.apimart.gpt-image-2-official.json \
  --prompt "保留参考图主体结构，改成电影感夜景，蓝金色调" \
  --size 16:9 \
  --resolution 2k \
  --quality high \
  --reference-image "https://example.com/reference.png" \
  --execute
```

使用 `mask_url` 提交 APIMart 局部重绘任务：

```bash
python3 scripts/build_image_request.py \
  --config assets/provider.apimart.gpt-image-2-official.json \
  --prompt "只替换遮罩区域为发光霓虹招牌，其他区域保持不变" \
  --size 16:9 \
  --resolution 2k \
  --quality high \
  --reference-image "https://example.com/original.png" \
  --extra mask_url=https://example.com/mask.png \
  --execute
```

直接查询一个已有的 APIMart 任务：

```bash
python3 scripts/build_image_request.py \
  --config assets/provider.apimart.gpt-image-2-official.json \
  --task-id task-unified-1234567890-example \
  --execute
```

默认输出目录：

```text
image-studio/
└── output/
    └── generated-images/
```

## 固定模型

本 skill 只使用 `gpt-image-2-official`，并且只保留 `assets/provider.apimart.gpt-image-2-official.json` 这一份配置。
