# AICON 模型接口与响应兼容调查

日期：2026-09-10。对应[重构方案](model-provider-unification-plan.md)。本文件记录调查事实和待验证项，不代表模型已通过真实生成验收。

用户已确认采用“文本、图片、视频、配音每类精选 5–15 个主力模型，按核实的模型发布时间从新到旧排序；其余隐藏，需要时再启用”。以下型号和协议是调查记录，不是必须保留的上线清单；仅精选型号及实际未完成任务需要的协议进入实施范围。目录 updated_time 不能作为模型发布日期；未核实日期的型号排后，数量不足时不以旧型号凑数。

## 1. 证据范围

- 对照当前 main 工作区的 Provider、模型发现、Canvas、Assistant、Movie Studio、图像/语音工具及视频后台同步链路。
- 读取[公开模型目录](https://api.aicon-studio.com/api/pricing)：331 个不同模型名、31 个厂商；其中 283 条带 openai，64 条带 openai-response，21 条只带 openai-response。接口类型可重复计数。
- 从[Apifox 索引](https://dcsynw64g3.apifox.cn/llms.txt)读取并解析 88 份接口页的 OpenAPI 内容，重点比较下表所列请求、响应与异步任务链路。
- 对 OpenAI Images、Responses、Speech 的文档矛盾，查阅官方协议作为基线；对 Gemini 音频格式核对站点具体示例。没有将官方支持范围直接等同于中转站支持范围。
- 从源码提取现有 Canvas 视频地址解析函数，对四份文档响应进行本地样例回放，结果见第 5 节。
- 未使用有效令牌读取授权模型目录、未发送生成请求、未访问中转站后台/数据库。`/v1/models` 无令牌访问为 401，认证后的语义仍需核实。

## 2. 文本协议

| 协议/模型线索 | 请求 | 响应与流式处理 | 调查结论 |
| --- | --- | --- | --- |
| 声明 openai 的通用对话模型 | POST /v1/chat/completions；model/messages | choices[].message.content；流式读取 delta；用量与结束原因独立处理 | 已有封装可复用，但识图、翻译、嵌入、音频等特殊任务不能仅凭 openai 标签归入普通对话 |
| 声明 openai-response 的模型 | POST /v1/responses；model/input；JSON 输出参数与 Chat 不同 | 标准响应为 output 内容项；仅汇总 message 中的 output_text，不能把 reasoning/function_call 当正文；流式转换 response.output_text.delta 等事件 | 必须有独立请求/响应适配；站点页面的聊天响应示例与标准冲突，需实测确认 |
| Gemini 原生文本 | POST /v1beta/models/{model}:generateContent；contents/systemInstruction/generationConfig | candidates[].content.parts；原生错误/结束原因 | 站点有原生文档；具有明确 Chat 兼容路由时可以先复用 Chat，不能自动改写所有 Gemini 请求 |
| Assistant | 目前通过 Provider 发出带 response_format=json_object 的请求，在 JSON 中表达动作 | 解析结构化 JSON 后构造应用工具调用 | 当前不是直接透传标准原生 tool_calls；重构供应层应保留此业务语义，并按模型验证 JSON 输出能力 |

来源：[站点 Chat](https://dcsynw64g3.apifox.cn/513529860e0)、[站点 Responses](https://dcsynw64g3.apifox.cn/513529921e0)、[站点 Responses 流式](https://dcsynw64g3.apifox.cn/513529923e0)、[站点 Gemini 文本](https://dcsynw64g3.apifox.cn/513529880e0)、[OpenAI Responses 标准](https://developers.openai.com/api/reference/python/resources/responses/methods/create)。

本次仅声明 Responses 的 21 个目录 ID：

```text
gpt-5.5-pro                  gpt-5.4
gpt-5.4-pro                  o3-pro
gpt-5.1-codex-max            gpt-5-chat-latest
gpt-5.4-pro-2026-03-05       gpt-5.2-pro
gpt-5-codex                 gpt-5-pro
gpt-5-mini                  gpt-5-nano
gpt-5-codex-low             gpt-5-codex-medium
o1-pro                      o1-pro-2025-03-19
o3-pro-2025-06-10           gpt-5.2-pro-2025-12-11
gpt-5.1-codex               gpt-5-codex-high
gpt-5.1-codex-high
```

这是站点元数据事实，不是对这些 ID 的官方可用性或实际权限背书。同一模型有多个 endpoint 时，要选择通过验证且满足当前操作需求的一条，不能出错后依次试发多个收费接口。

## 3. 图片协议

| 模型/协议候选 | 创建/编辑方式 | 结果处理 | 当前缺口与决定 |
| --- | --- | --- | --- |
| gpt-image-1、1-mini、1.5、2、2-c | 创建 /v1/images/generations，编辑 /v1/images/edits；编辑文档使用 multipart 文件/遮罩 | 标准 data[] 中 URL 或 b64_json，加上实际 output_format；统一存储 | 现有 CustomProvider 只调用 images.generate，不实现 edits。站点 GPT Image-2 创建响应错配为聊天，编辑 data 被写成 object，与标准数组冲突，必须补实际样本 |
| Gemini 图像模型 | 原生 generateContent；contents.parts；参考图 inline_data；imageConfig 控制比例/尺寸 | 按 MIME 提取图像 inlineData，保留其他文本说明；不能把 thoughtSignature 当图片 | 现有代码只取第一张且自行封装成伪 OpenAI 对象；站点 response_format=url 扩展及 responseModalities 示例不一致，不直接启用未验证扩展 |
| Seedream 4.5、5.0 等兼容路径 | /v1/images/generations；图生图也可在此路径传 image URL/数组；参数含 size、水印、组图设置 | 文档给出 data[].url，可复用 Images 解码器 | 不等同于 multipart edits；请求参数应使用 JSON 扩展配置，SDK 不接受的扩展需正确编码，不能直接 kwargs 透传 |
| doubao-seedream-5-0-pro-260628 | 文档明确 /api/v3/images/generations；image 或 images，response_format、output_format | 文档成功示例 data[].url | pricing 只标 openai，不能据此发 Chat；复用媒体解码，单独配置路径与参数。文档 n 上限为 1 |
| qwen-image-max、qwen-image-2.0-2026-03-03、z-image-turbo | 部分文档走 /v1/images/generations，Qwen 编辑也在该路径用 image | 部分示例为 data[].url/b64_json | 2.0 页面只有错误响应示例；不能宣称已验证成功结构 |
| qwen-image-max-2025-12-30 | 专页标记 /alibailian/api/v1/services/aigc/multimodal-generation/generation | 专页成功结构为空 | 与 pricing 的 dall-e-3 路径映射冲突，待确认应采用哪个路径及响应封装 |
| grok-imagine-image、grok-imagine-image-2.0 | 图像文档为 images/generations、images/edits，编辑还有 JSON/multipart 变体 | 需按具体站点路由验证图片返回 | pricing 含 openai-response/openai-video，不能据此把绘图当视频或对话 |
| gpt-4o-image-vip / Chat 绘图 | /v1/chat/completions 为候选 | 可能是内容块或文本里的图片引用，站点通用聊天示例不能证明输出规则 | 不用正则从任意正文猜图片；取得可验证响应前保持待适配 |
| mj_imagine、mj_upscale、mj_variation、mj_reroll | /mj/submit/imagine 与动作接口；并非四个普通生成模型 | 创建任务后查询；文档查询有 SUCCESS、imageUrl、progress、buttons | 需要异步图像和动作上下文；单纯 Provider 改名不足以接入，独立扩展，不混入同步图片列表 |

来源：[GPT 创建](https://dcsynw64g3.apifox.cn/513530006e0)、[GPT 编辑](https://dcsynw64g3.apifox.cn/513530005e0)、[OpenAI Images 标准](https://developers.openai.com/api/reference/python/resources/images/methods/generate)、[Gemini 图像](https://dcsynw64g3.apifox.cn/513530040e0)、[Seedream 多图](https://dcsynw64g3.apifox.cn/513530017e0)、[Seedream 5 Pro](https://dcsynw64g3.apifox.cn/513530024e0)、[Qwen 特殊路径](https://dcsynw64g3.apifox.cn/513530032e0)、[Qwen 2.0](https://dcsynw64g3.apifox.cn/513530033e0)、[Qwen 编辑](https://dcsynw64g3.apifox.cn/513530035e0)、[Grok 编辑](https://dcsynw64g3.apifox.cn/513530009e0)、[Chat 绘图](https://dcsynw64g3.apifox.cn/513529902e0)、[MJ 提交](https://dcsynw64g3.apifox.cn/513529987e0)、[MJ 查询](https://dcsynw64g3.apifox.cn/513529988e0)。

不能按“图像”分类自动开放生图：gpt-4-vision-compatible 的标签实际为识图。文档中还存在 Fal/Tencent 等异步图像端点，但目录、操作和具体路由必须明确匹配后才可加入，不能仅因文档存在就宣称站点已对当前令牌开放。

## 4. 视频协议：必须成套绑定

| 路由族/代表 | 提交 | 查询 | 文档结果 | 决定 |
| --- | --- | --- | --- | --- |
| 旧 Veo 统一格式 | POST /v1/video/create；JSON；images/aspect_ratio | GET /v1/video/query?id=… | id；completed；video_url 或 detail.video_url | 仅有保留型号或未完成任务依赖时核实并暂留；否则删除。现有代码混用 /videos/{id} 查询，兼容性未实测 |
| Veo OpenAI 格式 | POST /v1/videos；multipart；seconds/input_reference/size | GET /v1/videos/{id}；另有 /content | id；queued/completed；video_url | 参数并非旧统一格式；/content 文档写 JSON，不能假定为标准视频二进制 |
| 豆包网关格式 | POST /v1/video/generations；JSON；duration/images/metadata | GET /v1/videos/{task_id} | id/task_id；succeeded；metadata.url | 当前解析不兼容。pricing 的 sd-* 与文档 doubao-seedance-* 没有明确映射；需保留原 ID 并确认别名 |
| MiniMax H3 网关格式 | POST /v1/video/generations；JSON；duration/images/videos/audios/metadata | GET /v1/videos/{task_id} | id/task_id；completed；metadata.url | 与豆包可共享提交/查询基础和响应处理，但视频/音频素材字段位置不同，不能完全复用请求体 |
| Grok 原生格式 | POST /v1/videos/generations（videos 为复数）；JSON | GET /v1/videos/{task_id} | request_id；done；video.url | 需要独立提交 ID 提取和结果解析；同路径文档还有 seconds/duration 两种参数描述，必须明确版本 |
| Grok OpenAI 格式 | POST /v1/videos；multipart | 该分组查询页却指向 GET /v1/video/query?id=… | 提交成功 Schema 为空；查询给 pending 示例 | 不能把“OpenAI 格式”标签当作完整协议保证，待实际创建/查询样例确定组合 |
| Wan 3.0 | POST /api/v1/services/aigc/video-generation/video-synthesis；input/parameters | 文档路径 GET /api/v1/tasks/{task_id}，说明文字又写 /tasks/{task_id} | 创建 id/task_id/queued；查询页只给 failed/error 例子 | 需要成功样例和路径确认；不能从 pricing 的 openai 发 Chat 或套旧 Veo 查询 |
| 豆包原生兼容 | /api/v3/contents/generations/tasks 或 /volc/v1/contents/generations/tasks | 分别使用匹配前缀的 tasks/{id} | 原生 content 与任务结构需按对应页面适配 | 不是上面网关 Generations 的同一路径；按连接/模型明确选择，不猜前缀 |

来源：[Veo 创建](https://dcsynw64g3.apifox.cn/513530042e0)、[Veo 查询](https://dcsynw64g3.apifox.cn/513530044e0)、[Veo multipart](https://dcsynw64g3.apifox.cn/513530046e0)、[Veo 查询/下载](https://dcsynw64g3.apifox.cn/513530048e0)、[豆包创建](https://dcsynw64g3.apifox.cn/513530114e0)、[豆包查询](https://dcsynw64g3.apifox.cn/513530119e0)、[MiniMax H3 创建](https://dcsynw64g3.apifox.cn/513530136e0)、[MiniMax H3 查询](https://dcsynw64g3.apifox.cn/513530137e0)、[Grok 原生](https://dcsynw64g3.apifox.cn/513530086e0)、[Grok 查询](https://dcsynw64g3.apifox.cn/513530087e0)、[Grok OpenAI 查询](https://dcsynw64g3.apifox.cn/513530082e0)、[Wan 提交](https://dcsynw64g3.apifox.cn/513530100e0)、[Wan 查询](https://dcsynw64g3.apifox.cn/513530102e0)、[豆包原生提交](https://dcsynw64g3.apifox.cn/513530067e0)、[豆包原生查询](https://dcsynw64g3.apifox.cn/513530068e0)。

首尾帧、多参考不是同一语义，请求位置也不统一：

| 输入 | 豆包网关文档 | MiniMax H3 文档 | Wan 文档 |
| --- | --- | --- | --- |
| 普通参考图 | images | images | input.media 中对应 type |
| 首帧/尾帧 | metadata.first_frame / last_frame | metadata.first_frame / last_frame | input.media 中 first_frame / last_frame 类型 |
| 参考视频/音频 | metadata.videos / audios | 顶层 videos / audios | input.media 中 reference_video / reference_audio 类型 |
| 生成时长 | duration | duration | parameters.duration |
| 比例/分辨率 | metadata.ratio / resolution | metadata.ratio / resolution | parameters.ratio / resolution |

来源：[豆包多模态](https://dcsynw64g3.apifox.cn/513530118e0)、[MiniMax 多模态](https://dcsynw64g3.apifox.cn/513530136e0)、[Wan 多模态](https://dcsynw64g3.apifox.cn/513530100e0)。例如 MiniMax 标题为首尾帧的单独页面 Schema 只列首帧，多模态页才列全；应以核实后的具体操作配置为准。

## 5. 现有解析器对文档样例的回放

从 `backend/src/services/canvas.py` 提取 `_extract_video_url` 方法独立执行，输入为文档中的响应示例，没有发起真实模型请求：

| 文档样例 | 状态 | 结果地址位置 | 现有函数结果 |
| --- | --- | --- | --- |
| 513530044e0，旧 Veo | completed | video_url / detail.video_url | 能提取 |
| 513530119e0，豆包 | succeeded | metadata.url | None |
| 513530137e0，MiniMax H3 | completed | metadata.url | None |
| 513530087e0，Grok | done | video.url | None |

当前视频提交只取 id/task_id，也不能读取 Grok 的 request_id。Movie Studio 的同步代码只在 status==completed 时读取 URL，且不读 metadata.url/video.url。由此可证明当前实现不兼容这些文档样例；不能据此声称线上已发生故障。

Canvas 会尝试 60 轮查询，查询本身还有重试，任务队列另有 480 秒软限制和 600 秒硬限制默认值。因此新增长视频不能仅增加模型选项或轮询次数，需要把已受理任务和素材落库进度持久化，任务超时后继续恢复查询，避免重复提交。

## 6. 语音协议与其他用途

| 类型 | 请求 | 响应 | 接入判断 |
| --- | --- | --- | --- |
| OpenAI Speech：tts-1 系列、gpt-4o-mini-tts | POST /v1/audio/speech；input/voice/model/response_format | 标准为音频内容，默认 MP3，可选其他格式；站点 200 Schema 为空 | 现有音频链路基础可复用，但应验证真实 Content-Type 与错误体 |
| Gemini TTS | generateContent；responseModalities=AUDIO；speechConfig | 站点示例 candidates[].content.parts[].inlineData，MIME 为 audio/L16;codec=pcm;rate=24000 | 需要 PCM 解码与 WAV 封装或转码；不能直接写 .mp3。模型目录某些 TTS path 固定成另一个模型名，不能直接照抄 |
| MiniMax 同步 TTS：speech-* | POST /minimax/v1/t2a_v2；text/voice_setting/audio_setting | data.audio 为 hex 或 URL；base_resp.status_code；格式信息在 extra_info | 独立请求与响应适配，不能用 OpenAI response.content |
| MiniMax 异步 TTS | POST /minimax/v1/t2a_async_v2 → query/t2a_async_query_v2?task_id=… → files/retrieve?file_id=… | task_id/file_id → 状态 → file.download_url | 需要异步音频任务生命周期；不能直接塞进当前同步单句语音调用 |
| Whisper/Transcribe、Realtime、音频对话、Voice Design | 不同操作：转录、实时会话、音色设计等 | 文本、实时事件或音色 ID 等 | 从普通配音列表排除；“音视频”不是 TTS 能力 |
| Embedding/Rerank | 向量或排序接口 | 向量/相关性结果 | 当前创作模型选择不需要；text-embedding-3-large 被目录标为文本也不能选入聊天 |

来源：[站点 Speech](https://dcsynw64g3.apifox.cn/513529858e0)、[OpenAI Speech 标准](https://developers.openai.com/api/docs/guides/text-to-speech)、[站点 Gemini TTS](https://dcsynw64g3.apifox.cn/513529899e0)、[MiniMax 同步](https://dcsynw64g3.apifox.cn/513530248e0)、[异步创建](https://dcsynw64g3.apifox.cn/513530247e0)、[异步查询](https://dcsynw64g3.apifox.cn/513530257e0)、[文件检索](https://dcsynw64g3.apifox.cn/513530255e0)。

## 7. 文档与目录不能自动编译为适配代码的具体原因

1. 目录中 openai 的全局定义是 Chat，但被视频、TTS、Seedream、MJ 复用；有些实际操作根本不接受 model 字段。
2. path 有 JSON 字符串、普通标签和未定义 endpoint ID；同一 Grok 的单数/复数 video 路径不一致。
3. [列出模型](https://dcsynw64g3.apifox.cn/513529868e0)的响应是聊天示例，[令牌支持模型](https://dcsynw64g3.apifox.cn/513529931e0)的响应结构为空，无法仅靠文档确定 data[].id 及权限语义。
4. [GPT 图片生成](https://dcsynw64g3.apifox.cn/513530006e0)、[Responses](https://dcsynw64g3.apifox.cn/513529921e0)响应也用了聊天示例；Grok 某页面甚至把请求 JSON 放在成功响应中。
5. Chat 非流式 Schema 把 tools/tool_choice 标为必填，而同页请求示例未提供；Gemini 图片请求示例只声明 TEXT，却是图片页。不能照抄所有 required 和默认值。
6. 视频字段有 duration/seconds、整数/字符串、不同状态名和不同结果嵌套位置；Wan 描述、路径及失败样例不能拼成已验证的成功契约。
7. 文档型号与目录 ID 不完全对应。sd-*、旧 Veo、部分新版图像模型必须确认准确路由，不能用模糊名字替换。
8. 公共页面附带 New-Api-User: 1 等调试示例及多种认证方案，不能将示例用户 ID 或会话认证头复制进普通令牌调用。按明确认证配置携带凭据。

结论：使用文档辅助人工建立有限的协议配置，并通过脱敏真实样本固化测试；运行时仅读取已校验的模型/操作绑定和能力数据。增加相同契约的模型更新配置即可，新契约才增加适配代码。

## 8. 代码清理的核实范围

- `APIKeyService.get_models`、`canvas-model-catalog` 是两种模型入口。后者合并全部密钥模型导致关联丢失，必须一起迁移，不能只改 get_models。
- 统一连接/适配器入口覆盖 Canvas、Assistant、角色、场景、分镜/关键帧、过渡视频、提示词、字幕和单句语音。`visual_identity_service.py` 还存在 flux-pro 默认及仅取 URL 的路径，需要一并纳入清单。
- 响应解析集中在 Provider、image.py、image_utils.py、Canvas、VisualIdentity、Transition 等多处。迁移后业务只读统一结果，不能保留并行的宽松字段猜测器。
- `BaseLLMProvider` 强制所有类实现文本、图片、音频，DeepSeek 缺少抽象方法；改为按能力暴露操作，未支持用途在调用前明确拒绝。
- `tasks/transition_sync.py` 有同名任务的未完成实现，但当前 Celery include 加载的是 `tasks/movie.py` 中调用真实服务的任务。不能把未加载的遗留文件误判成当前同步完全失效；清理时核实注册来源。
- 历史密钥、任务 ID、提示词、素材 object_key、用户选择与生成历史保留；新增执行上下文确保目录刷新和连接调整不会改变正在执行任务的查询协议。

## 9. 最小实测清单

| 核实项 | 最小证据 | 用途 |
| --- | --- | --- |
| 令牌模型发现 | 授权 GET /v1/models 返回结构；不同权限/分组令牌的差异 | 确定目录可用范围；不能仅用公开 enable_groups 判权限 |
| Chat 与 Responses | 各一份非流式、流式、错误响应；JSON 输出样例 | 确定文本和助手契约，覆盖中途错误与空/不完整输出 |
| 图片 | 每种已启用请求/响应配置的无参考与带参考样例，真实 URL/base64、MIME | 验证模型/操作映射，不必对每个同协议型号重复生成 |
| 视频 | 每种精选型号所需协议的提交、运行中、成功、失败、内容获取；确有旧任务依赖时再取历史 Veo 样本 | 成套确认任务 ID、查询路径、状态、媒体位置和恢复 |
| 语音 | 已启用协议的真实音频及错误体；检查编码、时长、可播放性 | 防止 JSON/PCM/hex 被误存为 MP3 |

这些样本可由网关维护者提供脱敏记录，或后续在限定费用的测试中获得。本轮已查清需要哪些适配和验证，未把缺失样本伪装成已确认的站点行为。
