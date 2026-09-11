# 模型供应接入与维护

## 已落地范围

统一入口为 `ProviderFactory` / `GatewayProvider`。业务服务不再根据厂商或模型名猜接口；原先六套 SDK 包装与视频提交实现已替换。新建任务通过精选目录验证模型用途和密钥权限，失效或隐藏的旧型号须重新选择，历史作品不改名、不删除。

AICON 默认连接为 `https://api.aicon-studio.com/v1`。模型广场 `/api/pricing` 提供站点元数据，带用户密钥访问 `/v1/models` 确认权限。后端交集过滤，密钥不发送到浏览器或公共目录请求中。厂商标签只用于说明，绝不用于选择密钥发送地址。

内置精选：文本 10、图片 8、视频 5、配音 5。按同一连接、同一用途限制最多 15 个；权限过滤后数量可能更少。视频包含站点原始 ID `sd-2.5`、`sd-2.0`、`sd-2.0-fast`、`sd-2.0-mini`、`MiniMax-H3`。前四项的 `/v1/video/generations` 路由由 pricing 的“豆包视频”声明确认，提交时保留原始 ID，不自行换成文档示例里的 doubao 别名。Grok / Wan 的候选配置保持隐藏，待站点真实调用澄清参数及查询契约后启用。

**协议样例测试通过不等于每个上游模型都完成了真实生成验收。** 本次没有使用生产密钥发起收费生成；模型可用性、站点别名接受情况和内容效果仍需带额度限制的真实冒烟验证。

## 修改配置即可启用同协议模型

默认文件：`backend/src/services/provider/models.json`。也可用进程环境变量 `MODEL_CATALOG_CONFIG` 指向运维维护的 JSON 文件；API 与所有 Worker 必须使用同一文件。环境变量应在启动进程前设置，单独写入未导出的 `.env` 不会自动覆盖此路径。

1. 用当前密钥刷新完整目录，确认型号可用。
2. 复制同协议型号的配置项，修改 `id`，按文档填写比例、尺寸、参考数量、音色或视频时长等参数。`id` 必须与站点返回值一致。
3. 设置 `enabled: true`；若某类已满 15 个，先隐藏被替代型号。未知协议不能仅增加一个 ID 就启用，需要补充适配器和测试。
4. 原子替换 JSON 文件，刷新页面。配置在请求时读取，无需重新构建或重启。配置损坏时，同一进程使用上一次有效配置；全新进程配置无效则拒绝生成。

主要字段：

| 字段 | 用途 |
| --- | --- |
| `id` | 站点精确模型 ID |
| `sources` | 默认 `['aicon']`；其他可为 `openai`、`deepseek`、`siliconflow`、`volcengine`、`vectorengine`、`compatible`（自定义其他地址） |
| `profile` | 下表已实现协议；不可指定任意请求路径 |
| `enabled` | 是否进入默认精选目录 |
| `released_at` / `release_source` | 已核实发布日期 YYYY-MM-DD 及来源链接；缺失日期排后，不用 `updated_time` 或名称后缀伪造日期 |
| `max_references` / `aspect_ratios` | 图片、视频能力；超限报错，不默默丢弃参考图 |
| `size_by_ratio` | Images / Seedream 的比例到像素尺寸映射 |
| `duration` / `durations` | 视频默认时长和允许时长 |
| `resolution` / `resolutions` | 视频默认分辨率和允许分辨率 |
| `voices` / `default_voice` | 配音允许音色及默认音色 |
| `defaults` | 根对象中每个 source 各用途的默认模型 |

内置清单的发布日期尚未独立核实，因此日期为空，当前按精选文件顺序展示。补齐可信日期后自动按新到旧排序。不要将这种文件顺序宣称为严格发布时间排名。

外部连接须在对应 `sources` 配置可调用型号：不会把 AICON 专有路由自动套到其他网关。OpenAI / DeepSeek 有少量基础配置；硅基流动与其他自定义网关需由维护者配置实际使用的主力型号。旧的“用途不明时返回前 20 个模型”回退已移除。

## 请求与结果兼容

