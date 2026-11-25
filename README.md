# Modbus MQTT Gateway

一个完全用软件运行的工业物联网实验项目。模拟电表通过 Modbus TCP 提供寄存器，Python 网关把原始值换算成带单位的读数，再以 MQTT QoS 1 发布给订阅端。不需要实体电表、Docker 或云账号。

[打开 GitHub Pages 交互演示](https://wenjialei15.github.io/modbus-mqtt-gateway/) · [寄存器配置](modbus_mqtt_gateway/demo.toml) · MIT

## 快速开始

需要 Python **3.11–3.13**。从仓库根目录执行：

```bash
git clone https://github.com/wenjialei15/modbus-mqtt-gateway.git
cd modbus-mqtt-gateway
python -m venv .venv
```

在 Windows PowerShell 中运行：

```powershell
.venv\Scripts\python.exe -m pip install ".[demo]"
.venv\Scripts\python.exe -m modbus_mqtt_gateway demo --outage --duration 15
```

在 macOS 或 Linux 中运行：

```bash
.venv/bin/python -m pip install ".[demo]"
.venv/bin/python -m modbus_mqtt_gateway demo --outage --duration 15
```

这个命令在当前终端启动模拟电表、aMQTT Broker、网关和订阅端。约第 6 秒关闭模拟电表的 TCP 监听，约第 11 秒重新开放。终端会打印真实的 MQTT 消息，依次看到 `online`、`offline` 和 `online`。去掉 `--duration 15` 可持续运行，按 Ctrl+C 停止。

## 链路和消息

```text
模拟电表 127.0.0.1:15020  →  Python 网关  →  MQTT Broker 127.0.0.1:18883  →  订阅端
        Modbus TCP FC04          换算                QoS 1
```

| MQTT 主题 | 消息 | 保留 |
| --- | --- | --- |
| `lab/meter-01/telemetry` | 每次完整采集的读数，含设备名、UTC 时间和值与单位 | 否 |
| `lab/meter-01/status` | 状态变化。网关重连 Broker 后重新发布当前状态 | 是 |

```json
{
  "device": "meter-01",
  "observed_at": "2026-11-25T08:30:00.000Z",
  "metrics": {
    "voltage": {"value": 230.0, "unit": "V"},
    "current": {"value": 4.4, "unit": "A"},
    "power": {"value": 951, "unit": "W"},
    "energy": {"value": 125.8, "unit": "kWh"}
  }
}
```

Modbus 读取失败时，状态变为 `offline`，网关关闭失效连接，下一轮重试。设备恢复后，状态变回 `online`，遥测继续发布。网关退出时发布 `unknown`，异常断开由 MQTT 遗嘱发布 `unknown`，遗嘱的 `observed_at` 为 `null`。Broker 离线期间，网关继续尝试采集，恢复连接后继续发布新读数。网关不保存离线历史，QoS 1 允许重复投递。

## 配置寄存器

把 [demo.toml](modbus_mqtt_gateway/demo.toml) 复制为 `gateway.toml` 并修改目标地址、端口、设备 ID、采集间隔或主题前缀。`--config` 放在子命令前。

| 名称 | 功能码 | 零基地址 | 类型 | 倍率 | 单位 |
| --- | --- | --- | --- | --- | --- |
| voltage | 04 | 0 | uint16 | 0.1 | V |
| current | 04 | 1 | uint16 | 0.01 | A |
| power | 04 | 2 | int16 | 1 | W |
| energy | 04 | 3–4 | uint32 | 0.001 | kWh |

`input` 对应功能码 04，`holding` 对应功能码 03。可配置 `int16`、`uint16`、`int32` 和 `uint32`。32 位寄存器默认高字在前，低字在前时设置 `word_order = "little"`。各字内部始终高字节在前。配置用协议中的零基地址，例如手册以 30001 表示第一个输入寄存器时，填写 0。

## 分开运行或接入 Mosquitto

激活虚拟环境后，在四个终端分别运行：

```bash
python -m modbus_mqtt_gateway simulator
python -m modbus_mqtt_gateway broker
python -m modbus_mqtt_gateway gateway
python -m modbus_mqtt_gateway subscribe
```

也可以用本地 [Mosquitto](https://mosquitto.org/) 替换内置 Broker。使用下面的实验室配置，然后以 `mosquitto -c mosquitto.conf` 启动。

```conf
listener 18883 127.0.0.1
allow_anonymous true
```

```bash
mosquitto_sub -h 127.0.0.1 -p 18883 -t "lab/meter-01/#" -q 1 -v
```

模拟电表和内置 Broker 只绑定回环地址。网关支持单个 Modbus TCP 端点和 MQTT 3.1.1 TCP，可用于本机协议实验。GitHub Pages 在浏览器内模拟链路和异常，不连接本机服务。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖寄存器换算和配置校验，以及真实 Modbus TCP 与 MQTT 连接上的采集、设备掉线、恢复和网关退出。
