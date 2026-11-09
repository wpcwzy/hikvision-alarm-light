# 海康 NVR 区域入侵 → 球机白光补光（Home Assistant）

当 NVR 的**任意一个指定通道**（可配置多个，例如 2 和 6）在夜间发生
“区域入侵 / 周界防范”报警时，通过 ISAPI 补光接口把海康球机的**所有补光通道**
（可配置多个，例如球机的通道 1 和通道 2）切换为**白光补光**：

- 补光模式：`colorVuWhiteLight`（白光补光）
- 亮度调节模式：`on`（常开）
- 亮度：`100`（可配置）

报警停止后保持 **300 秒**（可配置），或持续报警达到 **900 秒**（安全上限）后，
把补光模式切回**智能补光** `eventIntelligence`，由摄像机自身的日夜策略接管。

> ⚠️ 本集成**不再使用 PTZ 辅助 LIGHT 接口**。该接口在部分海康球机固件上存在
> “关灯后红外灯也熄灭”的问题，因此补光全部通过 `supplementLight` 模式切换完成。

本项目是一个 Home Assistant 自定义集成，直接在现有 Home Assistant 容器内运行，
无需额外维护一个 Docker 容器。它适合“摄像机一直侦测录像，但只有夜间报警时才
需要高亮照明”的场景。

## 功能

- 订阅 NVR 的 ISAPI 报警事件流（`/ISAPI/Event/notification/alertStream`）。
- 支持配置**多个 NVR 报警通道**（例如 `2,6`），任一通道的 `fielddetection`
  （区域入侵）报警都会触发。
- 支持配置**多个球机补光通道**（例如 `1,2`），报警时所有通道一起切换补光模式。
- 仅在可配置的夜间时段（默认 `18:00–06:00`）自动触发。
- 报警时：白光补光、亮度调节模式常开、亮度 100%（可通过选项修改亮度）。
- 报警结束后保持可配置时间（默认 300 秒）再切回智能补光；
  持续报警时安全上限（默认 900 秒）会强制切回智能补光。
- 不修改摄像机侦测、录像等设置，也不使用 PTZ 辅助 LIGHT / 预置点。
- 支持两个 HTTP Digest 设备（NVR 与摄像机），可分别配置端口/HTTPS。
- 提供实体：区域入侵报警、照明增强中、事件流连接、上次入侵、测试补光、
  关闭灯光、**手动灯光开关“后院灯”**、自动联动开关。
- “后院灯”是标准开关实体，可桥接到 **HomeKit / Apple 家庭**。
- 中英文界面、options 配置、diagnostics 下载。

## 已验证环境

- NVR：Hikvision DS-7808N-Z2/X(B)，V4.85.010
- 报警通道：NVR 2 号通道（后院固定摄像机）和 6 号通道（后院云台），
  任一通道报警都会触发
- 补光设备：DS-2DC7X144DW-DE 球机，V5.8.1，补光通道 **1 和 2**
- 补光接口：`PUT /ISAPI/Image/channels/<n>/supplementLight`
- 实测补光文档（通道 1/2 均支持）：
  `colorVuWhiteLight` + `whiteLightBrightness=100` +
  `mixedLightBrightnessRegulatMode=on`（常开） → `eventIntelligence`
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
| 报警通道 | `2, 6` | 逗号分隔；监听这些 NVR 通道的 `fielddetection` 事件 |

### 第二步：补光球机

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| 摄像机地址 | `192.168.1.11` | 球机/摄像机的 IP |
| 端口 | `80` | |
| 补光通道 | `1, 2` | 逗号分隔；报警时这些图像通道一起切换补光模式 |
| 夜间开始/结束 | `18:00` / `06:00` | 支持跨午夜；两者不能相同 |
| 报警结束保持 | `300` 秒 | `inactive` 后再保持多久后切回智能补光 |
| 安全上限 | `900` 秒 | 持续报警时的兜底，超时强制切回智能补光 |
| 亮度 | `100` | 白光补光亮度（0–100） |

