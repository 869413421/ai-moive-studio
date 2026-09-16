# AICON · 开源 AI 视频创作工作台

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/deploy-Docker-2496ED.svg)](docs/docker-deployment-guide.md)

从小说、剧本到角色、分镜与视频，在无限画布中组织创作。AICON 支持自然语言助手搭建工作流，连接文本、图片和视频节点，也支持 Docker 自部署。

Open-source AI video creation with an infinite canvas and a natural-language workflow assistant.

[在线体验](https://aicon-studio.com/?utm_source=github&utm_medium=readme&utm_campaign=aicon) · [演示](#演示) · [快速开始](#快速开始) · [关于中转站](#关于中转站) · [使用指南](docs/user-guide.md) · [问题反馈](https://github.com/869413421/ai-moive-studio/issues)

## 赞助商

<table>
  <tr>
    <td width="180" align="center" valign="middle">
      <a href="https://metaso.cn/minimax-h3/?s=AICON"><img src="docs/media/metasota-logo.png" width="160" alt="秘塔科技 MetaSota"></a>
    </td>
    <td>
      <strong>MiniMax H3 视频生成 API｜秘塔科技</strong><br>
      秘塔科技提供高性价比的 MiniMax H3 视频生成服务：<strong>768P 仅 0.09 元/秒，2K 仅 0.15 元/秒</strong>。支持原生 2K、音画同步，API 兼容 <strong>OpenAI 协议</strong>，同时支持 <strong>ComfyUI</strong>，无需自行部署 GPU。通过 <a href="https://metaso.cn/minimax-h3/?s=AICON">AICON 专属链接注册</a>，即可领取赠送额度及专属优惠。
    </td>
  </tr>
</table>

## 演示

![AICON 无限画布：通过自然语言助手组织角色、分镜、图片与视频节点](docs/media/agent.png)

观看成片：[《静默战争》](https://www.bilibili.com/video/BV1DpvaB8EDE/) · [《艾尔登法环真人版预告》](https://www.bilibili.com/video/BV1w3igBpEXo) · [更多功能截图](docs/user-guide.md#功能截图)

## 核心能力

- **剧本到分镜**：拆解角色、场景与镜头，生成角色参考图、关键帧和过渡视频。
- **无限画布**：连接文本、图片和视频节点，通过自然语言助手搭建可编辑的工作流。
- **图文与配音**：按章节生成配图、语音和字幕，组合解说视频。
- **素材到发布**：管理生成历史与参考素材，合成视频并对接 Bilibili 分发。

> Canvas 助手负责创建节点与连线，生成任务由你手动触发。支持自定义兼容模型服务；模型调用费用由所选服务商收取。

## 快速开始

准备 Docker 和 Docker Compose v2：

```bash
git clone https://github.com/869413421/ai-moive-studio.git
cd ai-moive-studio

cp .env.production.example .env.production
# 编辑 .env.production，填写数据库、Redis、JWT、MinIO 等配置

docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

启动后访问 `http://localhost`，在「API 密钥管理」配置模型服务，再创建项目或画布开始创作。

完整步骤见 [Docker 部署指南](docs/docker-deployment-guide.md)与[模型配置说明](docs/user-guide.md#使用说明)。已有部署升级前，请查看[更新记录](docs/changelog.md)。

## 关于中转站

[AICON 模型中转站](https://api.aicon-studio.com/)是我自己部署、自己也在用的大模型兼容中转站。做这个项目需要用到不同的模型，我希望有一个方便维护、能长期使用、成本也尽量合理的接入方式，所以把它一起开放给有需要的朋友。

**AICON 不强制绑定这个站点，大家可以自行替换。** 如果你已经有自己的兼容网关或模型供应商，可以继续使用自己的 API Key 和 Base URL，并按[接入指南](docs/model-provider-configuration.md)配置对应的模型与协议。

如果你想使用我的中转站：

1. 在 [api.aicon-studio.com](https://api.aicon-studio.com/) 注册，按需购买额度，并在令牌页面创建 API Key。建议先少量体验，确认模型和效果适合自己再继续使用。
2. 在 AICON 的「API 密钥管理」中选择「自定义」，填入 API Key；OpenAI 兼容接口的 Base URL 填写 `https://api.aicon-studio.com/v1`，末尾不加斜杠。
3. 其他协议的调用方式见 [API 接口文档](https://dcsynw64g3.apifox.cn/)，模型与价格可在站内查看。

已有用户请将旧中转站地址更新为上述地址；如果还有未完成的视频任务，请先保留原连接，具体说明见[使用指南](docs/user-guide.md#使用说明)。

## 文档与交流

- [使用指南与常见问题](docs/user-guide.md)
- [模型接入与维护](docs/model-provider-configuration.md)
- [前端开发](frontend/README.md) · [后端开发](backend/README.md)
- [更新记录](docs/changelog.md) · [Star 趋势](https://www.star-history.com/#869413421/ai-moive-studio&Date)
- [问题反馈与功能建议](https://github.com/869413421/ai-moive-studio/issues)

采用 [Apache License 2.0](LICENSE) 开源。
