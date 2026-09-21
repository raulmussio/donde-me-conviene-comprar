"""Promociones bancarias de Jumbo.

Responsabilidad unica: leer la entidad `JN` de Cencosud y traducirla a `Promo`.

Jumbo publica todas sus promos en un unico documento JSON que comparte con las
otras banderas del grupo (Disco y Vea). Por eso hay que filtrar por `websites`:
sin ese filtro se cuelan descuentos que solo valen en Disco.

Las fechas vienen como epoch en segundos y muchas filas estan vencidas, asi que
el filtro por vigencia no es opcional.
"""

from __future__ import annotations

import datetime as dt
import json
import logging

import requests

from nucleo.modelos import Promo
from promociones import bancos
from precios.base import ErrorCadena, pedir_json

LOGGER = logging.getLogger(__name__)

URL = (
    "https://www.jumbo.com.ar/api/dataentities/JN/documents/bankDiscount"
    "?_fields=value,id&an=jumboargentina"
)

# Identificador de la bandera Jumbo dentro del documento compartido del grupo.
SITIO = "jumboargentina"

# En este esquema los dias van de "1" (lunes) a "7" (domingo).
_DESPLAZAMIENTO_DIA = 1


def obtener(sesion: requests.Session) -> list[Promo]:
    """Descarga y normaliza las promociones vigentes de Jumbo."""
    crudo = pedir_json(sesion, URL, cadena="jumbo")
    valor = (crudo or {}).get("value")
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except ValueError as exc:
            raise ErrorCadena("jumbo", "las promociones no se pudieron leer") from exc
    if not isinstance(valor, list):
        raise ErrorCadena("jumbo", "las promociones vinieron en un formato inesperado")

    hoy = dt.date.today()
    promos: list[Promo] = []
    for fila in valor:
        promo = _a_promo(fila)
        if promo and _sigue_viva(promo, hoy):
            promos.append(promo)
    return promos


def _sigue_viva(promo: Promo, hoy: dt.date) -> bool:
    """Descarta lo ya vencido. El documento arrastra filas de anios anteriores."""
    return not promo.vigencia_hasta or promo.vigencia_hasta >= hoy


def _a_promo(fila: dict) -> Promo | None:
    if not isinstance(fila, dict):
        return None

    sitios = fila.get("websites") or []
    if sitios and SITIO not in sitios:
        return None

    dias = _dias(fila.get("days"))
    if not dias:
        return None

    # `discount` es solo el numero; `discountText` es su sufijo. Juntos forman
    # la frase que ve el cliente: "20" + "% de reintegro", pero tambien
    # "12" + "Cuotas sin interes". Leer `discount` como porcentaje sin mirar el
    # sufijo convierte 12 cuotas en un 12% de descuento que no existe.
    porcentaje, cuotas_numero = _interpretar_descuento(
        fila.get("discount"), fila.get("discountText")
    )
    texto = _frase(fila.get("discount"), fila.get("discountText"))
    info = (fila.get("info") or "").strip() or None
    legales = (fila.get("legals") or "").strip() or None
    cuotas_texto = (fila.get("installmentsText") or "").strip() or None

    nombres_banco = [
        (banco.get("name") or "").strip()
        for banco in (fila.get("banks") or [])
        if isinstance(banco, dict)
    ]
    texto_bancos = " ".join(n for n in nombres_banco if n)

    titulo = texto or _titulo_sintetico(porcentaje, texto_bancos, cuotas_texto)
    if not titulo:
        return None

    medios = fila.get("paymentMethod")
    medio = ", ".join(medios.keys()) if isinstance(medios, dict) and medios else None

    return Promo(
        cadena="jumbo",
        titulo=titulo,
        bancos=bancos.detectar_entidades(texto_bancos, titulo, info),
        porcentaje=porcentaje,
        dias=dias,
        tope=bancos.detectar_tope(info, legales, titulo),
        cuotas=cuotas_numero or bancos.detectar_cuotas(cuotas_texto, titulo),
        medio_pago=medio or (", ".join(bancos.detectar_marcas(titulo, info)) or None),
        requiere_modo="modo" in bancos.detectar_entidades(texto_bancos, titulo),
        vigencia_desde=_fecha(fila.get("dateStart")),
        vigencia_hasta=_fecha(fila.get("dateEnd")),
        solo_online=False,
        solo_sucursal=False,
        detalle=info,
        legal=legales,
    )


