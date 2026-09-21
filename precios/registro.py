"""Registro de las cadenas comparadas y punto de entrada unico de precios.

Responsabilidad unica: saber que cadena se consulta con que cliente y con que
parametros de zona. El resto de la app pide precios por aca y no necesita saber
si detras hay VTEX o Constructor.io.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from nucleo.modelos import Oferta
from precios import coto as cliente_coto
from precios import vtex as cliente_vtex

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Cadena:
    """Como consultar una cadena puntual."""

    clave: str
    nombre: str
    motor: str  # "vtex" | "coto"
    dominio: str
    # Canal de venta de VTEX. Determina la lista de precios que se devuelve y,
    # con ella, la zona. Ver `precios/zonas.py`.
    canal_venta: str | None = None
    url_promociones: str = ""


CADENAS: dict[str, Cadena] = {
    "carrefour": Cadena(
        clave="carrefour",
        nombre="Carrefour",
        motor="vtex",
        dominio="www.carrefour.com.ar",
        url_promociones="https://www.carrefour.com.ar/descuentos-bancarios",
    ),
    "coto": Cadena(
        clave="coto",
        nombre="Coto",
        motor="coto",
        dominio="www.coto.com.ar",
        url_promociones="https://www.coto.com.ar/descuentos",
    ),
    "jumbo": Cadena(
        clave="jumbo",
        nombre="Jumbo",
        motor="vtex",
        dominio="www.jumbo.com.ar",
        url_promociones="https://www.jumbo.com.ar/descuentos-del-dia",
    ),
    "dia": Cadena(
        clave="dia",
        nombre="Dia",
        motor="vtex",
        dominio="diaonline.supermercadosdia.com.ar",
        url_promociones="https://diaonline.supermercadosdia.com.ar/medios-de-pago-y-promociones",
    ),
    "changomas": Cadena(
        clave="changomas",
        nombre="ChangoMas",
        motor="vtex",
        dominio="www.masonline.com.ar",
        url_promociones="https://www.masonline.com.ar/promociones-bancarias",
    ),
}


def buscar(
    sesion: requests.Session,
    *,
    clave_cadena: str,
    consulta: str,
    sucursal_coto: str | None = None,
) -> list[Oferta]:
    """Busca un termino en una cadena y devuelve sus ofertas sin puntuar."""
    cadena = CADENAS.get(clave_cadena)
    if cadena is None:
        raise KeyError(f"cadena desconocida: {clave_cadena}")

    if cadena.motor == "coto":
        return cliente_coto.buscar(sesion, consulta=consulta, sucursal=sucursal_coto)

    return cliente_vtex.buscar(
        sesion,
        cadena=cadena.clave,
        dominio=cadena.dominio,
        consulta=consulta,
        canal_venta=cadena.canal_venta,
    )
