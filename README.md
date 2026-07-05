# Green Monitor — Crecimiento vegetal por ROI

[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.1%2B-000000?logo=flask)](https://flask.palletsprojects.com/)
[![OpenCV](https://img.shields.io/badge/OpenCV-4.10%2B-5C3EE8?logo=opencv)](https://opencv.org/)
[![CI](https://github.com/drbash/green-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/drbash/green-monitor/actions)

Web app Flask para monitorear crecimiento vegetal mediante análisis de cobertura verde en un ROI poligonal, desde streaming MJPEG o imágenes fijas.

## Contenido

- [Características](#caracter%C3%ADsticas)
- [Stack](#stack)
- [Estructura](#estructura)
- [Requisitos](#requisitos)
- [Instalación](#instalaci%C3%B3n)
- [Uso](#uso)
- [API](#api)
- [Tests](#tests)
- [Configuración](#configuraci%C3%B3n)
- [CI/CD](#cicd)
- [Datos](#datos)
- [Nota técnica](#nota-t%C3%A9cnica)
- [Limitaciones / Roadmap](#limitaciones--roadmap)
- [Licencia](#licencia)

## Características

- **Stream MJPEG** con overlay de ROI y métricas
- **Dibujo de ROI poligonal** desde el navegador
- **Cobertura verde ROI (%)**: píxeles verdes dentro del polígono
- **Baseline automático**: calibración inicial al guardar ROI
- **Crecimiento vs baseline**: `max(0, cobertura_actual - baseline)`
- **Histórico automático**: guarda el máximo crecimiento por ventana temporal
- **Gráfico histórico** embebido en la interfaz web
- **Fallback a imagen fija** para demo sin cámara
- **Fuentes**: RTSP, cámara USB o imagen estática

## Stack

| Componente | Tecnología |
|---|---|
| Backend | Python 3.11+, Flask 3.1+ |
| Visión | OpenCV 4.10+, NumPy |
| Frontend | HTML5, CSS3, JavaScript |
| Testing | pytest |

## Estructura

```
green-monitor/
├── app.py                  # Aplicación Flask principal
├── static/
│   ├── app.js              # Lógica frontend
│   └── styles.css
├── templates/
│   └── index.html          # Interfaz web
├── data/                   # Datos persistentes
│   ├── roi_polygon.json
│   ├── app_state.json
│   ├── growth_history.csv
│   ├── history_latest.json
│   └── history_window.json
├── tests/
├── .env.example
├── .github/workflows/ci.yml
├── pyproject.toml
├── requirements.txt
└── README.md
```

## Requisitos

- Python 3.11+
- Cámara RTSP / USB o imagen estática para demo
- Navegador moderno

## Instalación

```bash
git clone https://github.com/drbash/green-monitor.git
cd green-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

### Ejecución rápida con imagen fija

```bash
python app.py
```

Abrir en navegador: [http://127.0.0.1:8000](http://127.0.0.1:8000)

### Usar cámara RTSP

```bash
export STREAM_SOURCE='rtsp://usuario:clave@IP:554/Streaming/Channels/101'
python app.py
```

### Usar cámara USB local

```bash
export STREAM_SOURCE='0'
python app.py
```

### Flujo recomendado

1. Abrir la app y pulsar **Capturar frame para ROI**
2. Dibujar el polígono sobre la bandeja
3. Pulsar **Guardar ROI** (el sistema recalibra el baseline)
4. Al aparecer brotes verdes, el crecimiento empezará a subir
5. La app guarda el valor máximo de crecimiento por ventana temporal

## API

| Ruta | Descripción |
|---|---|
| `/` | Interfaz web |
| `/video_feed` | Stream MJPEG |
| `/api/status` | Métricas actuales (JSON) |
| `/api/history/latest` | Último guardado + ventana actual |
| `/api/history.csv` | CSV histórico descargable |

## Tests

```bash
pip install pytest
pytest tests/ -v
```

## Configuración

Variables de entorno (ver `.env.example`):

| Variable | Default | Descripción |
|---|---|---|
| `STREAM_SOURCE` | `data/sample_baseline.png` | Fuente de video (RTSP, USB o archivo) |
| `HISTORY_SAVE_MINUTES` | `5` | Intervalo de guardado histórico |
| `FRAME_WAIT` | `0.2` | Segundos entre frames |
| `AUTO_BASELINE_ON_START` | `1` | Calibrar baseline al iniciar |
| `MIN_CONTOUR_AREA` | `10` | Área mínima de contorno verde |
| `CONTOUR_FILL_ALPHA` | `0.35` | Opacidad del overlay de contornos |

## CI/CD

GitHub Actions ejecuta lint (Ruff) y tests (pytest) en cada push/PR.

## Datos

Archivos persistentes en `data/`:

- `roi_polygon.json` — Polígono ROI
- `app_state.json` — Baseline guardado
- `growth_history.csv` — Histórico consolidado por ventanas
- `history_latest.json` — Último registro guardado
- `history_window.json` — Pico de la ventana actual

## Nota técnica

La detección de verde usa combinación de:

- Umbral HSV + índice ExG (`2G - R - B`)
- Limpieza morfológica
- Exclusión de reflejos brillantes

El histórico guarda el mejor `growth_pct` de cada ventana; en empate, prioriza mayor cobertura verde.

## Limitaciones / Roadmap

- [x] Detección de verde con umbral HSV + ExG
- [x] ROI poligonal interactivo
- [x] Histórico por ventanas temporales
- [ ] Normalización de iluminación
- [ ] Análisis por alveolo/celda
- [ ] Confirmación temporal en N frames
- [ ] Modelo de segmentación entrenado (deep learning)
- [ ] Notificaciones push al superar umbral

## Licencia

MIT
