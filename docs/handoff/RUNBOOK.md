# 本地运行、复现与交接核验

## 干净检出与资源

```bash
git clone https://github.com/wind-chaser-github/OpenStoryline.git
cd OpenStoryline
git status --short
```

按仓库[中文README](../../README_zh.md)的官方安装/资源下载说明准备Python、FFmpeg、模型权重与资源。优先隔离虚拟环境；本次交接没有修改`requirements.txt`、Dockerfile或安装脚本，也没有验证所有平台的一键安装。

源码现在位于维护者工作区顶层`FireRed-OpenStoryline/`，不再位于`.omx/references/`。其他机器使用自己的检出路径。`iic`只是原机器的ASR资源链接，不提交；新机器按官方安装方式准备资源。

## 零模型调用的防覆盖回归

需要Python 3.11+、项目运行依赖、`ffmpeg`和`ffprobe`在PATH中。无需API key、私人原片或ASR权重，不启动Web/MCP：

```bash
PYTHONPATH=src:. python -m unittest discover -s tests -v
git diff --check
```

测试生成临时合成视频，用固定剪辑决策调用真实`SpeechRoughCutNode.process`和FFmpeg；禁止测试期间的socket连接与DNS；退出时清理临时视频。验收文件/ID唯一和实际时长，不声称验证AI选片。

预期3项通过。未修复的官方基线在多源用例因输出路径/ID重复而失败。合成测试与真实视频验收是不同层次，不能互相替代。

## 官方服务配置与启动（会产生付费调用，非本次交接自动执行）

1. 复制官方配置到已忽略的`config.local.toml`。不要把密钥写入受跟踪的`config.toml`。
2. 配置MCP未占用的本机端口；下例Web端口18793也须确认未占用。仅监听127.0.0.1。
3. `[llm]`、`[vlm]`设置超时和`max_retries=0`。官方Web可在配置不完整时回退到`OPENSTORYLINE_LLM_MODEL/BASE_URL/API_KEY`及`OPENSTORYLINE_VLM_MODEL/BASE_URL/API_KEY`环境变量；由安全方式注入，不在命令行/日志打印密钥。
4. 暂时保留默认`.storyline/.server_cache`缓存位置，以新session隔离。独立配置目录会触发当前Web预览白名单问题，见I-05。
5. 确认`.storyline/skills`、`prompts`、`resource`、模型权重可用。旧实验脚本引用旧目录，禁止直接复用。

```bash
cp config.toml config.local.toml
# 按上面的要求编辑本地配置、准备环境变量与资源，再启动。
export OPENSTORYLINE_CONFIG="$PWD/config.local.toml"
export PYTHONPATH="$PWD/src:$PWD"
python -m open_storyline.mcp.server
```

另一个终端在相同目录、配置与环境下：

```bash
export OPENSTORYLINE_CONFIG="$PWD/config.local.toml"
export PYTHONPATH="$PWD/src:$PWD"
uvicorn agent_fastapi:app --host 127.0.0.1 --port 18793
```

`OPENSTORYLINE_CONFIG`在两个服务中必须指向同一配置。不要启动旧自写编排器或更改官方skills后声称默认流程。

## 一次真实流程的接口路径

官方`agent_fastapi.py`提供：

1. `POST /api/sessions`创建会话。
2. `POST /api/sessions/{session_id}/media`上传用户授权的素材，multipart字段`files`。
3. WebSocket `/ws/sessions/{session_id}/chat`，使用官方`chat.send`协议（可参考官方`.claude/skills/openstoryline-use/scripts/bridge_openstoryline.py`）。
4. 仅发送剪辑目标；如官方Agent请求计划确认，只做必要确认，不指定技能、片段或时间线。
5. 保存`tool.start/end`、最终响应、artifact与全部模型usage。收费子调用发生在MCP sampling，不能只截取Web消息计数。
6. `GET /api/sessions/{session_id}`检查历史；`GET /api/sessions/{session_id}/preview?path=...`检查授权文件预览/下载。
7. 失败通过`POST /api/sessions/{session_id}/cancel`停止；断开WebSocket不等于取消任务。等待并核查在途模型调用和渲染状态。

提示词基线（不要偷偷添加工具步骤）：

> 请把我上传的太阳系科普视频剪成45到70秒的精华短片。请根据实际原声内容挑选两到三颗行星，每颗保留完整、有价值的特点介绍；去掉开场、重复铺垫和结尾，保留清楚的主语和上下文。保持原片先后顺序、原声和对应的中文字幕，不加配乐、不另配音、不生成新画面。

## 验收与费用

先看模型输入/输出和artifact，再看页面。按[方案中的验收表](PLAN.md)逐项取证，不以模型口头完成为准。重启后GET历史不会创建Agent；不要为恢复历史发送新chat消息。

- 每次运行前记录代码SHA、diff、配置差异、素材摘要、请求和预算。
- 记录所有成功/失败/取消请求的actual usage与计量缺口，区分估算和供应商计量。
- 最新测试的约22万token阈值是外部观察器设置，并未实现为官方服务能力。本仓库不提供默认成本上限；伙伴应先准备可审计的调用计量/停止机制再做付费测试。
- 预算阈值通常在调用边界判断，在途响应可能越线；不能承诺硬性费用封顶。
- 失败停止、离线定位；有新证据和明确预算后才考虑下一轮。不要自动发多轮纠错。

## 已有本地证据（不随Git上传）

位于原工作区`.omx/artifacts/`：

- `openstoryline-restore-official-20261015/`：撤回范围、唯一补丁、真实回复回放红绿结果及旧实验备份。
- `openstoryline-restored-live-20261015-r1/`：最新完整模型消息/回复/usage、原片摘要、节点JSON、取消事件、重启历史、音频相关性和缓存成片。

仓库移动后，这些旧脚本和链接可能失效；不要批量替换后直接重新收费运行。Git内的`evidence/`是人工明确筛选过的脱敏摘录，不包含私人视频、完整转录、API key或原始模型消息中的图片。
