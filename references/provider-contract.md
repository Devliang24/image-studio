# APIMart gpt-image-2-official 配置说明

本 skill 只接入一个模型：`gpt-image-2-official`。供应商配置文件固定为：

```text
assets/provider.apimart.gpt-image-2-official.json
```

## 本地密钥

脚本默认读取 skill 目录下的 `secrets.local.json`。

首次使用：

```bash
cp secrets.example.json secrets.local.json
```

然后写入：

```json
{
  "APIMART_API_KEY": "你的 APIMart API Key"
}
```

`secrets.local.json` 已加入 `.gitignore`，不要提交到远端仓库。

## 请求流程

APIMart 是异步任务模式：

1. `POST /v1/images/generations` 提交生成任务。
2. 响应中读取 `data.0.task_id`。
3. `GET /v1/tasks/{task_id}?language=zh` 查询任务。
4. 任务完成后从 `data.result.images.0.url.0` 读取最终图片 URL。
5. 脚本自动下载最终图片到 `output/generated-images/`。

## 核心字段

请求体字段：

- `model`: 固定为 `gpt-image-2-official`
- `prompt`: 图片提示词
- `size`: 比例或尺寸，例如 `16:9`
- `resolution`: 分辨率档位，例如 `2k`
- `quality`: 质量档位，例如 `high`
- `n`: 生成数量，默认 `1`
- `image_urls`: 参考图 URL 列表，可选
- `mask_url`: 局部重绘遮罩图，可选
- `output_format`: 输出格式，可选
- `output_compression`: 输出压缩参数，可选

响应路径：

- 提交任务 ID：`data.0.task_id`
- 查询状态：`data.status`
- 查询进度：`data.progress`
- 最终图片 URL：`data.result.images.0.url.0`
- 错误信息：`error.message` 或 `data.error.message`

## 常用命令

Dry-run：

```bash
python3 scripts/build_image_request.py \
  --config assets/provider.apimart.gpt-image-2-official.json \
  --prompt "星空下的古老城堡" \
  --size 16:9 \
  --resolution 2k \
  --quality high
```

真实生成并保存：

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

查询已有任务：

```bash
python3 scripts/build_image_request.py \
  --config assets/provider.apimart.gpt-image-2-official.json \
  --task-id task_xxx \
  --execute
```
