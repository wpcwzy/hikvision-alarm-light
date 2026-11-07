# 海康 NVR 区域入侵 → 球机白光补光（Home Assistant）

当 NVR 的指定通道在夜间发生“区域入侵 / 周界防范”报警时，自动把指定海康
摄像机/球机的补光灯切换到**白光灯、亮度最大**，报警结束 **2 分钟**后恢复为
**智能补光**。

本项目是一个 Home Assistant 自定义集成，直接在现有 Home Assistant 容器内运行，
无需额外维护一个 Docker 容器。它适合“摄像机一直侦测录像，但只有夜间报警时才
需要高亮照明”的场景。

## 功能

- 订阅 NVR 的 ISAPI 报警事件流（`/ISAPI/Event/notification/alertStream`）。
- 只处理指定 NVR 通道的 `fielddetection`（区域入侵）事件。
- 仅在可配置的夜间时段（默认 `18:00–06:00`）自动触发。
- 事件 `active` 时：调用摄像机
  `/ISAPI/Image/channels/<n>/supplementLight`，切换到
  `colorVuWhiteLight` 模式，亮度 100。
- 事件 `inactive` 后保持 2 分钟（可配置），再恢复为 `eventIntelligence`
  （智能补光）或触发前保存的模式。
- 安全上限（默认 300 秒）：即使没有收到 `inactive`，也不会永久点亮。
- 如果 HA 在补光期间重启，会自动恢复智能补光，避免灯一直亮着。
- 支持两个 HTTP Digest 设备（NVR 与摄像机），可分别配置端口/HTTPS。
- 提供实体：区域入侵报警、照明增强中、事件流连接、上次入侵、测试补光、
  恢复智能补光、自动联动开关。
- 中英文界面、options 配置、diagnostics 下载。

## 已验证环境

- NVR：Hikvision DS-7808N-Z2/X(B)，V4.85.010
- 报警通道：NVR 2 号通道（后院）
- 补光设备：DS-2DC7X144DW-DE 球机，V5.8.1
- 补光灯接口：`/ISAPI/Image/channels/1/supplementLight`
- 模式：`eventIntelligence`（智能补光）↔ `colorVuWhiteLight`（白光灯）
- Home Assistant 2026.8.3（实际部署），2025.1.4（自动化测试）

## 安装

### HACS

1. HACS → 集成 → 右上角 → 自定义存储库，添加本仓库 URL，类别选
   “Integration”。
2. 搜索 **Hikvision Alarm Light Link** 安装。
3. 重启 Home Assistant。

### 手动

把 `custom_components/hikvision_alarm_light` 复制到 Home Assistant 配置目录的
`custom_components/` 下，重启。

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
| 报警通道 | `2` | 监听该 NVR 通道的 `fielddetection` 事件 |

### 第二步：补光摄像机

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| 摄像机地址 | `192.168.1.11` | 球机/摄像机的 IP |
| 端口 | `80` | |
| 补光通道 | `1` | 对应 `/ISAPI/Image/channels/1/supplementLight` |
| 夜间开始/结束 | `18:00` / `06:00` | 支持跨午夜；两者不能相同 |
| 报警结束保持 | `120` 秒 | inactive 后再保持多久 |
| 安全上限 | `300` 秒 | 没有 inactive 时的兜底 |
| 亮度 | `100` | 白光灯最大亮度 |

一个配置条目对应一条“NVR 通道 → 摄像机通道”联动。

## 实体

设备下会创建：

- `binary_sensor.*_qu_yu_ru_qin_bao_jing`：区域入侵报警（active 时开）
- `binary_sensor.*_zhao_ming_zeng_qiang_zhong`：当前是否处于白光增强状态
- `binary_sensor.*_bao_jing_shi_jian_liu`：报警事件流是否连接
- `sensor.*_shang_ci_ru_qin`：上次入侵时间
- `button.*_ce_shi_bu_guang`：立即测试补光，保持配置的 hold 时间后自动恢复
- `button.*_hui_fu_zhi_neng_bu_guang`：立即恢复智能补光
- `switch.*_zi_dong_lian_dong`：暂停/启用自动联动

建议先用“测试补光”按钮在白天验证：约 2 分钟后它会自动恢复智能补光。
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

`inactive` 事件触发“保持 2 分钟”的恢复计时器。

### 补光控制

当前摄像机支持：

```text
eventIntelligence,colorVuWhiteLight,irLight,close
```

触发时 PUT：

```xml
<SupplementLight>
  <supplementLightMode>colorVuWhiteLight</supplementLightMode>
  <whiteLightBrightness>100</whiteLightBrightness>
</SupplementLight>
```

恢复时写回触发前保存的智能补光 XML（正常情况为
`eventIntelligence + EventIntelligenceModeCfg`）。

### 夜间判断

使用 Home Assistant 本地时区和配置的时间窗口。默认 `18:00–06:00`，与摄像机
自身的补光时间段一致。

## 安全与恢复

- 报警结束时只恢复补光模式，不改变摄像机侦测、录像等设置。
- 如果 HA 重启时补光仍在进行，集成读取持久化状态并尝试恢复智能补光。
- 如果恢复失败，会每 30 秒重试，并保留 diagnostic 错误信息。
- 安全上限防止因事件流中断导致灯永久点亮。
- 集成卸载时会尝试恢复智能补光。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| 事件流未连接 | 检查 NVR 地址/凭据；确认账号可访问 ISAPI；查看实体属性 `stream_error` |
| 摄像机补光接口返回 404 | 该型号可能没有 `/ISAPI/Image/channels/<ch>/supplementLight`；在浏览器/curl 验证 |
| 报警时灯不亮 | 检查夜间时段、自动联动开关、NVR 通道是否真的产生 `fielddetection` 事件 |
| 灯一直亮 | 使用“恢复智能补光”按钮；检查安全上限；重启 HA 时会自动恢复 |
| 手机收不到通知 | 本集成只控制补光灯；NVR 报警推送仍由海康 Hik-Connect/上传中心负责 |

### 手动验证补光接口

```bash
export CAMERA_HOST=192.168.1.11
export CAMERA_USERNAME=admin
export CAMERA_PASSWORD='...'
curl --digest -u "$CAMERA_USERNAME:$CAMERA_PASSWORD" \
  "http://$CAMERA_HOST/ISAPI/Image/channels/1/supplementLight"
```

## 开发测试

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest -q
```

纯函数测试覆盖事件解析、multipart 分帧、补光 XML 与夜间判断；Home Assistant
测试覆盖配置流、实体创建、报警触发、inactive 后自动恢复、按钮和自动联动开关。

## 许可

MIT License，详见 [LICENSE](LICENSE)。
