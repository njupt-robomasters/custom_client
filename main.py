from __future__ import annotations

import queue
import struct
import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass

import paho.mqtt.client as mqtt

from rm_custom_proto import CustomByteBlock, GlobalUnitStatus


BROKER_HOST = "127.0.0.1"
BROKER_PORT = 3333
TOPIC_GLOBAL_UNIT_STATUS = "GlobalUnitStatus"
TOPIC_CUSTOM_BYTE_BLOCK = "CustomByteBlock"
WINDOW_TITLE = "RoboMaster 2026 自定义客户端"
PREFERRED_FONT_FAMILIES = [
    "Noto Sans CJK SC",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
    "PingFang SC",
    "SimHei",
]

FONT_FAMILY = "Noto Sans CJK SC"

RED_IDS = [1, 2, 3, 4, 6]
BLUE_IDS = [101, 102, 103, 104, 106]

ALLY_LABELS = ["No. 1", "No. 2", "No. 3", "No. 4", "No. 6"]
ALLY_STATUS_LABELS = ["No. 1", "No. 2", "No. 3", "No. 4", "No. 6", "No. 7"]
ENEMY_LABELS = ["No. 1", "No. 2", "No. 3", "No. 4", "No. 6", "No. 7"]

TEAM_STYLES = {
    "red": {
        "accent": "#d32f2f",
        "accent_dark": "#9f1d1d",
        "page_bg": "#fff8f8",
        "panel_bg": "#ffffff",
        "panel_border": "#efb0b0",
        "ally_fill": "#d32f2f",
        "enemy_fill": "#2d6cdf",
        "title_fg": "#ffffff",
    },
    "blue": {
        "accent": "#2563eb",
        "accent_dark": "#1847a8",
        "page_bg": "#f8fbff",
        "panel_bg": "#ffffff",
        "panel_border": "#adc4ef",
        "ally_fill": "#2563eb",
        "enemy_fill": "#d32f2f",
        "title_fg": "#ffffff",
    },
}


def _select_font_family(root: tk.Misc) -> str:
    global FONT_FAMILY

    try:
        available = set(tkfont.families(root))
    except Exception:
        available = set()

    for family in PREFERRED_FONT_FAMILIES:
        if family in available:
            FONT_FAMILY = family
            return family

    try:
        FONT_FAMILY = tkfont.nametofont("TkDefaultFont").cget("family")
    except Exception:
        FONT_FAMILY = "sans-serif"
    return FONT_FAMILY


def _ui_font(size: int, bold: bool = False):
    return (FONT_FAMILY, size, "bold") if bold else (FONT_FAMILY, size)


def _team_from_client_id(client_id: int) -> str:
    return "red" if client_id < 100 else "blue"


def _safe_int(value) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _hex_preview(data: bytes, limit: int = 32) -> str:
    if not data:
        return "-"
    preview = data[:limit].hex(" ")
    if len(data) > limit:
        return f"{preview} ..."
    return preview


def _u16(data: bytes, offset: int) -> int:
    if offset + 2 > len(data):
        return 0
    return struct.unpack_from("<H", data, offset)[0]


def _u16_optional(data: bytes, offset: int) -> int | None:
    if offset + 2 > len(data):
        return None
    return struct.unpack_from("<H", data, offset)[0]


def _crc8(data: bytes) -> int:
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc >> 1) ^ 0x8C) if crc & 0x01 else (crc >> 1)
    return crc


def _crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc >> 1) ^ 0x8408) if crc & 0x0001 else (crc >> 1)
    return crc


@dataclass
class StatusSnapshot:
    robot_health: list[int]
    total_damage_ally: int
    total_damage_enemy: int


@dataclass
class OpponentSnapshot:
    robot_bullets: list[int | None]
    remaining_gold: int | None