一个配置条目对应一条“NVR 报警通道（可多个）→ 球机补光通道（可多个）”联动。
以上参数都可在“配置 → 选项”中修改。

## 实体

设备下会创建：

- `binary_sensor.*_qu_yu_ru_qin_bao_jing`：区域入侵报警（active 时开）
- `binary_sensor.*_zhao_ming_zeng_qiang_zhong`：当前是否处于白光增强状态
- `binary_sensor.*_bao_jing_shi_jian_liu`：报警事件流是否连接
- `sensor.*_shang_ci_ru_qin`：上次入侵时间
- `button.*_ce_shi_bu_guang`：立即测试白光补光，保持配置的 hold 时间后自动切回智能补光
- `button.*`（名称“关闭灯光”）：立即切回智能补光
- `switch.hou_yuan_deng`（名称“后院灯”）：手动开关白光补光；打开后一直亮灯，
  直到再次关闭或安全上限（默认 15 分钟）触发；可通过 HomeKit Bridge 桥接到
  Apple 家庭
- `switch.*_zi_dong_lian_dong`：暂停/启用自动联动

### 添加到 HomeKit / Apple 家庭

“后院灯”是一个普通开关实体，可以桥接到 Apple 家庭：

1. 如果还没有 HomeKit Bridge：设置 → 设备与服务 → 添加集成 → **HomeKit Bridge**，
   选择「桥接（Bridge）」模式并保存。
2. 在 HomeKit Bridge 的「配置 → 包含实体」中勾选 **后院灯**
   （实体 `switch.hou_yuan_deng`；也可以直接按 `switch` 域选择）。
3. 按提示用 iPhone「家庭」App 扫描二维码/输入配对码完成配对。
4. 之后即可在「家庭」App、控制中心或家庭自动化里直接开关“后院灯”。

桥接后 HA 里的开关状态和 HomeKit 会双向同步；报警自动点灯时，HomeKit 里的
“后院灯”也会显示为“开”。

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
任意一个通道的 `active` 事件都会点亮灯光，`inactive` 事件触发
“保持 300 秒”的恢复计时器。

### 补光模式切换（不使用 PTZ 辅助灯）

报警时，对每一个配置的补光通道发送：

```text
PUT /ISAPI/Image/channels/1/supplementLight   （通道 2 同理）
Content-Type: application/xml

<?xml version="1.0" encoding="UTF-8"?>
<SupplementLight version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<supplementLightMode>colorVuWhiteLight</supplementLightMode>
<whiteLightBrightness>100</whiteLightBrightness>
<mixedLightBrightnessRegulatMode>on</mixedLightBrightnessRegulatMode>
</SupplementLight>
```

其中：

- `supplementLightMode=colorVuWhiteLight`：白光补光；
- `mixedLightBrightnessRegulatMode=on`：亮度调节模式“常开”（固定亮度，
  不随环境自动调节）；
- `whiteLightBrightness`：亮度，取配置值（默认 100）。

报警结束保持时间到（或安全上限到）后，对所有补光通道切回智能补光：

```text
PUT /ISAPI/Image/channels/1/supplementLight

<SupplementLight version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<supplementLightMode>eventIntelligence</supplementLightMode>
<EventIntelligenceModeCfg>
<brightnessRegulatMode>auto</brightnessRegulatMode>
<whiteLightBrightness>100</whiteLightBrightness>
<irLightBrightness>100</irLightBrightness>
</EventIntelligenceModeCfg>
</SupplementLight>
```

这样智能补光和红外灯继续按摄像机自身策略工作，不会出现“关灯后红外灯也熄灭”
的问题（这正是弃用 PTZ 辅助 LIGHT 接口的原因）。

### 夜间判断

使用 Home Assistant 本地时区和配置的时间窗口。默认 `18:00–06:00`，与摄像机
自身的补光时间段一致。

## 安全与恢复