| Profile | 请求 | 业务结果 |
| --- | --- | --- |
| `chat` | `/v1/chat/completions` | 统一文本结果；保留 Chat 流 |
| `responses` | `/v1/responses`，映射 input、结构化输出、token 限制 | 完整文本或统一流增量；不完整终态报错 |
| `images` | `/v1/images/generations` JSON；带参考图则 `/v1/images/edits` multipart | URL / base64；保存前核验图像字节及真实 MIME |
| `gemini_image` | `/v1beta/models/{id}:generateContent` | 仅提取图片 inlineData，不把 thoughtSignature 当图片 |
| `seedream` | `/v1/images/generations`，参考图为 image 数组 | 统一单图结果 |
| `seedream_pro` | `/api/v3/images/generations` | 统一单图结果 |
| `gateway_video` | `/v1/video/generations`；查询 `/v1/videos/{id}` | 统一任务状态和 metadata.url；MiniMax 分辨率独立配置 |
| `grok_video`（隐藏） | `/v1/videos/generations` | request_id / done / video.url；参数待真实核验 |
| `wan_video`（隐藏） | `/api/v1/services/aigc/video-generation/video-synthesis` | 查询 `/api/v1/tasks/{id}`；成功封装待真实核验 |
| `speech` | `/v1/audio/speech` | MP3 二进制 |
| `gemini_speech` | Gemini AUDIO generateContent | 24kHz 单声道 PCM 包装为 WAV，按 `.wav` 保存 |
| `minimax_speech` | `/minimax/v1/t2a_v2` 同步 hex | 校验业务错误码，解码后保存 MP3 |

视频参考图使用可被上游访问的 URL。站内对象键生成 24 小时签名链接，`MINIO_PUBLIC_URL` 必须可从站点访问。首尾帧操作要求两张图和 `supports_frames` 能力；不会把首尾帧退化成普通参考图。

## 视频任务与部署

迁移 `030` 为 `movie_shot_transitions` 增加可空 JSON 字段，仅存协议、模型和连接快照，不存明文密钥。先更新后端代码并执行 `alembic upgrade head`，再启动新 Worker / Beat。已有历史行保持 NULL；旧任务只走单独的只读查询兼容类，没有旧型号的创建入口。

Canvas 提交成功即保存任务 ID 与快照并提交事务，Worker 不长期等待生成完成。Beat 每 30 秒派发查询任务；每个查询任务有 Redis 锁避免同一任务堆积并发请求。页面也可查询状态。瞬时查询失败保留原任务，不重新提交生成；已持久化的视频任务重复执行不会再 POST。进程在上游接收请求后、任务 ID 入库前崩溃仍属于分布式提交的不确定窗口，本站未提供幂等保证时不能宣称完全消除重复生成。

查询历史任务不要求模型仍在精选目录。新协议任务若密钥的连接地址已变更，会提示恢复提交时的连接，避免向错误站点发送该密钥。旧任务没有快照，沿用原密钥记录的旧查询地址；不要在它结束前改变地址。

`docker-compose.prod.yml` 已将 `backend/src` 挂载给 API / Worker / Beat，直接更新默认 models.json 可被全部进程看到。首次发布本次代码需要包含迁移 030 的后端镜像，不能仅修改模型配置替代程序升级。其他部署方式应将同一个配置目录只读挂载到各服务，再设置 `MODEL_CATALOG_CONFIG`。

## 目录接口与缓存

- `GET /api/v1/api-keys/provider-presets`：受支持的供应商及默认地址，前端不再重复维护默认值。
- `GET /api/v1/api-keys/{id}/models?type=text|image|video|audio`：保留字符串列表响应，供现有选择器使用。
- `GET /api/v1/api-keys/{id}/model-catalog?refresh=true&include_hidden=true`：模型能力与 enabled / hidden / needs_configuration / unavailable 状态。
- `GET /api/v1/canvas-model-catalog`：`connections[key_id]` 形式，保持模型与密钥对应关系。

目录接口校验密钥所属用户和激活状态。公共元数据缓存 5 分钟，失败可用本进程最后成功缓存并标记 stale；权限缓存 60 秒且以连接与密钥摘要隔离，刷新失败清除旧权限，不回退为“全模型可用”。缓存目前在进程内，重启后首次请求需要上游可用。

本次本地测试结果与自审修复记录见[自审与验证](model-provider-review.md)。
