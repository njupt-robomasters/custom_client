# RoboMaster 2026 自定义客户端

这是一个基于 Tkinter 和 MQTT 的 RoboMaster 2026 自定义客户端。程序启动后会先选择红方或蓝方的客户端编号，连接成功后订阅 `GlobalUnitStatus` 主题，并在界面中实时显示双方累计伤害和机器人血量。

## 运行方式

在当前目录执行：

```powershell
python main.py
```

## 默认连接配置

- MQTT 服务器：`192.168.12.1:3333`
- 订阅主题：`GlobalUnitStatus`
- MQTT 协议版本：`MQTT v3.1.1`
- `client_id`：使用界面中选择的编号

可选编号：

- 红方：`1`、`2`、`3`、`4`、`6`
- 蓝方：`101`、`102`、`103`、`104`、`106`

## 界面功能

程序包含两个主要页面：

- 阵营与编号选择页：选择红方或蓝方客户端编号后开始连接 MQTT 服务器。
- 状态展示页：连接后显示当前连接状态、订阅主题、双方累计总伤害，以及 10 个机器人血量。

状态展示页中的机器人分为：

- 己方：1、2、3、4、7 号机器人
- 对方：1、2、3、4、7 号机器人

## 数据说明

客户端解析 `GlobalUnitStatus` protobuf 消息，并使用以下字段更新界面：

- `robot_health`：机器人血量列表，最多展示前 10 个值。
- `total_damage_ally`：己方累计总伤害。
- `total_damage_enemy`：对方累计总伤害。

如果收到的 `robot_health` 少于 10 个值，缺失位置会按 `0` 显示。

## 依赖

运行前需要确保 Python 环境中已安装：

- `paho-mqtt`
- `protobuf`

可通过以下命令安装：

```powershell
pip install paho-mqtt protobuf
```
