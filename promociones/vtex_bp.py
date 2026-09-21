"""Promociones bancarias de Carrefour y ChangoMas.

Responsabilidad unica: leer la entidad `BP` de VTEX Master Data y traducirla a
objetos `Promo`.

Las dos cadenas usan la misma aplicacion de promociones (esta construida por el
mismo proveedor), asi que comparten esquema: una fila por promocion, con un
booleano por dia de la semana y las fechas de vigencia.

Detalle de la API: hay que pedir los campos explicitamente. Con `_fields=_all`
el endpoint responde 403 "Cannot read private fields", porque la entidad mezcla
campos publicos con campos internos.
"""

from __future__ import annotations

import datetime as dt
import logging

import requests

from nucleo.modelos import Promo
from promociones import bancos
from precios.base import ErrorCadena, pedir_json

LOGGER = logging.getLogger(__name__)

DOMINIOS = {
    "carrefour": "www.carrefour.com.ar",
    "changomas": "www.masonline.com.ar",
}

# Orden de `datetime.weekday()`: lunes=0 .. domingo=6.
_DIAS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

_CAMPOS = ",".join(
    (
        "id",
        "title",
        "sub_title",
        "discount_percentage",
        "discounts_amount_installments",
        "discounts_text_installments",
        *_DIAS,
        "legal",
        "active",
        "active_from",
        "active_to",
        "hyper",
        "market",
        "express",
        "maxi",
        "ecommerce",
    )
)


def obtener(sesion: requests.Session, *, cadena: str) -> list[Promo]:
    """Descarga y normaliza las promociones bancarias de una de las dos cadenas."""
    dominio = DOMINIOS.get(cadena)
    if not dominio:
        raise KeyError(f"cadena sin entidad BP: {cadena}")

    url = f"https://{dominio}/api/dataentities/BP/search?_fields={_CAMPOS}&_where=active=true"
    crudo = pedir_json(
        sesion,
        url,
        cadena=cadena,
        cabeceras={
            "Accept": "application/vnd.vtex.ds.v10+json",
            "REST-Range": "resources=0-500",
        },
    )
    if not isinstance(crudo, list):
        raise ErrorCadena(cadena, "la entidad de promociones devolvio un formato inesperado")

    promos: list[Promo] = []
    for fila in crudo:
        promo = _a_promo(fila, cadena=cadena)
        if promo:
            promos.append(promo)
    return promos


def _a_promo(fila: dict, *, cadena: str) -> Promo | None:
    titulo = (fila.get("title") or "").strip()
    if not titulo:
        return None

    dias = frozenset(indice for indice, clave in enumerate(_DIAS) if _verdadero(fila.get(clave)))
    if not dias:
        # Sin dias marcados la promo no es aplicable a ninguna fecha; suele ser
        # una fila de borrador que quedo activa.
        return None

    subtitulo = (fila.get("sub_title") or "").strip() or None
    legal = (fila.get("legal") or "").strip() or None

    porcentaje = _numero(fila.get("discount_percentage"))
    if porcentaje is None:
        porcentaje = bancos.detectar_porcentaje(titulo, subtitulo)

    cuotas = _entero(fila.get("discounts_amount_installments"))
    if cuotas is None:
        cuotas = bancos.detectar_cuotas(titulo, subtitulo)

    en_sucursal = any(_verdadero(fila.get(c)) for c in ("hyper", "market", "express", "maxi"))
    en_linea = _verdadero(fila.get("ecommerce"))

    return Promo(
        cadena=cadena,
        titulo=titulo,
        bancos=bancos.detectar_entidades(titulo, subtitulo, legal),
        porcentaje=porcentaje,
        dias=dias,
        tope=bancos.detectar_tope(subtitulo, titulo, legal),
        cuotas=cuotas,
        medio_pago=", ".join(bancos.detectar_marcas(titulo, subtitulo)) or None,
        requiere_modo="modo" in bancos.detectar_entidades(titulo, subtitulo),
        vigencia_desde=_fecha(fila.get("active_from")),
        vigencia_hasta=_fecha(fila.get("active_to")),
        solo_online=en_linea and not en_sucursal,
        solo_sucursal=en_sucursal and not en_linea,
        detalle=subtitulo,
        legal=legal,
    )


def _verdadero(valor: object) -> bool:
    """VTEX Master Data devuelve los booleanos como bool o como texto."""
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() == "true"


def _numero(valor: object) -> float | None:
    if valor is None or valor == "":
        return None
    try:
        numero = float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return numero if 0 < numero <= 100 else None


def _entero(valor: object) -> int | None:
    numero = _numero(valor)
    return int(numero) if numero else None


def _fecha(valor: object) -> dt.date | None:
    if not valor:
        return None
    texto = str(valor).strip().replace("Z", "")
    for formato in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(texto[: len(formato) + 6], formato).date()
        except ValueError:
            continue
    try:
        return dt.datetime.fromisoformat(texto).date()
    except ValueError:
        return None
