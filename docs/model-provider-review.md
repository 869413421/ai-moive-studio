# 模型供应重构：自审与验证

日期：2026-09-10。分支：`codex/model-provider-unification`，基线 `43750da`。按用户指定的 review-agent 流程检查未提交改动、新增文件、调用方和相关测试；审查阶段只读，记录问题后切回实现阶段修复并复测。

## 发现并修复的问题

- **[P1] 避免多密钥目录并发使用同一个 AsyncSession。** 改为一次查询所属用户的激活密钥，并行部分仅执行上游网络请求。回归测试禁止在并行阶段再次查询密钥。
- **[P1] 历史版本应用不得依赖当前模型是否可用。** 移除误加到历史切换的模型校验，保留新生成的校验；前端测试覆盖模型隐藏后的历史作品应用。
- **[P1] 后台必须继续查询已接受但仍排队的视频。** 派发和执行查询均覆盖 pending / processing，筛选已拿到 provider_task_id 的记录，避免排队任务失去后台查询。
- **[P1] 完成状态但尚无文件 URL 时不能提前结束本地任务。** 保留 processing，等待可下载结果；测试覆盖完成响应没有资源的情况。
- **[P1] Seedream Pro 必须使用文档允许的尺寸。** 修正非方形比例映射，使用 2368×1776、1776×2368、2816×1584、1584×2816；测试对照文档枚举。
- **[P2] 过期视频必须收敛到失败终态。** 将文档中的 expired 映射为 failed，避免无限查询。
- **[P2] Qwen 编辑参考图上限应为三张。** 按具体编辑文档修正能力配置，超限在请求前报错。
- **[P2] 无效连接配置应返回可处理的输入错误。** 校验失败返回 400；编辑时清空地址恢复所选供应商默认值。

修复后复查：**No findings.** 未发现仍需修复的已知引入缺陷。这里的结论针对已实现代码与本地测试，不能替代站点收费调用验收。

## 验证结果

后端相关测试 **73 passed**，包括 Canvas API 集成、Assistant 业务、目录交集与缓存隔离、JSON 配置热更新、协议请求和响应、音频 WAV 封装、视频提交恢复、历史保留及迁移 030 升降级。数据库集成使用隔离的 SQLite；迁移验证不代表生产 PostgreSQL 已执行。

```sh
cd backend
DYLD_LIBRARY_PATH=/opt/homebrew/opt/libmagic/lib .venv/bin/python -m pytest -c pyproject.toml \
  tests/integration/test_canvas_api.py \
  tests/unit/test_model_catalog.py tests/unit/test_gateway_provider.py \
  tests/unit/test_canvas_assistant_agent_factory.py \
  tests/unit/test_canvas_assistant_workflow_service.py \
  tests/unit/test_canvas_assistant_service.py tests/unit/test_canvas_assistant_tools.py \
  --disable-warnings
```

macOS 使用 libmagic 动态库路径；Linux 镜像使用系统 libmagic，无需上述环境变量。

前端相关测试 **28 passed**；生产构建通过。覆盖密钥与模型匹配、配置能力比例、音色切换、晚到的旧密钥目录响应、隐藏型号历史应用、画布生成及历史链路。

```sh
cd frontend
npx vitest run src/tests/unit/views/canvas/CanvasEditor.test.js \
  src/tests/unit/utils src/tests/unit/composables/useCanvasGeneration.test.js \
  src/tests/unit/components/GenerateAudioDialog.test.js
npm run build
```

`git diff --check`、后端 Python 编译通过；运行代码中只剩统一入口创建 AsyncOpenAI，不再引用被删除的供应商类。

## 全量测试的基线问题

完整前端测试结果为 **58 passed / 31 failed**。将原始 `43750da` 导出到隔离目录，用同一依赖运行：**55 passed / 同样 31 failed**，失败用例列表完全一致，集中在 auth store 与 Login 测试模拟配置。此次新增和修改的相关用例全部通过。

完整后端 unit 目录在收集阶段有四个原有错误：SupportedFileType 旧导入以及不存在的 src.api.files / src.api.projects / src.api.upload。对原始基线运行同一命令，得到相同四项错误。这些无关测试未顺手重构，也未宣称全量测试通过。

## 尚未获得的证据

- 无有效测试密钥和收费额度授权，未进行 28 个精选型号的真实生成验证；特别是 sd-* 站点 ID、Responses 兼容层、原生 Gemini 图片/配音仍需要上游实测。
- 未部署，未对生产 PostgreSQL 应用迁移，未进行浏览器视觉验收。
- 模型发布日期没有独立可靠来源时保持为空，不把站点元数据更新时间当发布时间。排序机制已支持已核实日期降序，目前无日期条目按精选文件顺序展示。

真实冒烟应至少覆盖每种已启用协议：纯文本和 JSON、Responses 流、图片创建和参考编辑、视频提交/查询/下载、MP3 和 WAV 配音，并在提交前明确额度上限。没有这些证据，不能给出“99% 线上可用”的承诺。
