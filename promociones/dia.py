"""Promociones bancarias de Dia.

Responsabilidad unica: extraer los bloques de promocion que Dia deja incrustados
en el HTML de su pagina de medios de pago y traducirlos a `Promo`.

Dia es la unica de las cinco cadenas que no expone las promociones por una API.
Las guarda como contenido del CMS de VTEX y las serializa dentro del HTML de la
pagina, en objetos con esta forma:

    {"__editorItemTitle": "Columbia 20% de reintegro",
     "daysToShow": {"monday": true, ...},
     "associatedBanks": [{"__editorItemTitle": "Banco Columbia"}],
     "availableOn": {"online": true, "store": true, "all": true},
     "terms": "...", "active": true}

Los datos son estructurados; lo fragil es solo su ubicacion. Si Dia cambia la
maquetacion, `obtener` devuelve una lista vacia en vez de romper: la app sigue
comparando precios y avisa que no pudo leer las promos de esta cadena.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re

import requests

from nucleo.modelos import Promo
from promociones import bancos
from precios.base import TIEMPO_ESPERA, ErrorCadena

LOGGER = logging.getLogger(__name__)

URL = "https://diaonline.supermercadosdia.com.ar/medios-de-pago-y-promociones"

_DIAS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

# Ancla de busqueda: cada promocion contiene esta clave exactamente una vez.
_ANCLA = '"daysToShow"'

# Cuanto se retrocede desde el ancla buscando el inicio del objeto contenedor.
_VENTANA_ATRAS = 4000

_RE_VIGENCIA = re.compile(
    r"vigencia\s+desde\s+el\s+(\d{2}/\d{2}/\d{4})\s+hasta\s+el\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)


def obtener(sesion: requests.Session) -> list[Promo]:
    """Descarga la pagina de promociones de Dia y normaliza lo que encuentre."""
    try:
        respuesta = sesion.get(URL, timeout=TIEMPO_ESPERA)
    except requests.RequestException as exc:
        raise ErrorCadena("dia", f"no se pudo abrir la pagina ({exc.__class__.__name__})") from exc
    if respuesta.status_code != 200:
        raise ErrorCadena("dia", f"la pagina respondio HTTP {respuesta.status_code}")

    bloques = _extraer_bloques(respuesta.text)
    if not bloques:
        raise ErrorCadena("dia", "no se encontraron promociones en la pagina")

    promos: list[Promo] = []
    vistos: set[str] = set()
    for bloque in bloques:
        promo = _a_promo(bloque)
        if not promo:
            continue
        # La pagina repite el mismo bloque en la version de escritorio y en la
        # de movil; sin esta guarda cada promo aparece dos veces.
        firma = f"{promo.titulo}|{sorted(promo.dias)}"
        if firma in vistos:
            continue
        vistos.add(firma)
        promos.append(promo)
    return promos


def _extraer_bloques(html: str) -> list[dict]:
    """Recupera los objetos JSON de promocion incrustados en el HTML."""
    decodificador = json.JSONDecoder()
    bloques: list[dict] = []
    posicion = 0

    while True:
        ancla = html.find(_ANCLA, posicion)
        if ancla == -1:
            break
        posicion = ancla + len(_ANCLA)

        # Se retrocede hasta la llave de apertura del objeto que contiene el
        # ancla. Como el contenido anterior tambien tiene llaves, se prueba cada
        # candidata de la mas cercana a la mas lejana hasta que una decodifique.
        inicio = max(0, ancla - _VENTANA_ATRAS)
        candidatas = [i for i, caracter in enumerate(html[inicio:ancla], inicio) if caracter == "{"]
        for candidata in reversed(candidatas):
            try:
                objeto, _ = decodificador.raw_decode(html[candidata:])
            except ValueError:
                continue
            if isinstance(objeto, dict) and "daysToShow" in objeto:
                bloques.append(objeto)
                break
    return bloques


def _a_promo(bloque: dict) -> Promo | None:
    if bloque.get("active") is False:
        return None

    titulo = (bloque.get("__editorItemTitle") or "").strip()
    if not titulo:
        return None

    dias_crudos = bloque.get("daysToShow")
    if not isinstance(dias_crudos, dict):
        return None
    dias = frozenset(i for i, clave in enumerate(_DIAS) if dias_crudos.get(clave) is True)
    if not dias:
        return None

    nombres_banco = " ".join(
        (entrada.get("__editorItemTitle") or "")
        for entrada in (bloque.get("associatedBanks") or [])
        if isinstance(entrada, dict)
    )
    condiciones = (bloque.get("terms") or "").strip() or None

    disponible = bloque.get("availableOn") or {}
    en_linea = bool(disponible.get("online") or disponible.get("all"))
    en_sucursal = bool(disponible.get("store") or disponible.get("all"))

    desde, hasta = _vigencia(condiciones)

    return Promo(
        cadena="dia",
        titulo=titulo,
        bancos=bancos.detectar_entidades(nombres_banco, titulo),
        # El titulo no siempre trae el porcentaje ("Personal Pay", "Anses").
        # Cuando falta, se lee del arranque de la letra chica, que es donde Dia
        # lo enuncia ("BNA JUBILADOS 5%..."). Se limita a los primeros
        # caracteres para no capturar un porcentaje de otra clausula.
        porcentaje=(
            bancos.detectar_porcentaje(titulo)
            or bancos.detectar_porcentaje((condiciones or "")[:200])
        ),
        dias=dias,
        tope=bancos.detectar_tope(condiciones, titulo),
        cuotas=bancos.detectar_cuotas(titulo, condiciones),
        medio_pago=", ".join(bancos.detectar_marcas(titulo, nombres_banco)) or None,
        requiere_modo="modo" in bancos.detectar_entidades(nombres_banco, titulo),
        vigencia_desde=desde,
        vigencia_hasta=hasta,
        solo_online=en_linea and not en_sucursal,
        solo_sucursal=en_sucursal and not en_linea,
        detalle=nombres_banco.strip() or None,
        legal=condiciones,
    )


def _vigencia(condiciones: str | None) -> tuple[dt.date | None, dt.date | None]:
    """Lee "VIGENCIA DESDE EL dd/mm/aaaa HASTA EL dd/mm/aaaa" de la letra chica."""
    if not condiciones:
        return None, None
    coincidencia = _RE_VIGENCIA.search(condiciones)
    if not coincidencia:
        return None, None
    return _fecha(coincidencia.group(1)), _fecha(coincidencia.group(2))


def _fecha(texto: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(texto, "%d/%m/%Y").date()
    except ValueError:
        return None
