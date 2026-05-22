from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import dataclass

import paho.mqtt.client as mqtt

from rm_custom_proto import GlobalUnitStatus


BROKER_HOST = "192.168.12.1"
BROKER_PORT = 3333
TOPIC_GLOBAL_UNIT_STATUS = "GlobalUnitStatus"
WINDOW_TITLE = "RoboMaster 2026 Custom Client"

RED_IDS = [1, 2, 3, 4, 6]
BLUE_IDS = [101, 102, 103, 104, 106]

ALLY_LABELS = ["No. 1", "No. 2", "No. 3", "No. 4", "No. 7"]
ENEMY_LABELS = ["No. 1", "No. 2", "No. 3", "No. 4", "No. 7"]
ROBOT_LABELS = [f"Ally {label}" for label in ALLY_LABELS] + [f"Enemy {label}" for label in ENEMY_LABELS]

TEAM_STYLES = {
    "red": {
        "accent": "#d32f2f",
        "accent_dark": "#9f1d1d",
        "accent_light": "#ffecec",
        "page_bg": "#fff8f8",
        "panel_bg": "#ffffff",
        "panel_border": "#efb0b0",
        "ally_fill": "#d32f2f",
        "enemy_fill": "#2d6cdf",
        "muted_fill": "#c9c9c9",
        "title_fg": "#ffffff",
    },
    "blue": {
        "accent": "#2563eb",
        "accent_dark": "#1847a8",
        "accent_light": "#eef4ff",
        "page_bg": "#f8fbff",
        "panel_bg": "#ffffff",
        "panel_border": "#adc4ef",
        "ally_fill": "#2563eb",
        "enemy_fill": "#d32f2f",
        "muted_fill": "#c9c9c9",
        "title_fg": "#ffffff",
    },
}


def _team_from_client_id(client_id: int) -> str:
    return "red" if client_id < 100 else "blue"


def _safe_int(value) -> int:
    try:
        return int(value)
    except Exception:
        return 0


@dataclass
class StatusSnapshot:
    robot_health: list[int]
    total_damage_ally: int
    total_damage_enemy: int


class RobotTile:
    def __init__(self, parent: tk.Widget, label: str, team_fill: str, panel_bg: str, border: str) -> None:
        self.frame = tk.Frame(
            parent,
            bg=panel_bg,
            highlightthickness=1,
            highlightbackground=border,
            highlightcolor=border,
            bd=0,
        )
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        self.frame.rowconfigure(2, weight=1)

        self.label = tk.Label(
            self.frame,
            text=label,
            bg=panel_bg,
            fg="#1f2937",
            font=("Microsoft YaHei UI", 12, "bold"),
        )
        self.label.grid(row=0, column=0, sticky="n", padx=10, pady=(12, 0))

        self.health_text = tk.Label(
            self.frame,
            text="0",
            bg=panel_bg,
            fg=team_fill,
            font=("Consolas", 30, "bold"),
        )
        self.health_text.grid(row=1, column=0, sticky="n", padx=10, pady=(6, 0))

    def grid(self, **kwargs):
        self.frame.grid(**kwargs)

    def update(self, value: int) -> None:
        self.value = max(0, int(value))
        self.health_text.config(text=str(self.value))


class DamageStats:
    def __init__(self, parent: tk.Widget, ally_fill: str, enemy_fill: str, panel_bg: str) -> None:
        self.frame = tk.Frame(parent, bg=panel_bg)
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=1)

        self.ally_label = tk.Label(
            self.frame,
            text="Ally Total Damage",
            bg=panel_bg,
            fg="#111827",
            font=("Microsoft YaHei UI", 13, "bold"),
        )
        self.ally_label.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 2))

        self.enemy_label = tk.Label(
            self.frame,
            text="Enemy Total Damage",
            bg=panel_bg,
            fg="#111827",
            font=("Microsoft YaHei UI", 13, "bold"),
        )
        self.enemy_label.grid(row=0, column=1, sticky="ew", padx=16, pady=(14, 2))

        self.ally_value = tk.Label(
            self.frame,
            text="0",
            bg=panel_bg,
            fg=ally_fill,
            font=("Consolas", 40, "bold"),
        )
        self.ally_value.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))

        self.enemy_value = tk.Label(
            self.frame,
            text="0",
            bg=panel_bg,
            fg=enemy_fill,
            font=("Consolas", 40, "bold"),
        )
        self.enemy_value.grid(row=1, column=1, sticky="ew", padx=16, pady=(0, 14))

    def grid(self, **kwargs):
        self.frame.grid(**kwargs)

    def update(self, ally_damage: int, enemy_damage: int) -> None:
        self.ally_value.config(text=str(max(0, int(ally_damage))))
        self.enemy_value.config(text=str(max(0, int(enemy_damage))))


class CustomClientApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.geometry("1280x900")
        self.root.minsize(1120, 760)

        self.client_id: int | None = None
        self.team: str | None = None
        self.theme = TEAM_STYLES["red"]
        self.mqtt_client: mqtt.Client | None = None
        self.closing = False
        self.connected = False
        self.incoming: "queue.Queue[StatusSnapshot]" = queue.Queue()
        self.tiles: list[RobotTile] = []
        self.robot_health = [0] * 10
        self.total_damage_ally = 0
        self.total_damage_enemy = 0

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
            text="Select Team and ID",
            bg="#1f2937",
            fg="#ffffff",
            font=("Microsoft YaHei UI", 24, "bold"),
        ).pack(anchor="w", padx=32, pady=(22, 2))
        tk.Label(
            self.selection_banner,
            text="After connecting, the app will subscribe to GlobalUnitStatus automatically.",
            bg="#1f2937",
            fg="#cbd5e1",
            font=("Microsoft YaHei UI", 11),
        ).pack(anchor="w", padx=34)

        self.selection_body = tk.Frame(self.selection_frame, bg="#f9fafb")
        self.selection_body.pack(fill="both", expand=True)
        self.selection_body.columnconfigure(0, weight=1)
        self.selection_body.rowconfigure(0, weight=1)

        grid = tk.Frame(self.selection_body, bg="#f9fafb")
        grid.grid(row=0, column=0, sticky="nsew", padx=32, pady=36)
        for column in range(5):
            grid.columnconfigure(column, weight=1)

        tk.Label(grid, text="Red Team", bg="#f9fafb", fg="#b91c1c", font=("Microsoft YaHei UI", 15, "bold")).grid(
            row=0, column=0, columnspan=5, sticky="w", pady=(0, 12)
        )
        self.selection_buttons: list[tk.Button] = []
        for idx, client_id in enumerate(RED_IDS):
            btn = self._make_selection_button(
                grid,
                row=1,
                column=idx,
                text=f"Red {ALLY_LABELS[idx]}",
                client_id=client_id,
                bg="#ffe3e3",
                activebg="#ffcbcb",
                fg="#8b1d1d",
            )
            self.selection_buttons.append(btn)

        tk.Label(grid, text="Blue Team", bg="#f9fafb", fg="#1d4ed8", font=("Microsoft YaHei UI", 15, "bold")).grid(
            row=2, column=0, columnspan=5, sticky="w", pady=(24, 12)
        )
        for idx, client_id in enumerate(BLUE_IDS):
            btn = self._make_selection_button(
                grid,
                row=3,
                column=idx,
                text=f"Blue {ALLY_LABELS[idx]}",
                client_id=client_id,
                bg="#dbeafe",
                activebg="#bfdbfe",
                fg="#1e3a8a",
            )
            self.selection_buttons.append(btn)

        self.selection_status = tk.Label(
            self.selection_body,
            text="",
            bg="#f9fafb",
            fg="#374151",
            font=("Microsoft YaHei UI", 11),
        )
        self.selection_status.grid(row=1, column=0, sticky="w", padx=34, pady=(0, 18))

        self.status_frame = tk.Frame(self.root, bg=self.theme["page_bg"])
        self.status_frame.pack_propagate(False)

        self.status_banner = tk.Frame(self.status_frame, bg=self.theme["accent"], height=104)
        self.status_banner.pack(fill="x", side="top")
        self.status_banner.pack_propagate(False)

        self.title_label = tk.Label(
            self.status_banner,
            text="Custom Client",
            bg=self.theme["accent"],
            fg=self.theme["title_fg"],
            font=("Microsoft YaHei UI", 24, "bold"),
        )
        self.title_label.pack(anchor="w", padx=30, pady=(18, 0))
        self.connection_label = tk.Label(
            self.status_banner,
            text="Waiting for connection",
            bg=self.theme["accent"],
            fg="#ffffff",
            font=("Microsoft YaHei UI", 11),
        )
        self.connection_label.pack(anchor="w", padx=32, pady=(6, 0))

        self.status_body = tk.Frame(self.status_frame, bg=self.theme["page_bg"])
        self.status_body.pack(fill="both", expand=True)

        main = tk.Frame(self.status_body, bg=self.theme["page_bg"], width=1120)
        main.pack(anchor="n", pady=24)
        main.pack_propagate(False)
        main.columnconfigure(0, weight=1)

        damage_card = tk.Frame(
            main,
            bg=self.theme["panel_bg"],
            highlightthickness=1,
            highlightbackground=self.theme["panel_border"],
        )
        damage_card.grid(row=0, column=0, sticky="ew")
        damage_card.columnconfigure(0, weight=1)
        tk.Label(
            damage_card,
            text="Total Damage Duel",
            bg=self.theme["panel_bg"],
            fg="#111827",
            font=("Microsoft YaHei UI", 13, "bold"),
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 0))
        self.damage_bar = DamageStats(
            damage_card,
            ally_fill=self.theme["ally_fill"],
            enemy_fill=self.theme["enemy_fill"],
            panel_bg=self.theme["panel_bg"],
        )
        self.damage_bar.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 8))

        health_card = tk.Frame(
            main,
            bg=self.theme["panel_bg"],
            highlightthickness=1,
            highlightbackground=self.theme["panel_border"],
        )
        health_card.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        for column in range(5):
            health_card.columnconfigure(column, weight=1)

        tk.Label(
            health_card,
            text="Robot Health",
            bg=self.theme["panel_bg"],
            fg="#111827",
            font=("Microsoft YaHei UI", 13, "bold"),
        ).grid(row=0, column=0, columnspan=5, sticky="ew", padx=16, pady=(14, 8))

        self.tiles = []
        for index, label in enumerate(ROBOT_LABELS):
            row = 1 if index < 5 else 2
            column = index % 5
            is_ally = index < 5
            tile = RobotTile(
                health_card,
                label,
                self.theme["ally_fill"] if is_ally else self.theme["enemy_fill"],
                self.theme["panel_bg"],
                self.theme["panel_border"],
            )
            tile.grid(row=row, column=column, sticky="nsew", padx=8, pady=(0 if row == 1 else 8, 12))
            self.tiles.append(tile)

        for column in range(5):
            health_card.columnconfigure(column, weight=1)

        self.page_footer = tk.Label(
            main,
            text="",
            bg=self.theme["page_bg"],
            fg="#6b7280",
            font=("Microsoft YaHei UI", 10),
        )
        self.page_footer.grid(row=2, column=0, sticky="ew", pady=(12, 0))

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
            font=("Microsoft YaHei UI", 13, "bold"),
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
        self.selection_status.config(text="Please choose a red or blue ID, then connect to the MQTT server.")

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
        self.selection_status.config(text=f"Connecting to {BROKER_HOST}:{BROKER_PORT} / client_id={self.client_id}")
        for button in self.selection_buttons:
            button.config(state="disabled")

        self._show_status()
        self._apply_theme()

        worker = threading.Thread(target=self._connect_worker, daemon=True)
        worker.start()

    def _apply_theme(self) -> None:
        if self.team is None:
            return

        self.status_frame.config(bg=self.theme["page_bg"])
        self.status_body.config(bg=self.theme["page_bg"])
        self.page_footer.config(bg=self.theme["page_bg"])
        self.title_label.config(text=f"{'Red' if self.team == 'red' else 'Blue'} Custom Client", bg=self.theme["accent"])
        self.connection_label.config(bg=self.theme["accent"])
        self.status_banner.config(bg=self.theme["accent"])
        self.selection_banner.config(bg=self.theme["accent_dark"])
        self.damage_bar.ally_value.config(fg=self.theme["ally_fill"])
        self.damage_bar.enemy_value.config(fg=self.theme["enemy_fill"])
        for tile, is_ally in zip(self.tiles, [True] * 5 + [False] * 5):
            tile.frame.config(highlightbackground=self.theme["panel_border"], highlightcolor=self.theme["panel_border"])
            tile.frame.config(bg=self.theme["panel_bg"])
            tile.label.config(bg=self.theme["panel_bg"])
            tile.health_text.config(bg=self.theme["panel_bg"])
            tile.health_text.config(fg=self.theme["ally_fill"] if is_ally else self.theme["enemy_fill"])
        self.page_footer.config(
            text=f"Server {BROKER_HOST}:{BROKER_PORT} | client_id {self.client_id if self.client_id is not None else ''}"
        )

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
            self.root.after(0, lambda: self._connection_failed(str(exc)))

    def _connection_failed(self, message: str) -> None:
        self.connected = False
        self.connection_label.config(text=f"Connection failed: {message}")
        self.selection_status.config(text=f"Connection failed: {message}")
        self._cleanup_mqtt()
        for button in self.selection_buttons:
            button.config(state="normal")
        self._show_selection()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if self.closing:
            return

        ok = _safe_int(reason_code) == 0
        if not ok:
            self.root.after(0, lambda: self._connection_failed(f"MQTT return code {reason_code}"))
            return

        client.subscribe(TOPIC_GLOBAL_UNIT_STATUS, qos=1)
        self.root.after(0, self._connected_ui)

    def _connected_ui(self) -> None:
        self.connected = True
        self.connection_label.config(
            text=f"Connected to {BROKER_HOST}:{BROKER_PORT} | client_id={self.client_id} | subscribed to {TOPIC_GLOBAL_UNIT_STATUS}"
        )
        self.selection_status.config(text="")
        self.page_footer.config(text=f"client_id {self.client_id} | topic {TOPIC_GLOBAL_UNIT_STATUS}")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        if self.closing:
            return

        self.connected = False
        text = f"Connection closed: {reason_code}"
        self.root.after(0, lambda: self.connection_label.config(text=text))

    def _on_message(self, client, userdata, msg) -> None:
        if msg.topic != TOPIC_GLOBAL_UNIT_STATUS:
            return

        try:
            parsed = GlobalUnitStatus()
            parsed.ParseFromString(msg.payload)
            health = [int(v) for v in parsed.robot_health]
            snapshot = StatusSnapshot(
                robot_health=health,
                total_damage_ally=_safe_int(getattr(parsed, "total_damage_ally", 0)),
                total_damage_enemy=_safe_int(getattr(parsed, "total_damage_enemy", 0)),
            )
            self.incoming.put(snapshot)
        except Exception:
            return

    def _poll_messages(self) -> None:
        latest: StatusSnapshot | None = None
        try:
            while True:
                latest = self.incoming.get_nowait()
        except queue.Empty:
            pass

        if latest is not None:
            self._apply_snapshot(latest)

        self.root.after(100, self._poll_messages)

    def _apply_snapshot(self, snapshot: StatusSnapshot) -> None:
        values = list(snapshot.robot_health[:10])
        if len(values) < 10:
            values.extend([0] * (10 - len(values)))
        self.robot_health = values
        self.total_damage_ally = snapshot.total_damage_ally
        self.total_damage_enemy = snapshot.total_damage_enemy

        for tile, value in zip(self.tiles, self.robot_health):
            tile.update(value)
        self.damage_bar.update(self.total_damage_ally, self.total_damage_enemy)

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
    app = CustomClientApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
