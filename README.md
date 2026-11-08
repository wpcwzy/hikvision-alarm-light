# 海康 NVR 区域入侵 → 球机白光补光（Home Assistant）

当 NVR 的**任意一个指定通道**（可配置多个，例如 2 和 6）在夜间发生
“区域入侵 / 周界防范”报警时，自动打开指定海康摄像机/球机的
**专用照明灯（与摄像机 Web UI 的“灯光”按钮相同的接口）**，亮灯期间保持
黑白（红外）画面，不切换白天模式。报警结束 **5 分钟**后关闭照明灯，随后通过
ISAPI 补光接口**先切换到白光补光，保持一段时间（默认 30 秒）后再切回智能补光**，
不再使用预置点来切换日夜模式。

灯光控制过程中**不会修改补光模式**：智能补光、红外灯及其亮度策略保持原样，
因此关闭照明灯后不会出现“红外灯也被关掉”的问题。

本项目是一个 Home Assistant 自定义集成，直接在现有 Home Assistant 容器内运行，
无需额外维护一个 Docker 容器。它适合“摄像机一直侦测录像，但只有夜间报警时才
需要高亮照明”的场景。

## 功能

- 订阅 NVR 的 ISAPI 报警事件流（`/ISAPI/Event/notification/alertStream`）。
- 支持配置**多个 NVR 通道**（例如 `2,6`），任一通道的 `fielddetection`
  （区域入侵）报警都会触发同一盏灯。
- 仅在可配置的夜间时段（默认 `18:00–06:00`）自动触发。
- 亮灯期间**保持黑白（红外）画面**，不改动补光模式，也不移动云台。
- 优先使用摄像机 Web UI“灯光”按钮同一个接口：
  `PUT /ISAPI/PTZCtrl/channels/<n>/auxcontrols/1`，直接打开/关闭
  PTZ 的 `LIGHT` 辅助灯。
- 不修改 `/ISAPI/Image/channels/<n>/supplementLight`，因此智能补光模式、
  红外灯亮度、IR-CUT 策略都不会被改动。
- 事件 `inactive` 后保持 5 分钟（可配置），然后关闭 aux 灯光。
- 灭灯后通过 `/ISAPI/Image/channels/<n>/supplementLight` 先切到**白光补光**
  （`colorVuWhiteLight`），保持一段可配置时间（默认 **30 秒**）后再切回
  **智能补光**（`eventIntelligence`），由补光接口恢复摄像机自动日夜策略，
  不移动云台。
- 安全上限（默认 15 分钟）：即使没有收到 `inactive`，也不会永久点亮。
- 如果 HA 在照明期间重启，会自动关闭 aux 灯光，避免灯一直亮着。
- 对于不支持 PTZ aux LIGHT 的摄像机，自动回退到 `supplementLight` 模式切换
  （兼容旧设备；本机使用 aux LIGHT）。
- 支持两个 HTTP Digest 设备（NVR 与摄像机），可分别配置端口/HTTPS。
- 提供实体：区域入侵报警、照明增强中、事件流连接、上次入侵、测试补光、
  恢复智能补光、自动联动开关。
- 中英文界面、options 配置、diagnostics 下载。

## 已验证环境

- NVR：Hikvision DS-7808N-Z2/X(B)，V4.85.010
- 报警通道：NVR 2 号通道（后院固定摄像机）和 6 号通道（后院云台），
  任一通道报警都会点亮同一盏灯
- 补光设备：DS-2DC7X144DW-DE 球机，V5.8.1
- 直接灯光接口：`/ISAPI/PTZCtrl/channels/1/auxcontrols/1`
  （与摄像机 Web UI 的“灯光”按钮相同）
- 补光模式：`eventIntelligence`（智能补光）、`irLight`（红外补光）、
  `colorVuWhiteLight`（白光补光）
- 灭灯恢复顺序：`colorVuWhiteLight` → 保持 30 秒 → `eventIntelligence`
  （ISAPI 补光接口）
- 补光配置：`eventIntelligence`，白光灯亮度 100，控制前后保持不变
- Home Assistant 2026.8.3（实际部署），2025.1.4（自动化测试）

## 安装

### HACS

1. HACS → 集成 → 右上角 → 自定义存储库，添加
   `https://github.com/wpcwzy/hikvision-alarm-light`，类别选“Integration”。
2. 搜索 **Hikvision Alarm Light Link** 安装。
3. 重启 Home Assistant。

### 手动

把 `custom_components/hikvision_alarm_light` 复制到 Home Assistant 配置目录的
`custom_components/` 下，重启。也可以直接下载 Release 中的
`hikvision_alarm_light_custom_components.zip` 解压到配置目录。

然后：设置 → 设备与服务 → 添加集成 → **Hikvision Alarm Light Link**。

## 配置

### 第一步：NVR

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| NVR 地址 | `192.168.1.10` | 支持 IP/主机名，也可粘贴 `http://ip:port` |
| 端口 | `80` | ISAPI/网页端口 |
| 使用 HTTPS | 否 | 按 NVR 实际配置 |
| 校验 TLS 证书 | 否 | 海康自签名证书一般关闭 |
| 用户名/密码 | `admin` / — | 需要远程配置权限 |
| 报警通道 | `2, 6` | 逗号分隔；监听这些 NVR 通道的 `fielddetection` 事件，任一通道报警都会触发 |

