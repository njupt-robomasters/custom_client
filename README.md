# RoboMaster 2026 Custom Client

一个基于 `Tkinter` 和 `MQTT` 的 RoboMaster 2026 自定义客户端，用于实时查看双方机器人血量、弹量、己方/对方总伤害，以及对方剩余金币。

## 功能

- 启动后先选择红方或蓝方客户端编号
- 连接到 `192.168.12.1:3333`
- 订阅 `GlobalUnitStatus`
- 订阅 `CustomByteBlock`
- 实时显示：
  - 己方与对方总伤害
  - 对方剩余金币
  - 双方机器人血量
  - 己方机器人弹量
- 连接失败或断开时会在界面中提示

## 运行方式

在项目根目录执行：

```powershell
python main.py
```

## 依赖

- Python 3.10+
- `paho-mqtt`
- `protobuf`

安装依赖：

```powershell
pip install paho-mqtt protobuf
```

## 默认配置

当前配置写死在 `main.py` 中：

- MQTT Broker：`192.168.12.1`
- 端口：`3333`
- 协议：`MQTT v3.1.1`
- 订阅主题：
  - `GlobalUnitStatus`
  - `CustomByteBlock`

可选客户端编号：

- 红方：`1`, `2`, `3`, `4`, `6`
- 蓝方：`101`, `102`, `103`, `104`, `106`

## 数据说明

### `GlobalUnitStatus`

`rm_custom_proto.py` 会动态构造 `GlobalUnitStatus` protobuf 类，程序从中读取：

- `robot_health`
- `robot_bullets`
- `total_damage_ally`
- `total_damage_enemy`

界面中：

- 己方血量直接显示 `robot_health` 的前 5 个值
- 己方弹量显示 `robot_bullets`
- 己方总伤害和对方总伤害显示在顶部卡片中

### `CustomByteBlock`

`CustomByteBlock.data` 是原始字节流。程序会按 RoboMaster 帧格式拆包，并解析以下命令字：

- `0x0A02`：对方机器人血量
- `0x0A03`：对方机器人弹量
- `0x0A04`：对方剩余金币

其中：

- 对方血量显示在敌方血量卡片中
- 对方弹量显示在对应卡片下方
- 剩余金币显示在独立卡片中

如果尚未收到 `CustomByteBlock`，对方血量会临时回退显示 `GlobalUnitStatus` 中的后 5 个血量值。

## 文件结构

- `main.py`：Tkinter 界面、MQTT 连接、消息订阅与渲染
- `rm_custom_proto.py`：动态构造 `GlobalUnitStatus` 和 `CustomByteBlock` protobuf 类

## 备注

- 当前程序没有单独的配置文件，服务器地址、端口和订阅主题都在 `main.py` 中定义
- 如果 MQTT 服务不可达，界面会停留在连接失败状态，并允许重新选择客户端编号

