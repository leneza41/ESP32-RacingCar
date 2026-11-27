# LawamyRacing — Carrito Controlado por Gestos con IA (Python + ESP32 + L298N)

Proyecto Final para controlar un carrito robótico de 2 motorreductores usando reconocimiento de gestos de mano en tiempo real con **Google MediaPipe**, comunicación **WiFi por Sockets TCP** y un **ESP32 DevKit + Puente H L298N**.

---

## 1. Gestos con las Manos

| Gesto | Categoría MediaPipe | Acción en el Carrito |
| :--- | :--- | :--- |
| 👍 Pulgar arriba | `Thumb_Up` | **Adelante** |
| 👎 Pulgar abajo | `Thumb_Down` | **Atrás** |
| ☝️ Índice arriba | `Pointing_Up` | **Izquierda** (giro diferencial) |
| ✌️ Victoria (2 dedos) | `Victory` | **Derecha** (giro diferencial) |
| ✊ Puño cerrado / ✋ Palma / Sin mano | `Closed_Fist` / `Open_Palm` / `None` | **Alto inmediato** |
| 🤟 Gesto Amor/Rock (mantener 1 s) | `ILoveYou` | **Alternar Modo Normal ↔ Precisión (Pista Cuadrada)** |

---

## 2. Conexiones Hardware (ESP32 DevKit + L298N)

> **Importante:** Retira los dos jumpers plásticos de `ENA` y `ENB` en el L298N y conecta un cable uniendo el **`GND` del ESP32** con el **`GND` del L298N**.

| Pin L298N | Pin ESP32 DevKit | Función |
| :--- | :--- | :--- |
| `ENA` | `GPIO 25` | PWM Velocidad Motor Izquierdo |
| `IN1` | `GPIO 26` | Dirección Motor Izquierdo |
| `IN2` | `GPIO 27` | Dirección Motor Izquierdo |
| `IN3` | `GPIO 32` | Dirección Motor Derecho |
| `IN4` | `GPIO 33` | Dirección Motor Derecho |
| `ENB` | `GPIO 14` | PWM Velocidad Motor Derecho |
| `GND` | `GND` + `(-)` Batería | Tierra común obligatoria |
| `+12V / VMS` | `(+)` Batería (6V–9V) | Alimentación de motores |

---

## 3. Instalación y Ejecución en PC (Windows)

```powershell
# 1. Crear y activar entorno virtual (Python 3.12)
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Descargar el modelo oficial de MediaPipe
python scripts/download_model.py
```

### Probar en PC con el Simulador (antes de encender el carrito)
Abre dos terminales con el entorno virtual activo:
```powershell
# Terminal 1: Simulador del ESP32
python tests/mock_esp32_server.py

# Terminal 2: Cámara + IA apuntando al simulador local
python main.py --host 127.0.0.1
```

### Ejecutar con el Carrito Físico (ESP32)
1. Abre `firmware/esp32_car/esp32_car.ino` en **Arduino IDE**, selecciona tu placa **ESP32 Dev Module** y sube el código.
2. Conecta tu laptop a la red WiFi creada por el carrito:
   - **SSID:** `LawamyRacing_Car`
   - **Contraseña:** `12345678`
3. Ejecuta:
```powershell
python main.py
```

---

## 4. Calibración para la Pista Cuadrada
Mientras pruebas el carrito en la pista, puedes afinar los motores **sin volver a programar el ESP32** usando estas teclas en la ventana de cámara:
- **`+` / `-`**: Sube o baja la velocidad de **Adelante y Atrás**.
- **`.` / `,`**: Sube o baja la velocidad de giro **Izquierda y Derecha** (para esquinas exactas de 90°).
- **`[` / `]`**: Ajusta el **Trim** (si el carrito se carga hacia un lado al ir derecho, compénsalo hasta que avance recto).
- **`G`**: Guarda tu calibración en `calibration.json` para que quede lista para la presentación.
- Si una llanta gira al revés por el cableado, simplemente cambia `INVERT_LEFT_MOTOR` o `INVERT_RIGHT_MOTOR` a `true` en `firmware/esp32_car/esp32_car.ino`.