def _decode_rm_frames(payload: bytes, *, diag: dict[str, object] | None = None) -> dict[int, bytes]:
    frames: dict[int, bytes] = {}
    index = 0
    limit = len(payload)
    crc8_fail = 0
    crc16_fail = 0
    skipped_bytes = 0
    cmd_ids: list[int] = []
    candidate_headers: list[tuple[int, str, int]] = []

    while index + 9 <= limit:
        if payload[index] != 0xA5:
            index += 1
            skipped_bytes += 1
            continue

        if index + 5 > limit:
            break

        header = payload[index : index + 5]
        if _crc8(header[:4]) != header[4]:
            candidate_headers.append((index, header[:5].hex(" "), _crc8(header[:4])))
            index += 1
            crc8_fail += 1
            continue

        data_length = int.from_bytes(header[1:3], "little")
        total_length = 5 + 2 + data_length + 2
        if index + total_length > limit:
            if diag is not None:
                diag["truncated"] = True
            break

        frame = payload[index : index + total_length]
        if _crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
            index += 1
            crc16_fail += 1
            continue

        cmd_id = int.from_bytes(frame[5:7], "little")
        frames[cmd_id] = frame[7:-2]
        cmd_ids.append(cmd_id)
        index += total_length

    if diag is not None:
        diag["payload_len"] = len(payload)
        diag["a5_count"] = payload.count(0xA5)
        diag["skipped_bytes"] = skipped_bytes
        diag["crc8_fail"] = crc8_fail
        diag["crc16_fail"] = crc16_fail
        diag["frame_count"] = len(frames)
        diag["cmd_ids"] = cmd_ids
        diag["candidate_headers"] = candidate_headers

    return frames


def _parse_opponent_snapshot(payload: bytes, *, diag: dict[str, object] | None = None) -> OpponentSnapshot:
    frames = _decode_rm_frames(payload, diag=diag)
    bullet_frame = frames.get(0x0A03, b"")
    gold_frame = frames.get(0x0A04, b"")

    if diag is not None:
        diag["bullet_frame_len"] = len(bullet_frame)
        diag["gold_frame_len"] = len(gold_frame)
        diag["bullet_frame_preview"] = _hex_preview(bullet_frame)
        diag["gold_frame_preview"] = _hex_preview(gold_frame)

    robot_bullets = [
        _u16_optional(bullet_frame, 0),
        _u16_optional(bullet_frame, 2),
        _u16_optional(bullet_frame, 4),
        _u16_optional(bullet_frame, 6),
        _u16_optional(bullet_frame, 8),
    ]
    return OpponentSnapshot(robot_bullets=robot_bullets, remaining_gold=_u16_optional(gold_frame, 0))


def _status_tile_values(health: list[int]) -> list[tuple[int | None, int | None]]:
    return [
        (health[0], None),
        (health[1], None),
        (health[2], None),
        (health[3], None),
        (None, None),
        (health[4], None),
    ]


class RobotTile:
    def __init__(self, parent: tk.Widget, label: str, fill: str, panel_bg: str, border: str) -> None:
        self.frame = tk.Frame(
            parent,
            bg=panel_bg,
            highlightthickness=1,
            highlightbackground=border,
            highlightcolor=border,
            bd=0,
        )
        self.frame.columnconfigure(0, weight=1)

        self.label = tk.Label(
            self.frame,
            text=label,
            bg=panel_bg,
            fg="#1f2937",
            font=_ui_font(11, True),
        )
        self.label.grid(row=0, column=0, sticky="ew", padx=10, pady=(12, 0))

        self.health_text = tk.Label(
            self.frame,
            text="0",
            bg=panel_bg,
            fg=fill,
            font=_ui_font(28, True),
            width=5,
            anchor="center",
        )
        self.health_text.grid(row=1, column=0, sticky="ew", padx=10, pady=(6, 0))

        self.extra_text = tk.Label(
            self.frame,
            text="-",
            bg=panel_bg,
            fg="#6b7280",
            font=_ui_font(13, True),
            width=5,
            anchor="center",
        )
        self.extra_text.grid(row=2, column=0, sticky="nsew", padx=0, pady=(4, 12))

    def grid(self, **kwargs):
        self.frame.grid(**kwargs)

    def set_value(self, health: int | None, bullets: int | None = None) -> None:
        self.health_text.config(text="- -" if health is None else str(max(0, int(health))))
        if bullets is None:
            self.extra_text.config(text="-")
        else:
            self.extra_text.config(text=str(max(0, int(bullets))), fg="#9ca3af")