- 报警结束时只切换补光模式，不改变摄像机侦测、录像等设置。
- 如果 HA 重启时灯光仍在进行，集成读取持久化状态并把所有补光通道切回智能补光。
- 任意通道切换失败只记录警告日志，不影响其他通道；安全上限防止灯光永久点亮。
- 集成卸载时会自动切回智能补光。
- 不使用 PTZ 辅助 LIGHT，也不调用预置点，云台位置不会被改动。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| 事件流未连接 | 检查 NVR 地址/凭据；确认账号可访问 ISAPI；查看实体属性 `stream_error` |
| 补光接口返回 404 | 该型号可能没有 `/ISAPI/Image/channels/<ch>/supplementLight`；在浏览器/curl 验证 |
| 报警时灯不亮 | 检查夜间时段、自动联动开关、报警通道列表（选项里是否包含该通道）、补光通道是否正确 |
| 灯一直亮 | 使用“关闭灯光”按钮或 HomeKit“后院灯”开关；检查安全上限；重启 HA 时会自动切回智能补光 |
| 灭灯后红外灯也不亮 | 本集成已弃用 PTZ 辅助 LIGHT；确认 HACS 中已更新到 v1.6.0+ 并重启 HA |
| 灭灯后没回到智能补光 | 查看日志中的 `Could not restore smart supplement light`，检查补光通道与权限，可用 curl 手动验证 |
| 手机收不到通知 | 本集成只控制补光灯；NVR 报警推送仍由海康 Hik-Connect/上传中心负责 |

### 手动验证补光接口

```bash
export CAMERA_HOST=192.168.1.11
export CAMERA_USERNAME=admin
export CAMERA_PASSWORD='...'

# 切换到白光补光（常开、100%）
for CH in 1 2; do
  curl --digest -u "$CAMERA_USERNAME:$CAMERA_PASSWORD" \
    -X PUT -H "Content-Type: application/xml" \
    --data-binary '<?xml version="1.0" encoding="UTF-8"?><SupplementLight version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema"><supplementLightMode>colorVuWhiteLight</supplementLightMode><whiteLightBrightness>100</whiteLightBrightness><mixedLightBrightnessRegulatMode>on</mixedLightBrightnessRegulatMode></SupplementLight>' \
    "http://$CAMERA_HOST/ISAPI/Image/channels/$CH/supplementLight"
done

# 切回智能补光
for CH in 1 2; do
  curl --digest -u "$CAMERA_USERNAME:$CAMERA_PASSWORD" \
    -X PUT -H "Content-Type: application/xml" \
    --data-binary '<?xml version="1.0" encoding="UTF-8"?><SupplementLight version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema"><supplementLightMode>eventIntelligence</supplementLightMode><EventIntelligenceModeCfg><brightnessRegulatMode>auto</brightnessRegulatMode><whiteLightBrightness>100</whiteLightBrightness><irLightBrightness>100</irLightBrightness></EventIntelligenceModeCfg></SupplementLight>' \
    "http://$CAMERA_HOST/ISAPI/Image/channels/$CH/supplementLight"
done
```

## 开发测试

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest -q
```

纯函数测试覆盖事件解析、multipart 分帧、补光 XML 与夜间判断；
Home Assistant 测试覆盖配置流、选项流、旧配置迁移、多报警通道任一触发、
多补光通道同时切换、亮灯失败回滚、inactive 后保持恢复、安全上限、手动开关、
按钮和自动联动开关。

### 打包发布

```bash
.venv/bin/python scripts/build_release.py --version 1.6.0
git archive --format=zip --prefix=hikvision-alarm-light-1.6.0/ \
  -o dist/hikvision-alarm-light-1.6.0.zip v1.6.0
gh release create v1.6.0 --title "v1.6.0" --notes-file <说明文件> \
  dist/hikvision_alarm_light_manual_install.zip \
  dist/hikvision_alarm_light_custom_components.zip
```

`hacs.json` 中 `zip_release` 使用
`hikvision_alarm_light_manual_install.zip` 作为 HACS 安装包。

## 许可

MIT License，详见 [LICENSE](LICENSE)。
