# Web app de crecimiento vegetal por ROI

App Flask para mostrar streaming MJPEG y calcular crecimiento basado en el aumento de verde **solo dentro de un ROI poligonal**.

## Qué mide

La app calcula:

- **Cobertura verde ROI (%)**: porcentaje del ROI que hoy contiene píxeles verdes.
- **Baseline verde (%)**: valor de referencia inicial.
- **Crecimiento vs baseline (%)**: `max(0, cobertura_actual - baseline)`.

Con esto, si calibras el baseline cuando todavía no hay brotes, el valor partirá cerca de **0%** y subirá a medida que aparezca más verde.

## Funcionalidades

- Stream MJPEG con overlay.
- Dibujo del ROI poligonal desde el navegador.
- Guardado de ROI en JSON.
- Recalibración manual de baseline.
- Guardado automático del máximo de crecimiento por ventana temporal.
- Gráfico histórico embebido en la misma interfaz web.
- Fallback a imagen fija para demo o pruebas.
- **Histórico automático**: cada `N` minutos guarda el **máximo crecimiento detectado** dentro de esa ventana.

## Instalación

```bash
cd crop_growth_app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecución rápida con imagen fija

```bash
python app.py
```

Abrir en navegador:

```text
http://127.0.0.1:8000
```

## Usar cámara RTSP

```bash
export STREAM_SOURCE='rtsp://usuario:clave@IP:554/Streaming/Channels/101'
python app.py
```

## Usar cámara USB local

```bash
export STREAM_SOURCE='0'
python app.py
```

## Ajustar guardado histórico

Por defecto la app guarda el pico cada **5 minutos**.

```bash
export HISTORY_SAVE_MINUTES='5'
python app.py
```

Si quieres más frecuencia, por ejemplo cada 1 minuto:

```bash
export HISTORY_SAVE_MINUTES='1'
python app.py
```

## Flujo recomendado

1. Abrir la app.
2. Pulsar **Capturar frame para ROI**.
3. Dibujar el polígono sobre la bandeja.
4. Pulsar **Guardar ROI**.
5. El sistema recalibra el baseline con el frame actual.
6. Cuando aparezcan brotes verdes, el crecimiento empezará a subir.
7. La app irá guardando en histórico el **valor máximo** de crecimiento de cada ventana temporal.

## Archivos persistentes

- `data/roi_polygon.json`: ROI poligonal.
- `data/app_state.json`: baseline guardado.
- `data/growth_history.csv`: histórico consolidado por ventanas.
- `data/history_latest.json`: último registro ya guardado.
- `data/history_window.json`: pico temporal de la ventana actual en curso.

## Endpoints útiles

- `/api/status`: métricas actuales.
- `/api/history/latest`: resumen del último guardado y la ventana actual.
- `/api/history.csv`: abre o descarga el CSV histórico.

## Nota técnica

La detección usa una combinación de:

- umbral de verde en HSV,
- índice `ExG = 2G - R - B`,
- limpieza morfológica,
- exclusión básica de reflejos muy brillantes.

El histórico guarda el **mejor valor de `growth_pct`** de cada ventana. Si hay empate, se queda con la lectura de mayor cobertura verde / más píxeles verdes.

Es un MVP práctico. Para producción más robusta convendría agregar:

- normalización de iluminación,
- análisis por alveolo/celda,
- confirmación temporal en N frames,
- y eventualmente un modelo de segmentación entrenado.
