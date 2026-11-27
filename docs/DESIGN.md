# Diseño de la interfaz (estilo iOS)

## Qué archivo hace qué
| Archivo | Responsabilidad | Tócalo si quieres… |
|---|---|---|
| `nimbo/theme.py` | Colores (pares claro/oscuro), presets, fuentes preferidas, iconos por categoría | cambiar la paleta, el color de acento o los iconos |
| `nimbo/ui_widgets.py` | Componentes: botones, tarjetas, lista virtual (`ItemList`), interruptor (`IOSSwitch`), selector, diálogo | cambiar la forma de los botones, redondeos, tamaños |
| `nimbo/ui.py` | Las pantallas (Plan, Historial, Proyectos, Sugerencias, Vigilante, Ajustes) y la barra lateral | mover cosas de sitio, agregar pantallas |

## Cambiar el aspecto desde la terminal (sin tocar código)
```powershell
python -m nimbo theme                         # ver el estado actual y los presets
python -m nimbo theme --preset rose           # ios | rose | mint | sunset | violet | graphite
python -m nimbo theme --accent "#FF2D55"      # cualquier color #RRGGBB
python -m nimbo theme --mode dark             # system | light | dark
python -m nimbo theme --reset                 # volver al azul iOS y modo del sistema
```
También se cambia dentro de la app: pestaña **Ajustes → Apariencia**. Se guarda en `config.json` (clave `theme`).

## Reglas de diseño
- Colores siempre como pares `(claro, oscuro)`: la ventana sigue el modo del sistema sola.
- Fondo gris suave, tarjetas blancas redondeadas (radio 14–16), sin bordes; jerarquía por tamaño de letra, no por líneas.
- Un solo color de acento para acciones; verde solo para "activo/ok", rojo solo para acciones destructivas.
- Interruptores con perilla blanca y pista verde; botones en forma de píldora.
- Confirmaciones con diálogo propio estilo iOS (icono por tipo: pregunta, éxito, aviso, peligro; botones grandes; Enter/Esc) y avisos breves con icono de estado, en lugar de los cuadros grises del sistema.
- Las listas se dibujan en **un solo lienzo** y solo las filas visibles (miles de filas sin lentitud); mientras cargan muestran esqueletos grises.
- Lo dibujado a mano (listas, interruptores) se redibuja al cambiar claro/oscuro con `Style.redraw_all()`.

## Fuentes
Usa la primera disponible: SF Pro → Segoe UI Variable → Segoe UI → Inter → Helvetica Neue. En Windows será Segoe UI.
(SF Pro es de Apple y no se puede redistribuir; Segoe UI es lo más cercano que trae Windows.)

## Limitaciones conocidas
- CustomTkinter no tiene desenfoque translúcido ni sombras reales: se imita con tonos y redondeos.
- Los iconos son símbolos Unicode sobre fichas de color (no SF Symbols). Si falta un símbolo en tu fuente, Windows usa otra de respaldo.
- Cambiar el color de acento reconstruye la ventana (se pierde la selección de las listas, no los datos).

## Tarjeta de IA (Ajustes)
Dos pestañas: **Gemini (API)** —un campo para la clave y el botón *Conectar*, que valida, elige el modelo y guarda— y **Local** (URL + modelo). Un solo diálogo de permiso la primera vez.
