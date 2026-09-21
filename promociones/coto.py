"""Promociones bancarias de Coto.

Responsabilidad unica: leer `getPromocionesMulticanal` y traducirlo a `Promo`.

Coto distingue dos conjuntos que la app necesita por separado:

- `promocionesDigitales`: las que valen comprando por la web.
- `promocionesSucursalesFisicas`: las que valen yendo al local.

Se traen las dos y se marcan con `solo_online` / `solo_sucursal`, porque para
quien va al supermercado en persona las digitales no sirven, y al reves.

Coto identifica al banco con un id numerico interno y no publica el catalogo
que lo traduce, asi que la entidad se deduce del texto de la promocion.
"""

from __future__ import annotations

import logging

import requests

from nucleo.modelos import Promo
from promociones import bancos
from precios.base import ErrorCadena, pedir_json

LOGGER = logging.getLogger(__name__)

URL = (
    "https://www.coto.com.ar/rest/model/atg/actors/cProfileActor/"
    "getPromocionesMulticanal?enviroment=ag&pushSite=CotoDigital"
)

# Los dias vienen como objetos con nombre y con un id propio de Coto, donde
# 1 es domingo. Se mapea por nombre y se deja el id como respaldo.
_POR_NOMBRE = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}


def obtener(sesion: requests.Session) -> list[Promo]:
    """Descarga y normaliza las promociones de Coto, web y sucursal."""
    crudo = pedir_json(sesion, URL, cadena="coto")
    resultado = (crudo or {}).get("result")
    if not isinstance(resultado, dict):
        raise ErrorCadena("coto", "las promociones vinieron en un formato inesperado")

    promos: list[Promo] = []
    for clave, solo_online in (
        ("promocionesDigitales", True),
        ("promocionesSucursalesFisicas", False),
    ):
        for fila in resultado.get(clave) or []:
            promo = _a_promo(fila, solo_online=solo_online)
            if promo:
                promos.append(promo)
    return promos


def _a_promo(fila: dict, *, solo_online: bool) -> Promo | None:
    if not isinstance(fila, dict):
        return None

    texto_descuento = (fila.get("textoDescuento") or "").strip()
    descripcion = (fila.get("descripcion") or "").strip() or None
    observacion = (fila.get("observacion") or "").strip() or None

    titulo = texto_descuento or descripcion
    if not titulo:
        return None

    dias = _dias(fila.get("dias"))
    if not dias:
        # Coto usa la lista vacia para las promos permanentes, sin restriccion
        # de dia. Vale todos los dias.
        dias = frozenset(range(7))

    textos = (texto_descuento, descripcion, observacion)

    return Promo(
        cadena="coto",
        titulo=titulo if not descripcion else f"{titulo} - {descripcion}",
        bancos=bancos.detectar_entidades(*textos),
        porcentaje=bancos.detectar_porcentaje(texto_descuento, descripcion),
        dias=dias,
        tope=bancos.detectar_tope(observacion, descripcion, texto_descuento),
        cuotas=bancos.detectar_cuotas(*textos),
        medio_pago=", ".join(bancos.detectar_marcas(*textos)) or None,
        requiere_modo="modo" in bancos.detectar_entidades(*textos),
        vigencia_desde=None,
        vigencia_hasta=None,
        solo_online=solo_online,
        solo_sucursal=not solo_online,
        detalle=observacion,
        legal=fila.get("urlTerminos") or None,
    )


def _dias(valor: object) -> frozenset[int]:
    """Traduce la lista de dias de Coto a `datetime.weekday()`."""
    if not isinstance(valor, list):
        return frozenset()

    from nucleo.texto import normalizar

    salida: set[int] = set()
    for entrada in valor:
        if not isinstance(entrada, dict):
            continue
        nombre = normalizar(str(entrada.get("descripcion") or ""))
        if nombre in _POR_NOMBRE:
            salida.add(_POR_NOMBRE[nombre])
            continue
        # Respaldo por id: 1 = domingo, 2 = lunes, ... 7 = sabado.
        try:
            identificador = int(entrada.get("id"))
        except (TypeError, ValueError):
            continue
        if 1 <= identificador <= 7:
            salida.add((identificador - 2) % 7)
    return frozenset(salida)