def _interpretar_descuento(
    valor: object, sufijo: object
) -> tuple[float | None, int | None]:
    """Decide si el numero de `discount` es un porcentaje o una cantidad de cuotas.

    Devuelve (porcentaje, cuotas); solo uno de los dos viene informado.
    """
    numero = _numero_crudo(valor)
    if numero is None:
        return None, None

    texto = str(sufijo or "").strip().lower()
    es_cuotas = texto.startswith("cuota") or texto.startswith("csi")
    if not es_cuotas and "%" not in texto:
        es_cuotas = "cuota" in texto or "csi" in texto

    if es_cuotas:
        return None, int(numero) if 1 <= numero <= 36 else None
    if "%" in texto:
        return (numero, None) if 0 < numero <= 100 else (None, None)
    if not texto and 0 < numero <= 60:
        # Sufijo vacio: la web muestra solo el numero dentro de un recuadro con
        # el simbolo de porcentaje dibujado. Se acota a 60 para no confundirlo
        # con un monto.
        return numero, None
    # Cualquier otro sufijo ("mil $", "de reintegro en pesos") significa que el
    # numero no es un porcentaje. Preferimos no informar descuento antes que
    # inventar uno: un "100 mil $" leido como 100% arruinaria la comparacion.
    return None, None


def _frase(valor: object, sufijo: object) -> str:
    """Reconstruye la frase que muestra la web uniendo numero y sufijo."""
    numero = _numero_crudo(valor)
    texto = str(sufijo or "").strip()
    if numero is None:
        return texto
    separador = "" if texto.startswith("%") else " "
    return f"{numero:g}{separador}{texto}".strip()


def _titulo_sintetico(
    porcentaje: float | None, texto_bancos: str, cuotas_texto: str | None
) -> str:
    """Titulo armado a mano cuando la fila no trae `discountText`."""
    partes: list[str] = []
    if porcentaje:
        partes.append(f"{porcentaje:g}% de descuento")
    elif cuotas_texto:
        partes.append(cuotas_texto.capitalize())
    if texto_bancos:
        partes.append(f"con {texto_bancos}")
    return " ".join(partes)


def _dias(valor: object) -> frozenset[int]:
    """Pasa la lista de dias del esquema (1=lunes) a `datetime.weekday()`."""
    if not isinstance(valor, list):
        return frozenset()
    salida: set[int] = set()
    for entrada in valor:
        try:
            numero = int(str(entrada).strip())
        except (TypeError, ValueError):
            continue
        if 1 <= numero <= 7:
            salida.add(numero - _DESPLAZAMIENTO_DIA)
    return frozenset(salida)


def _numero(valor: object) -> float | None:
    numero = _numero_crudo(valor)
    return numero if numero is not None and 0 < numero <= 100 else None


def _numero_crudo(valor: object) -> float | None:
    """Numero tal cual viene, sin acotar el rango."""
    if valor in (None, ""):
        return None
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _fecha(valor: object) -> dt.date | None:
    """Convierte un epoch en segundos a fecha. Tolera strings y vacios."""
    if valor in (None, ""):
        return None
    try:
        segundos = int(str(valor).strip())
    except (TypeError, ValueError):
        return None
    if segundos <= 0:
        return None
    try:
        return dt.datetime.fromtimestamp(segundos).date()
    except (OverflowError, OSError, ValueError):
        return None