class DualMetricCard:
    def __init__(self, parent: tk.Widget, left_title: str, right_title: str, left_fill: str, right_fill: str, panel_bg: str):
        self.frame = tk.Frame(parent, bg=panel_bg)
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=1)

        self.left_label = tk.Label(
            self.frame,
            text=left_title,
            bg=panel_bg,
            fg="#111827",
            font=_ui_font(13, True),
            anchor="center",
            justify="center",
        )
        self.left_label.grid(row=0, column=0, sticky="nsew", padx=0, pady=(14, 2))

        self.right_label = tk.Label(
            self.frame,
            text=right_title,
            bg=panel_bg,
            fg="#111827",
            font=_ui_font(13, True),
            anchor="center",
            justify="center",
        )
        self.right_label.grid(row=0, column=1, sticky="nsew", padx=0, pady=(14, 2))

        self.left_value = tk.Label(
            self.frame,
            text="0",
            bg=panel_bg,
            fg=left_fill,
            font=_ui_font(40, True),
            anchor="center",
        )
        self.left_value.grid(row=1, column=0, sticky="nsew", padx=0, pady=(0, 14))

        self.right_value = tk.Label(
            self.frame,
            text="0",
            bg=panel_bg,
            fg=right_fill,
            font=_ui_font(40, True),
            anchor="center",
        )
        self.right_value.grid(row=1, column=1, sticky="nsew", padx=0, pady=(0, 14))

    def grid(self, **kwargs):
        self.frame.grid(**kwargs)

    def update(self, left_value: int, right_value: int) -> None:
        self.left_value.config(text=str(max(0, int(left_value))))
        self.right_value.config(text=str(max(0, int(right_value))))


class SingleMetricCard:
    def __init__(self, parent: tk.Widget, title: str, value_fill: str, panel_bg: str):
        self.frame = tk.Frame(parent, bg=panel_bg, highlightthickness=1, highlightbackground="#d7dbe3")
        self.frame.columnconfigure(0, weight=1)
        self.label = tk.Label(
            self.frame,
            text=title,
            bg=panel_bg,
            fg="#111827",
            font=_ui_font(13, True),
            anchor="center",
        )
        self.label.grid(row=0, column=0, sticky="nsew", padx=0, pady=(14, 2))
        self.value = tk.Label(
            self.frame,
            text="0",
            bg=panel_bg,
            fg=value_fill,
            font=_ui_font(38, True),
            anchor="center",
        )
        self.value.grid(row=1, column=0, sticky="nsew", padx=0, pady=(0, 14))

    def grid(self, **kwargs):
        self.frame.grid(**kwargs)

    def update(self, value: int | None) -> None:
        self.value.config(text="-" if value is None else str(max(0, int(value))))


class CustomClientApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.geometry("1280x900")
        self.root.minsize(1120, 760)
        _select_font_family(self.root)

        self.client_id: int | None = None
        self.team: str | None = None
        self.theme = TEAM_STYLES["red"]
        self.mqtt_client: mqtt.Client | None = None
        self.closing = False
        self.connected = False

        self.incoming: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.latest_status: StatusSnapshot | None = None
        self.latest_opponent: OpponentSnapshot | None = None

        self.ally_tiles: list[RobotTile] = []
        self.enemy_tiles: list[RobotTile] = []

        self.root.configure(bg=self.theme["page_bg"])
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_views()
        self._show_selection()
        self.root.after(100, self._poll_messages)

    def _build_views(self) -> None:
        self.selection_frame = tk.Frame(self.root, bg="#f9fafb")
        self.selection_frame.pack_propagate(False)

        self.selection_banner = tk.Frame(self.selection_frame, bg="#1f2937", height=96)
        self.selection_banner.pack(fill="x", side="top")
        self.selection_banner.pack_propagate(False)
        tk.Label(
            self.selection_banner,
            text="选择队伍和编号",
            bg="#1f2937",
            fg="#ffffff",
            font=_ui_font(24, True),
        ).pack(anchor="w", padx=32, pady=(22, 2))
        tk.Label(
            self.selection_banner,
            text="连接后会自动订阅 GlobalUnitStatus 和 CustomByteBlock。",
            bg="#1f2937",
            fg="#cbd5e1",
            font=_ui_font(11),
        ).pack(anchor="w", padx=34)

        self.selection_body = tk.Frame(self.selection_frame, bg="#f9fafb")
        self.selection_body.pack(fill="both", expand=True)
        self.selection_body.columnconfigure(0, weight=1)
        self.selection_body.rowconfigure(0, weight=1)

        grid = tk.Frame(self.selection_body, bg="#f9fafb")
        grid.grid(row=0, column=0, sticky="nsew", padx=32, pady=36)
        for column in range(5):
            grid.columnconfigure(column, weight=1)

        tk.Label(grid, text="红方", bg="#f9fafb", fg="#b91c1c", font=_ui_font(15, True)).grid(
            row=0, column=0, columnspan=5, sticky="w", pady=(0, 12)
        )
        self.selection_buttons: list[tk.Button] = []
        for idx, client_id in enumerate(RED_IDS):
            self.selection_buttons.append(
                self._make_selection_button(
                    grid,
                    row=1,
                    column=idx,
                    text=f"红方 {ALLY_LABELS[idx]}",
                    client_id=client_id,
                    bg="#ffe3e3",
                    activebg="#ffcbcb",
                    fg="#8b1d1d",
                )
            )

        tk.Label(grid, text="蓝方", bg="#f9fafb", fg="#1d4ed8", font=_ui_font(15, True)).grid(
            row=2, column=0, columnspan=5, sticky="w", pady=(24, 12)
        )
        for idx, client_id in enumerate(BLUE_IDS):
            self.selection_buttons.append(
                self._make_selection_button(
                    grid,
                    row=3,
                    column=idx,
                    text=f"蓝方 {ALLY_LABELS[idx]}",
                    client_id=client_id,
                    bg="#dbeafe",
                    activebg="#bfdbfe",
                    fg="#1e3a8a",
                )
            )

        self.selection_status = tk.Label(
            self.selection_body,
            text="",
            bg="#f9fafb",
            fg="#374151",
            font=_ui_font(11),
        )
        self.selection_status.grid(row=1, column=0, sticky="w", padx=34, pady=(0, 18))

        self.status_frame = tk.Frame(self.root, bg=self.theme["page_bg"])
        self.status_frame.pack_propagate(False)

        self.status_banner = tk.Frame(self.status_frame, bg=self.theme["accent"], height=104)
        self.status_banner.pack(fill="x", side="top")
        self.status_banner.pack_propagate(False)

        self.title_label = tk.Label(
            self.status_banner,
            text="自定义客户端",
            bg=self.theme["accent"],
            fg=self.theme["title_fg"],
            font=_ui_font(24, True),
        )
        self.title_label.pack(anchor="w", padx=30, pady=(18, 0))
        self.connection_label = tk.Label(
            self.status_banner,
            text="等待连接",
            bg=self.theme["accent"],
            fg="#ffffff",
            font=_ui_font(11),
        )
        self.connection_label.pack(anchor="w", padx=32, pady=(6, 0))

        self.status_body = tk.Frame(self.status_frame, bg=self.theme["page_bg"])
        self.status_body.pack(fill="both", expand=True)

        main = tk.Frame(self.status_body, bg=self.theme["page_bg"], width=1120)
        main.pack(anchor="n", pady=24)
        main.pack_propagate(False)
        main.columnconfigure(0, weight=1)

        damage_card = tk.Frame(main, bg=self.theme["panel_bg"], highlightthickness=1, highlightbackground=self.theme["panel_border"])
        damage_card.grid(row=0, column=0, sticky="ew")
        damage_card.columnconfigure(0, weight=1)
        self.damage_card = DualMetricCard(
            damage_card,
            left_title="己方伤害",
            right_title="对方伤害",
            left_fill=self.theme["ally_fill"],
            right_fill=self.theme["enemy_fill"],
            panel_bg=self.theme["panel_bg"],
        )
        self.damage_card.grid(row=0, column=0, sticky="ew", padx=8, pady=8)

        money_card = tk.Frame(main, bg=self.theme["panel_bg"], highlightthickness=1, highlightbackground=self.theme["panel_border"])
        money_card.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        money_card.columnconfigure(0, weight=1)
        self.money_card = SingleMetricCard(money_card, title="对方金币", value_fill="#0f766e", panel_bg=self.theme["panel_bg"])
        self.money_card.grid(row=0, column=0, sticky="ew", padx=8, pady=8)

        health_card = tk.Frame(main, bg=self.theme["panel_bg"], highlightthickness=1, highlightbackground=self.theme["panel_border"])
        health_card.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        health_card.columnconfigure(0, weight=1)

        tk.Label(
            health_card,
            text="血量/发弹量",
            bg=self.theme["panel_bg"],
            fg="#111827",
            font=_ui_font(13, True),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))

        ally_row = tk.Frame(health_card, bg=self.theme["panel_bg"])
        ally_row.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        ally_row.columnconfigure(0, weight=0)
        for column in range(6):
            ally_row.columnconfigure(column + 1, weight=1)
        tk.Label(
            ally_row,
            text="己方",
            bg=self.theme["panel_bg"],
            fg="#111827",
            font=_ui_font(11, True),
            width=5,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(8, 6))

        self.ally_tiles = []
        for idx, label in enumerate(ALLY_STATUS_LABELS):
            tile = RobotTile(ally_row, label, self.theme["ally_fill"], self.theme["panel_bg"], self.theme["panel_border"])
            tile.grid(row=0, column=idx + 1, sticky="nsew", padx=6)
            self.ally_tiles.append(tile)

        enemy_row = tk.Frame(health_card, bg=self.theme["panel_bg"])
        enemy_row.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 12))
        enemy_row.columnconfigure(0, weight=0)
        for column in range(6):
            enemy_row.columnconfigure(column + 1, weight=1)
        tk.Label(
            enemy_row,
            text="对方",
            bg=self.theme["panel_bg"],
            fg="#111827",
            font=_ui_font(11, True),
            width=5,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(8, 6))

        self.enemy_tiles = []
        for idx, label in enumerate(ENEMY_LABELS):
            tile = RobotTile(enemy_row, label, self.theme["enemy_fill"], self.theme["panel_bg"], self.theme["panel_border"])
            tile.grid(row=0, column=idx + 1, sticky="nsew", padx=6)
            self.enemy_tiles.append(tile)

        self.page_footer = tk.Label(main, text="", bg=self.theme["page_bg"], fg="#6b7280", font=_ui_font(10))
        self.page_footer.grid(row=3, column=0, sticky="ew", pady=(12, 0))

    def _make_selection_button(
        self,
        parent: tk.Widget,
        *,
        row: int,
        column: int,
        text: str,
        client_id: int,
        bg: str,
        activebg: str,
        fg: str,
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=lambda cid=client_id: self._start_connection(cid),
            bg=bg,
            activebackground=activebg,
            activeforeground=fg,
            fg=fg,
            font=_ui_font(13, True),
            relief="flat",
            bd=0,
            padx=10,
            pady=16,
            cursor="hand2",
        )
        button.grid(row=row, column=column, sticky="ew", padx=8, pady=8, ipady=8)
        parent.columnconfigure(column, weight=1)
        return button

    def _show_selection(self) -> None:
        self.status_frame.pack_forget()
        self.selection_frame.pack(fill="both", expand=True)
        self.selection_status.config(text="请选择红方或蓝方编号，然后连接 MQTT 服务器。")

    def _show_status(self) -> None:
        self.selection_frame.pack_forget()
        self.status_frame.pack(fill="both", expand=True)

    def _start_connection(self, client_id: int) -> None:
        if self.connected or self.mqtt_client is not None:
            return

        self.client_id = int(client_id)
        self.team = _team_from_client_id(self.client_id)
        self.theme = TEAM_STYLES[self.team]
        self.root.configure(bg=self.theme["page_bg"])
        self.selection_status.config(text=f"正在连接 {BROKER_HOST}:{BROKER_PORT} / client_id={self.client_id}")
        for button in self.selection_buttons:
            button.config(state="disabled")

        self._show_status()
        self._apply_theme()

        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _apply_theme(self) -> None:
        if self.team is None:
            return

        self.status_frame.config(bg=self.theme["page_bg"])
        self.status_body.config(bg=self.theme["page_bg"])
        self.page_footer.config(bg=self.theme["page_bg"])
        self.title_label.config(text=f"{'红方' if self.team == 'red' else '蓝方'} 自定义客户端", bg=self.theme["accent"])
        self.connection_label.config(bg=self.theme["accent"])
        self.status_banner.config(bg=self.theme["accent"])
        self.selection_banner.config(bg=self.theme["accent_dark"])
        self.damage_card.left_value.config(fg=self.theme["ally_fill"])
        self.damage_card.right_value.config(fg=self.theme["enemy_fill"])
        self.money_card.value.config(fg="#0f766e")

        for tile in self.ally_tiles:
            tile.frame.config(bg=self.theme["panel_bg"], highlightbackground=self.theme["panel_border"], highlightcolor=self.theme["panel_border"])
            tile.label.config(bg=self.theme["panel_bg"])
            tile.health_text.config(bg=self.theme["panel_bg"])
            tile.extra_text.config(bg=self.theme["panel_bg"])
        for tile in self.enemy_tiles:
            tile.frame.config(bg=self.theme["panel_bg"], highlightbackground=self.theme["panel_border"], highlightcolor=self.theme["panel_border"])
            tile.label.config(bg=self.theme["panel_bg"])
            tile.health_text.config(bg=self.theme["panel_bg"])
            tile.extra_text.config(bg=self.theme["panel_bg"])

        self.page_footer.config(text=f"Server {BROKER_HOST}:{BROKER_PORT} | client_id {self.client_id or ''}")

    def _connect_worker(self) -> None:
        if self.client_id is None:
            return

        try:
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=str(self.client_id),
                protocol=mqtt.MQTTv311,
            )
            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message
            client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
            client.loop_start()
            self.mqtt_client = client
        except Exception as exc:
            message = str(exc)
            self.root.after(0, lambda message=message: self._connection_failed(message))

    def _connection_failed(self, message: str) -> None:
        self.connected = False
        self.connection_label.config(text=f"连接失败：{message}")
        self.selection_status.config(text=f"连接失败：{message}")
        self._cleanup_mqtt()
        for button in self.selection_buttons:
            button.config(state="normal")
        self._show_selection()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if self.closing:
            return

        if _safe_int(reason_code) != 0:
            self.root.after(0, lambda: self._connection_failed(f"MQTT 返回码 {reason_code}"))
            return

        client.subscribe(TOPIC_GLOBAL_UNIT_STATUS, qos=1)
        client.subscribe(TOPIC_CUSTOM_BYTE_BLOCK, qos=1)
        self.root.after(0, self._connected_ui)

    def _connected_ui(self) -> None:
        self.connected = True
        self.connection_label.config(
            text=(
                f"已连接 {BROKER_HOST}:{BROKER_PORT} | client_id={self.client_id} | "
                f"已订阅 {TOPIC_GLOBAL_UNIT_STATUS}, {TOPIC_CUSTOM_BYTE_BLOCK}"
            )
        )
        self.selection_status.config(text="")
        self.page_footer.config(text=f"client_id {self.client_id} | 主题 {TOPIC_GLOBAL_UNIT_STATUS}, {TOPIC_CUSTOM_BYTE_BLOCK}")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        if self.closing:
            return

        self.connected = False
        self.root.after(0, lambda: self.connection_label.config(text=f"连接已断开：{reason_code}"))

    def _on_message(self, client, userdata, msg) -> None:
        try:
            if msg.topic == TOPIC_GLOBAL_UNIT_STATUS:
                parsed = GlobalUnitStatus()
                parsed.ParseFromString(msg.payload)
                snapshot = StatusSnapshot(
                    robot_health=[int(v) for v in parsed.robot_health],
                    total_damage_ally=_safe_int(getattr(parsed, "total_damage_ally", 0)),
                    total_damage_enemy=_safe_int(getattr(parsed, "total_damage_enemy", 0)),
                )
                self.incoming.put(("status", snapshot))
                return

            if msg.topic == TOPIC_CUSTOM_BYTE_BLOCK:
                parsed = CustomByteBlock()
                parsed.ParseFromString(msg.payload)
                raw_data = bytes(getattr(parsed, "data", b""))
                diag: dict[str, object] = {}
                opponent = _parse_opponent_snapshot(raw_data, diag=diag)
                self.incoming.put(("opponent", opponent))
        except Exception:
            return

    def _poll_messages(self) -> None:
        latest_status: StatusSnapshot | None = None
        latest_opponent: OpponentSnapshot | None = None

        try:
            while True:
                kind, payload = self.incoming.get_nowait()
                if kind == "status":
                    latest_status = payload  # type: ignore[assignment]
                elif kind == "opponent":
                    latest_opponent = payload  # type: ignore[assignment]
        except queue.Empty:
            pass

        if latest_status is not None:
            self.latest_status = latest_status
            self._apply_status(latest_status)
        if latest_opponent is not None:
            self.latest_opponent = self._merge_opponent(latest_opponent)
            self._apply_opponent(self.latest_opponent)

        self.root.after(100, self._poll_messages)

    def _apply_status(self, snapshot: StatusSnapshot) -> None:
        health = list(snapshot.robot_health[:10])
        if len(health) < 10:
            health.extend([0] * (10 - len(health)))
        ally_values = _status_tile_values(health[:5])
        for tile, (value, bullets) in zip(self.ally_tiles, ally_values):
            tile.set_value(value, bullets)

        self.damage_card.update(snapshot.total_damage_ally, snapshot.total_damage_enemy)

        enemy_health = [health[5], health[6], health[7], health[8], None, health[9]]
        self._apply_enemy_health(enemy_health)

    def _merge_opponent(self, snapshot: OpponentSnapshot) -> OpponentSnapshot:
        previous = self.latest_opponent
        bullets = list(snapshot.robot_bullets[:5])
        if len(bullets) < 5:
            bullets.extend([None] * (5 - len(bullets)))

        if previous is not None:
            old_bullets = list(previous.robot_bullets[:5])
            if len(old_bullets) < 5:
                old_bullets.extend([None] * (5 - len(old_bullets)))
            bullets = [new if new is not None else old for new, old in zip(bullets, old_bullets)]

        gold = snapshot.remaining_gold
        if gold is None and previous is not None:
            gold = previous.remaining_gold

        return OpponentSnapshot(robot_bullets=bullets, remaining_gold=gold)

    def _apply_enemy_health(self, enemy_health: list[int | None]) -> None:
        bullets = self._enemy_bullet_values()
        for tile, value, bullet in zip(self.enemy_tiles, enemy_health, bullets):
            tile.set_value(value, bullet)

    def _enemy_bullet_values(self) -> list[int | None]:
        bullets: list[int | None]
        if self.latest_opponent is None:
            bullets = []
        else:
            bullets = list(self.latest_opponent.robot_bullets[:5])
        if len(bullets) < 5:
            bullets.extend([None] * (5 - len(bullets)))
        return [
            bullets[0],
            None,
            bullets[1],
            bullets[2],
            bullets[3],
            bullets[4],
        ]

    def _apply_opponent(self, snapshot: OpponentSnapshot) -> None:
        if self.latest_status is not None:
            health = list(self.latest_status.robot_health[:10])
            if len(health) < 10:
                health.extend([0] * (10 - len(health)))
            self._apply_enemy_health([health[5], health[6], health[7], health[8], None, health[9]])
        else:
            self._apply_enemy_health([None, None, None, None, None, None])
        self.money_card.update(snapshot.remaining_gold)

    def _cleanup_mqtt(self) -> None:
        client = self.mqtt_client
        self.mqtt_client = None
        if client is None:
            return
        try:
            client.loop_stop()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass

    def on_close(self) -> None:
        self.closing = True
        self._cleanup_mqtt()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    CustomClientApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
