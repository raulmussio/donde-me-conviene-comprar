"""Punto de entrada unico de promociones bancarias.

Responsabilidad unica: juntar las promociones de las cinco cadenas en una sola
lista de `Promo`, consultandolas en paralelo y sin que el fallo de una tumbe al
resto.

Ese aislamiento importa: las fuentes son heterogeneas y la de Dia depende del
HTML de su pagina. Si Dia cambia la maquetacion, la app tiene que seguir
comparando precios y avisar que le falta una fuente, no caerse.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests

from nucleo.modelos import Promo
from precios.base import ErrorCadena, nueva_sesion
from promociones import coto as fuente_coto
from promociones import dia as fuente_dia
from promociones import jumbo as fuente_jumbo
from promociones import vtex_bp

LOGGER = logging.getLogger(__name__)


@dataclass
class Promociones:
    """Promociones de todas las cadenas, con el detalle de lo que fallo."""

    items: list[Promo] = field(default_factory=list)
    fallos: dict[str, str] = field(default_factory=dict)

    def de_cadena(self, cadena: str) -> list[Promo]:
        return [promo for promo in self.items if promo.cadena == cadena]

    @property
    def entidades_disponibles(self) -> list[str]:
        """Claves de entidades mencionadas en alguna promo, ordenadas por uso."""
        conteo: dict[str, int] = {}
        for promo in self.items:
            for clave in promo.bancos:
                conteo[clave] = conteo.get(clave, 0) + 1
        return sorted(conteo, key=lambda clave: (-conteo[clave], clave))


def obtener_todas(sesion: requests.Session | None = None) -> Promociones:
    """Consulta las cinco fuentes en paralelo y devuelve lo que haya salido bien."""
    propia = sesion is None
    sesion = sesion or nueva_sesion()

    tareas = {
        "carrefour": lambda: vtex_bp.obtener(sesion, cadena="carrefour"),
        "changomas": lambda: vtex_bp.obtener(sesion, cadena="changomas"),
        "jumbo": lambda: fuente_jumbo.obtener(sesion),
        "dia": lambda: fuente_dia.obtener(sesion),
        "coto": lambda: fuente_coto.obtener(sesion),
    }

    resultado = Promociones()
    try:
        with ThreadPoolExecutor(max_workers=len(tareas)) as ejecutor:
            futuros = {cadena: ejecutor.submit(tarea) for cadena, tarea in tareas.items()}
            for cadena, futuro in futuros.items():
                try:
                    resultado.items.extend(futuro.result())
                except ErrorCadena as exc:
                    LOGGER.warning("promociones de %s: %s", cadena, exc.mensaje)
                    resultado.fallos[cadena] = exc.mensaje
                except Exception as exc:  # noqa: BLE001 - una fuente rota no puede tumbar al resto
                    LOGGER.exception("promociones de %s: fallo inesperado", cadena)
                    resultado.fallos[cadena] = f"error inesperado ({exc.__class__.__name__})"
    finally:
        if propia:
            sesion.close()

    return resultado