### 第二步：补光摄像机

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| 摄像机地址 | `192.168.1.11` | 球机/摄像机的 IP |
| 端口 | `80` | |
| 补光通道 | `1` | 对应 `/ISAPI/Image/channels/1/supplementLight` |
| 夜间开始/结束 | `18:00` / `06:00` | 支持跨午夜；两者不能相同 |
| 报警结束保持 | `300` 秒（5 分钟） | inactive 后再保持多久 |
| 安全上限 | `900` 秒（15 分钟） | 没有 inactive 时的兜底 |
| 亮度 | `100` | 白光灯最大亮度 |
| 白光补光保持 | `30` 秒 | 关灯后先切白光补光并保持该时长，然后再切回智能补光；0 表示立即切回 |

一个配置条目对应一条“NVR 通道（可多个）→ 摄像机通道”联动。关灯后的
关灯后白光补光的保持时间可在“配置 → 选项”中修改。

## 实体

设备下会创建：

- `binary_sensor.*_qu_yu_ru_qin_bao_jing`：区域入侵报警（active 时开）
- `binary_sensor.*_zhao_ming_zeng_qiang_zhong`：当前是否处于白光增强状态
- `binary_sensor.*_bao_jing_shi_jian_liu`：报警事件流是否连接
- `sensor.*_shang_ci_ru_qin`：上次入侵时间
- `button.*_ce_shi_bu_guang`：立即测试补光，保持配置的 hold 时间后自动恢复
- `button.*`（名称“关闭灯光”）：立即关闭增强灯光（智能补光模式保持不变）
- `switch.*_zi_dong_lian_dong`：暂停/启用自动联动

建议先用“测试补光”按钮在白天验证：约 5 分钟后它会自动关闭灯光，智能补光模式保持不变。
也可以查看 NVR/摄像机的 ISAPI 状态确认。

## 工作原理

### 报警事件

集成在后台线程中保持一个 HTTP Digest 长连接：

```text
GET /ISAPI/Event/notification/alertStream
```

解析 `multipart/mixed` 帧中的 `EventNotificationAlert`，匹配：

```xml
<eventType>fielddetection</eventType>
<eventState>active</eventState>
<channelID>2</channelID>
```

只有当 `channelID` 在配置的报警通道列表（例如 `[2, 6]`）中时才会触发；
任意一个通道的 `active` 事件都会点亮同一盏灯，`inactive` 事件触发
“保持 5 分钟”的恢复计时器。

### 灯光控制

摄像机 Web UI 的“灯光”按钮并不是切换补光模式，而是发送一条 PTZ 辅助灯光
命令。集成直接复用这个接口：

```text
PUT /ISAPI/PTZCtrl/channels/1/auxcontrols/1
Content-Type: application/xml

<?xml version="1.0" encoding="UTF-8"?>
<PTZAux><id>1</id><type>LIGHT</type><status>on</status></PTZAux>
```

关闭时 `status` 改为 `off`。注意：

- 该 XML **不能带 xmlns 命名空间**，否则部分固件会拒绝（与摄像机 Web UI
  发送的请求一致）。
- 该命令只控制 PTZ 的辅助 `LIGHT` 输出，不修改
  `/ISAPI/Image/channels/1/supplementLight`。
- 触发前后摄像机始终保持：
  `supplementLightMode=eventIntelligence`，
  `whiteLightBrightness=100`，`irLightBrightness=100`。
- 因此关闭灯光后智能补光和红外灯仍按原有策略工作，不会因为“白光灯关闭”
  而把红外灯一起关掉。

集成启动时会读取
`/ISAPI/PTZCtrl/channels/1/capabilities`，检查
`PTZAuxType` 是否包含 `LIGHT`。若没有该能力，则回退到原来的
`supplementLight` 模式切换方式。

### 关灯后的夜视模式恢复

之前用 PTZ 预置点切换日夜模式时，预置点会带动云台位置/焦距，而且球机在忙时
可能吞掉命令。现在改为直接调用补光接口，不移动云台：

```text
PUT /ISAPI/Image/channels/1/supplementLight
Content-Type: application/xml

<?xml version="1.0" encoding="UTF-8"?>
<SupplementLight version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<supplementLightMode>colorVuWhiteLight</supplementLightMode>
<whiteLightBrightness>100</whiteLightBrightness>
</SupplementLight>
```

1. **关灯**：先发送 aux LIGHT off。
2. **先切白光补光**：把补光模式设置为 `colorVuWhiteLight`（白光补光）。
3. **保持一段时间**：默认 **30 秒**（可配置 0–600 秒），让画面在补光下平稳过渡。
4. **再切智能补光**：把补光模式切回 `eventIntelligence`（智能补光），
   由摄像机自身的日夜策略接管。

