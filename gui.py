"""Interfaz gráfica de escritorio para ver tu cámara, el gesto detectado y controlar el ESP32."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import cv2
from PIL import Image, ImageTk

from config import (
    CALIBRATION_PATH,
    COMMAND_LABELS,
    DEFAULT_HOST,
    DEFAULT_PORT,
    MIN_GESTURE_CONFIDENCE,
    CalibrationProfile,
)
from scripts.download_model import ensure_model_downloaded
from src.gesture_controller import GestureController
from src.socket_client import CarSocketClient

GESTURE_FRIENDLY_NAMES: dict[str, str] = {
    "Thumb_Up": "Pulgar arriba (Thumb_Up)",
    "Thumb_Down": "Pulgar abajo (Thumb_Down)",
    "Pointing_Up": "Indice arriba (Pointing_Up)",
    "Victory": "Victoria / 2 dedos (Victory)",
    "Closed_Fist": "Puno cerrado (Closed_Fist)",
    "Open_Palm": "Palma abierta (Open_Palm)",
    "ILoveYou": "ILoveYou (Cambiar modo)",
    "None": "Sin gesto claro",
}

COMMAND_VISUALS: dict[str, tuple[str, str]] = {
    "F": ("▲  ADELANTE", "#22c55e"),
    "B": ("▼  ATRAS", "#f59e0b"),
    "L": ("◀  IZQUIERDA", "#38bdf8"),
    "R": ("▶  DERECHA", "#a855f7"),
    "S": ("■  ALTO", "#64748b"),
}


class LawamyRacingGUI:
    def __init__(self, root: tk.Tk, camera_index: int = 0) -> None:
        self.root = root
        self.root.title("LawamyRacing — Control por Gestos con IA")
        self.root.configure(bg="#0f172a")
        self.root.resizable(False, False)

        self.camera_index = camera_index
        self.profile = CalibrationProfile.load(CALIBRATION_PATH)
        self.model_path = ensure_model_downloaded()
        self.controller = GestureController(model_path=self.model_path)
        self.client: CarSocketClient | None = None

        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            self.controller.close()
            raise RuntimeError(
                f"No se pudo abrir la webcam (índice {self.camera_index}). "
                "Cierra otras aplicaciones que usen la cámara e intenta de nuevo."
            )
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        self._photo_ref: ImageTk.PhotoImage | None = None
        self._running = True

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._update_frame()

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TProgressbar", troughcolor="#1e293b", background="#38bdf8", thickness=14)

        main_frame = tk.Frame(self.root, bg="#0f172a", padx=14, pady=14)
        main_frame.pack(fill="both", expand=True)

        # ---- COLUMNA IZQUIERDA: VIDEO EN VIVO ----
        left_col = tk.Frame(main_frame, bg="#0f172a")
        left_col.grid(row=0, column=0, sticky="n", padx=(0, 14))

        tk.Label(
            left_col,
            text="CÁMARA EN VIVO (Reconocimiento de Mano)",
            font=("Segoe UI", 11, "bold"),
            fg="#e2e8f0",
            bg="#0f172a",
        ).pack(anchor="w", pady=(0, 6))

        self.video_label = tk.Label(left_col, bg="#020617", width=640, height=480)
        self.video_label.pack()

        # Leyenda compacta bajo el video
        legend = (
            "Gestos:  👍 Pulgar arriba = Adelante  |  👎 Pulgar abajo = Atrás  |  "
            "☝️ Índice = Izq  |  ✌️ Victoria = Der  |  ✊/✋ = Alto  |  🤟 (1s) = Precisión"
        )
        tk.Label(
            left_col,
            text=legend,
            font=("Segoe UI", 9),
            fg="#cbd5e1",
            bg="#1e293b",
            padx=10,
            pady=8,
            wraplength=630,
            justify="left",
        ).pack(fill="x", pady=(8, 0))

        # ---- COLUMNA DERECHA: RETROALIMENTACIÓN + CONTROLES ----
        right_col = tk.Frame(main_frame, bg="#0f172a", width=330)
        right_col.grid(row=0, column=1, sticky="ns")

        # 1. Tarjeta de Comando Actual
        cmd_card = tk.Frame(right_col, bg="#1e293b", padx=14, pady=12)
        cmd_card.pack(fill="x", pady=(0, 10))

        tk.Label(
            cmd_card,
            text="GESTO RECONOCIDO",
            font=("Segoe UI", 9, "bold"),
            fg="#94a3b8",
            bg="#1e293b",
        ).pack(anchor="w")

        self.cmd_badge = tk.Label(
            cmd_card,
            text="■  ALTO",
            font=("Segoe UI", 22, "bold"),
            fg="#ffffff",
            bg="#64748b",
            pady=10,
        )
        self.cmd_badge.pack(fill="x", pady=(6, 8))

        self.gesture_label = tk.Label(
            cmd_card,
            text="Gesto: Sin gesto claro",
            font=("Segoe UI", 10, "bold"),
            fg="#f8fafc",
            bg="#1e293b",
            anchor="w",
        )
        self.gesture_label.pack(fill="x")

        conf_row = tk.Frame(cmd_card, bg="#1e293b")
        conf_row.pack(fill="x", pady=(6, 4))
        self.conf_text = tk.Label(
            conf_row,
            text="Confianza: 0%",
            font=("Segoe UI", 9),
            fg="#cbd5e1",
            bg="#1e293b",
        )
        self.conf_text.pack(side="left")
        self.mode_badge = tk.Label(
            conf_row,
            text="MODO: NORMAL",
            font=("Segoe UI", 9, "bold"),
            fg="#38bdf8",
            bg="#1e293b",
        )
        self.mode_badge.pack(side="right")

        self.conf_bar = ttk.Progressbar(cmd_card, orient="horizontal", length=280, mode="determinate", maximum=100)
        self.conf_bar.pack(fill="x", pady=(2, 6))

        self.pwm_label = tk.Label(
            cmd_card,
            text="PWM Motor Izq: 0   |   Der: 0",
            font=("Consolas", 10, "bold"),
            fg="#a7f3d0",
            bg="#0f172a",
            pady=5,
        )
        self.pwm_label.pack(fill="x", pady=(4, 0))

        # 2. Conexión WiFi ESP32
        net_card = tk.Frame(right_col, bg="#1e293b", padx=14, pady=10)
        net_card.pack(fill="x", pady=(0, 10))

        tk.Label(
            net_card,
            text="CONEXIÓN CARRITO (ESP32 WiFi)",
            font=("Segoe UI", 9, "bold"),
            fg="#94a3b8",
            bg="#1e293b",
        ).pack(anchor="w", pady=(0, 6))

        ip_row = tk.Frame(net_card, bg="#1e293b")
        ip_row.pack(fill="x")
        tk.Label(ip_row, text="IP:", fg="#cbd5e1", bg="#1e293b", font=("Segoe UI", 9)).pack(side="left")
        self.host_var = tk.StringVar(value=DEFAULT_HOST)
        tk.Entry(ip_row, textvariable=self.host_var, width=15, bg="#0f172a", fg="#f8fafc", insertbackground="#fff").pack(
            side="left", padx=(4, 8)
        )
        tk.Label(ip_row, text="Puerto:", fg="#cbd5e1", bg="#1e293b", font=("Segoe UI", 9)).pack(side="left")
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        tk.Entry(ip_row, textvariable=self.port_var, width=6, bg="#0f172a", fg="#f8fafc", insertbackground="#fff").pack(
            side="left", padx=(4, 0)
        )

        btn_row = tk.Frame(net_card, bg="#1e293b")
        btn_row.pack(fill="x", pady=(8, 4))
        self.connect_btn = tk.Button(
            btn_row,
            text="Conectar al ESP32",
            command=self._toggle_connection,
            bg="#2563eb",
            fg="#ffffff",
            activebackground="#1d4ed8",
            activeforeground="#ffffff",
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=5,
            cursor="hand2",
        )
        self.connect_btn.pack(side="left", fill="x", expand=True)

        self.conn_status = tk.Label(
            net_card,
            text="○ Solo prueba de gestos (sin ESP32)",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#1e293b",
            anchor="w",
        )
        self.conn_status.pack(fill="x", pady=(4, 0))

        # 3. Calibración rápida Pista Cuadrada
        cal_card = tk.Frame(right_col, bg="#1e293b", padx=14, pady=10)
        cal_card.pack(fill="x")

        tk.Label(
            cal_card,
            text="CALIBRACIÓN PISTA CUADRADA",
            font=("Segoe UI", 9, "bold"),
            fg="#94a3b8",
            bg="#1e293b",
        ).pack(anchor="w", pady=(0, 4))

        self.conf_threshold_var = tk.IntVar(value=int(MIN_GESTURE_CONFIDENCE * 100))
        self.drive_var = tk.IntVar(value=self.profile.forward_pwm)
        self.turn_var = tk.IntVar(value=self.profile.left_turn_pwm)
        self.trim_var = tk.IntVar(value=self.profile.trim_balance)

        self._add_slider(cal_card, "Confianza mínima (%)", self.conf_threshold_var, 35, 90, self._on_slider_change)
        self._add_slider(cal_card, "Velocidad Recta (PWM)", self.drive_var, 80, 255, self._on_slider_change)
        self._add_slider(cal_card, "Velocidad Giro 90° (PWM)", self.turn_var, 80, 255, self._on_slider_change)
        self._add_slider(cal_card, "Trim Izq (-) / Der (+)", self.trim_var, -60, 60, self._on_slider_change)

        tk.Button(
            cal_card,
            text="Guardar calibración (calibration.json)",
            command=self._save_calibration,
            bg="#059669",
            fg="#ffffff",
            activebackground="#047857",
            activeforeground="#ffffff",
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            pady=6,
            cursor="hand2",
        ).pack(fill="x", pady=(8, 0))

    def _add_slider(
        self,
        parent: tk.Frame,
        label: str,
        var: tk.IntVar,
        from_: int,
        to: int,
        command,
    ) -> None:
        row = tk.Frame(parent, bg="#1e293b")
        row.pack(fill="x", pady=(2, 0))
        tk.Label(row, text=label, font=("Segoe UI", 8), fg="#cbd5e1", bg="#1e293b").pack(side="left")
        val_lbl = tk.Label(row, textvariable=var, font=("Consolas", 9, "bold"), fg="#38bdf8", bg="#1e293b")
        val_lbl.pack(side="right")

        scale = tk.Scale(
            parent,
            from_=from_,
            to=to,
            orient="horizontal",
            variable=var,
            showvalue=False,
            bg="#1e293b",
            fg="#e2e8f0",
            troughcolor="#0f172a",
            highlightthickness=0,
            activebackground="#38bdf8",
            command=command,
        )
        scale.pack(fill="x")

    def _on_slider_change(self, _value: str | None = None) -> None:
        self.controller.filter.min_confidence = self.conf_threshold_var.get() / 100.0
        drive = self.drive_var.get()
        turn = self.turn_var.get()
        self.profile.forward_pwm = drive
        self.profile.backward_pwm = max(0, drive - 10)
        self.profile.left_turn_pwm = turn
        self.profile.right_turn_pwm = turn
        self.profile.trim_balance = self.trim_var.get()

    def _save_calibration(self) -> None:
        self._on_slider_change()
        self.profile.save(CALIBRATION_PATH)
        self.conn_status.config(text=f"✔ Calibración guardada en {CALIBRATION_PATH.name}", fg="#34d399")

    def _toggle_connection(self) -> None:
        if self.client is not None:
            self.client.stop()
            self.client = None
            self.connect_btn.config(text="Conectar al ESP32", bg="#2563eb")
            self.conn_status.config(text="○ Desconectado (solo prueba de gestos)", fg="#94a3b8")
            return

        host = self.host_var.get().strip() or DEFAULT_HOST
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            messagebox.showerror("Puerto inválido", "Ingresa un número de puerto válido (ej. 8888).")
            return

        self.client = CarSocketClient(host=host, port=port)
        self.client.start()
        self.connect_btn.config(text="Desconectar ESP32", bg="#dc2626")
        self.conn_status.config(text=f"◌ Conectando a {host}:{port}...", fg="#fbbf24")

    def _update_frame(self) -> None:
        if not self._running:
            return

        ok, frame = self.cap.read()
        if ok:
            frame = cv2.flip(frame, 1)
            state, landmarks = self.controller.process_frame(frame)
            pwm_left, pwm_right = self.profile.compute_pwms(state.command, state.precision_mode)

            if self.client is not None:
                self.client.set_command(state.command, pwm_left, pwm_right)
                if self.client.is_connected:
                    self.conn_status.config(
                        text=f"● CONECTADO a {self.client.host}:{self.client.port}", fg="#22c55e"
                    )
                else:
                    self.conn_status.config(
                        text=f"◌ Buscando ESP32 en {self.client.host}:{self.client.port}...", fg="#fbbf24"
                    )

            # Dibujar esqueleto de la mano sobre el video
            self.controller.draw_hand_landmarks(frame, landmarks)

            # Actualizar panel derecho
            cmd_text, cmd_color = COMMAND_VISUALS.get(state.command, ("■  ALTO", "#64748b"))
            self.cmd_badge.config(text=cmd_text, bg=cmd_color)

            friendly = GESTURE_FRIENDLY_NAMES.get(state.raw_gesture, state.raw_gesture)
            self.gesture_label.config(text=f"Gesto: {friendly}")

            conf_pct = int(state.confidence * 100)
            self.conf_text.config(text=f"Confianza: {conf_pct}%")
            self.conf_bar["value"] = conf_pct

            mode_label = "MODO: PRECISIÓN" if state.precision_mode else "MODO: NORMAL"
            mode_fg = "#fbbf24" if state.precision_mode else "#38bdf8"
            self.mode_badge.config(text=mode_label, fg=mode_fg)
            self.pwm_label.config(text=f"PWM Motor Izq: {pwm_left:3d}   |   Der: {pwm_right:3d}")

            # Convertir frame OpenCV -> Tkinter
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb).resize((640, 480))
            self._photo_ref = ImageTk.PhotoImage(image=img)
            self.video_label.configure(image=self._photo_ref)

        self.root.after(20, self._update_frame)

    def _on_close(self) -> None:
        self._running = False
        if self.cap.isOpened():
            self.cap.release()
        self.controller.close()
        if self.client is not None:
            self.client.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        LawamyRacingGUI(root)
    except Exception as exc:
        messagebox.showerror("Error al iniciar LawamyRacing", str(exc))
        root.destroy()
        raise
    root.mainloop()


if __name__ == "__main__":
    main()