如果某一步失败，只记录警告日志、另一条仍会继续尝试，不会影响灯光的开关；
最终状态会写入 `camera_mode` 属性，可在实体属性/诊断信息中查看。

### 夜间判断

使用 Home Assistant 本地时区和配置的时间窗口。默认 `18:00–06:00`，与摄像机
自身的补光时间段一致。

## 安全与恢复

- 报警结束时只关闭灯光并恢复日夜模式，不改变摄像机侦测、录像等设置。
- 如果 HA 重启时灯光仍在进行，集成读取持久化状态并发送 aux LIGHT off，
  并通过补光接口先切白光补光、再恢复智能补光。
- 如果关闭命令失败，会每 30 秒重试，并保留 diagnostic 错误信息。
- 安全上限防止因事件流中断导致灯永久点亮。
- 集成卸载时会尝试关闭 aux 灯光。
- 使用 aux 直控时不会触碰补光模式；只有不支持 aux 的摄像机才回退到模式切换。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| 事件流未连接 | 检查 NVR 地址/凭据；确认账号可访问 ISAPI；查看实体属性 `stream_error` |
| 摄像机补光接口返回 404 | 该型号可能没有 `/ISAPI/Image/channels/<ch>/supplementLight`；在浏览器/curl 验证 |
| 报警时灯不亮 | 检查夜间时段、自动联动开关、报警通道列表（选项里是否包含该通道）、NVR 通道是否真的产生 `fielddetection` 事件 |
| 灯一直亮 | 使用“关闭灯光”按钮；检查安全上限；重启 HA 时会自动关灯 |
| 灭灯后白光一直不灭/一直保持彩色 | 集成会先切白光补光、按“白光补光保持”时间后再切回智能补光；检查该时间设置与日志中的补光切换警告 |
| 灭灯后没回到智能补光 | 确认“白光补光保持”时间已生效；可用 curl 手动验证补光接口，若球机吞命令可适当加长保持时间 |
| 手机收不到通知 | 本集成只控制补光灯；NVR 报警推送仍由海康 Hik-Connect/上传中心负责 |

### 手动验证 aux 灯光接口

```bash
export CAMERA_HOST=192.168.1.11
export CAMERA_USERNAME=admin
export CAMERA_PASSWORD='...'
curl --digest -u "$CAMERA_USERNAME:$CAMERA_PASSWORD" \
  "http://$CAMERA_HOST/ISAPI/PTZCtrl/channels/1/capabilities"

curl --digest -u "$CAMERA_USERNAME:$CAMERA_PASSWORD" \
  -X PUT -H "Content-Type: application/xml" \
  --data-binary '<?xml version="1.0" encoding="UTF-8"?><PTZAux><id>1</id><type>LIGHT</type><status>on</status></PTZAux>' \
  "http://$CAMERA_HOST/ISAPI/PTZCtrl/channels/1/auxcontrols/1"
```

### 手动验证补光模式切换

```bash
# 切到白光补光
curl --digest -u "$CAMERA_USERNAME:$CAMERA_PASSWORD" \
  -X PUT -H "Content-Type: application/xml" \
  --data-binary '<?xml version="1.0" encoding="UTF-8"?><SupplementLight version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema"><supplementLightMode>colorVuWhiteLight</supplementLightMode><whiteLightBrightness>100</whiteLightBrightness></SupplementLight>' \
  "http://$CAMERA_HOST/ISAPI/Image/channels/1/supplementLight"

# 切回智能补光
curl --digest -u "$CAMERA_USERNAME:$CAMERA_PASSWORD" \
  -X PUT -H "Content-Type: application/xml" \
  --data-binary '<?xml version="1.0" encoding="UTF-8"?><SupplementLight version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema"><supplementLightMode>eventIntelligence</supplementLightMode><EventIntelligenceModeCfg><brightnessRegulatMode>auto</brightnessRegulatMode><whiteLightBrightness>100</whiteLightBrightness><irLightBrightness>100</irLightBrightness></EventIntelligenceModeCfg></SupplementLight>' \
  "http://$CAMERA_HOST/ISAPI/Image/channels/1/supplementLight"
```

## 开发测试

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest -q
```

纯函数测试覆盖事件解析、multipart 分帧、补光 XML 与夜间判断；
Home Assistant 测试覆盖配置流、选项流、旧配置迁移、多通道任一触发、实体创建、
关灯后“先白光补光、保持一段时间、再切智能补光”的恢复流程及保持时间、
inactive 后自动恢复、按钮和自动联动开关。

### 打包发布

```bash
.venv/bin/python scripts/build_release.py --version 1.2.0
git archive --format=zip --prefix=hikvision-alarm-light-1.2.0/ \
  -o dist/hikvision-alarm-light-1.2.0.zip v1.2.0
gh release create v1.2.0 --title "v1.2.0" --notes-file <说明文件> \
  dist/hikvision_alarm_light_manual_install.zip \
  dist/hikvision_alarm_light_custom_components.zip
```

`hacs.json` 中 `zip_release` 使用
`hikvision_alarm_light_manual_install.zip` 作为 HACS 安装包。

## 许可

MIT License，详见 [LICENSE](LICENSE)。
