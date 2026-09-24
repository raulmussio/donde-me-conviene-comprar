"""Reconocimiento de bancos, billeteras y topes dentro del texto de una promo.

Responsabilidad unica: leer texto libre publicado por las cadenas y extraer
(a) que entidades emisoras aplican y (b) cual es el tope de reintegro.

Existe porque ninguna de las cinco cadenas publica el banco en un campo
normalizado utilizable: Carrefour y ChangoMas usan un id interno sin catalogo
publico, Coto usa otro id distinto, y Jumbo y Dia si dan el nombre pero escrito
a mano ("BANCO NACION", "Bco. Nacion", "BNA"). Unificar por texto es lo unico
que funciona en las cinco a la vez.
"""

from __future__ import annotations

import re

from nucleo.texto import normalizar

# Entidades que el usuario puede tener. La clave es el identificador interno;
# los valores son las formas en que las cadenas las escriben.
#
# Se listan primero los alias mas largos para que "banco nacion" gane sobre
# "nacion" y "naranja x" sobre "naranja".
ENTIDADES: dict[str, tuple[str, tuple[str, ...]]] = {
    "santander": ("Santander", ("santander",)),
    "galicia": ("Galicia", ("galicia", "banco galicia")),
    "macro": ("Macro", ("macro", "banco macro")),
    "bbva": ("BBVA", ("bbva", "frances")),
    "nacion": ("Banco Nacion", ("banco nacion", "bna", "nacion", "modo bna")),
    "provincia": ("Banco Provincia", ("banco provincia", "bapro", "cuenta dni", "provincia")),
    "ciudad": ("Banco Ciudad", ("banco ciudad", "ciudad")),
    "icbc": ("ICBC", ("icbc",)),
    "supervielle": ("Supervielle", ("supervielle",)),
    "patagonia": ("Patagonia", ("patagonia",)),
    "hsbc": ("HSBC", ("hsbc",)),
    "credicoop": ("Credicoop", ("credicoop",)),
    "comafi": ("Comafi", ("comafi",)),
    "hipotecario": ("Hipotecario", ("hipotecario",)),
    "itau": ("Itau", ("itau",)),
    "columbia": ("Columbia", ("columbia",)),
    "bancor": ("Bancor / Cordoba", ("bancor", "cordobesa", "banco de cordoba")),
    "santafe": ("Banco Santa Fe", ("santa fe", "bsf")),
    "entrerios": ("Banco Entre Rios", ("entre rios",)),
    "sanjuan": ("Banco San Juan", ("san juan",)),
    "santacruz": ("Banco Santa Cruz", ("santa cruz",)),
    "chubut": ("Banco Chubut", ("chubut",)),
    "tierradelfuego": ("Banco Tierra del Fuego", ("tierra del fuego", "btf")),
    "neuquen": ("Banco Provincia del Neuquen", ("neuquen", "bpn")),
    "tucuman": ("Banco Tucuman", ("tucuman",)),
    "chaco": ("Nuevo Banco del Chaco", ("chaco",)),
    "corrientes": ("Banco de Corrientes", ("corrientes",)),
    "formosa": ("Banco Formosa", ("formosa",)),
    "lapampa": ("Banco La Pampa", ("la pampa",)),
    "delsol": ("Banco del Sol", ("del sol",)),
    "roela": ("Banco Roela", ("roela",)),
    "bica": ("Bica", ("bica",)),
    "coinag": ("Coinag", ("coinag",)),
    "meridian": ("Meridian", ("meridian",)),
    "julio": ("Banco Julio", ("banco julio",)),
    "piano": ("Banco Piano", ("piano",)),
    # Billeteras y emisoras no bancarias.
    "naranja": ("Naranja X", ("naranja x", "naranjax", "naranja")),
    "mercadopago": ("Mercado Pago", ("mercado pago", "mercadopago", "mp")),
    "modo": ("MODO", ("modo",)),
    "uala": ("Uala", ("uala",)),
    "brubank": ("Brubank", ("brubank",)),
    "personalpay": ("Personal Pay", ("personal pay", "personalpay")),
    "prex": ("Prex", ("prex",)),
    "yoy": ("Billetera YOY", ("yoy",)),
    "credicuotas": ("Credicuotas", ("credicuotas",)),
    "cuentadni": ("Cuenta DNI", ("cuenta dni",)),
}

# Canales de pago: no emiten tarjetas, solo transportan la de otro. Una promo
# "40% con Credicoop a traves de MODO" exige la tarjeta de Credicoop; tener MODO
# instalado no alcanza. Ver `decision._tiene_medio`.
CANALES = frozenset({"modo"})

# Marcas de tarjeta. No son entidades emisoras: no se le pregunta al usuario por
# ellas, pero sirven para describir la promo.
MARCAS = ("visa", "mastercard", "maestro", "amex", "american express", "cabal")

# Alias ordenados por longitud descendente: evita que un alias corto tape a uno
# largo que lo contiene.
_ALIAS: list[tuple[str, str]] = sorted(
    ((alias, clave) for clave, (_, alias_lista) in ENTIDADES.items() for alias in alias_lista),
    key=lambda par: -len(par[0]),
)

_RE_TOPE = re.compile(
    r"tope[^$\d]{0,40}\$\s?([\d.]+(?:,\d+)?)",
    re.IGNORECASE,
)
_RE_SIN_TOPE = re.compile(r"sin\s+tope", re.IGNORECASE)
_RE_PORCENTAJE = re.compile(r"(\d{1,2}(?:[.,]\d+)?)\s?%")
_RE_CUOTAS = re.compile(r"(\d{1,2})\s*cuotas?\s*sin\s*inter", re.IGNORECASE)


# Prefijos que no distinguen nada: dieciseis de las treinta y seis entidades
# empiezan con "Banco", asi que en una lista para elegir la propia obligan a
# leer mas alla de la primera palabra en casi la mitad de los casos. Se ordenan
# de mas largo a mas corto para que "Banco de " gane sobre "Banco ".
_PREFIJOS_GENERICOS = (
    "nuevo banco del ",
    "nuevo banco de ",
    "banco de la ",
    "banco del ",
    "banco de ",
    "banco ",
    "billetera ",
)


def nombre_entidad(clave: str) -> str:
    """Nombre presentable de una entidad a partir de su clave interna."""
    entrada = ENTIDADES.get(clave)
    return entrada[0] if entrada else clave.title()


def nombre_corto(clave: str) -> str:
    """El nombre sin el prefijo generico, para listas donde hay que buscar.

    "Banco Nacion" se muestra como "Nacion" y "Nuevo Banco del Chaco" como
    "Chaco", que es ademas como los nombra cualquiera. El nombre completo se
    sigue usando donde hay lugar y hace falta precision, como al explicar de
    que promocion salio un descuento.
    """
    completo = nombre_entidad(clave)
    plano = normalizar(completo)
    for prefijo in _PREFIJOS_GENERICOS:
        if not plano.startswith(prefijo) or len(plano) <= len(prefijo):
            continue
        recorte = completo[len(prefijo) :].strip()
        if not recorte:
            continue
        # Si lo que queda es una sola palabra corta, el articulo hace falta para
        # que se entienda: "Banco del Sol" se reconoce como "Del Sol", no
        # como "Sol" a secas.
        if prefijo.endswith(("del ", "de ", "de la ")) and len(recorte.split()) == 1 and len(recorte) <= 4:
            continue
        return recorte[:1].upper() + recorte[1:]
    return completo


def detectar_entidades(*textos: str | None) -> tuple[str, ...]:
    """Claves de las entidades mencionadas en los textos dados.

    Se busca sobre el texto normalizado y con limites de palabra, para que
    "macro" no dispare dentro de "macronutrientes".
    """
    plano = " ".join(normalizar(t) for t in textos if t)
    if not plano:
        return ()

    encontradas: list[str] = []
    consumido = plano
    for alias, clave in _ALIAS:
        if clave in encontradas:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", consumido):
            encontradas.append(clave)
            # Se tacha el alias ya usado para que un alias mas corto contenido
            # en el no vuelva a disparar sobre el mismo fragmento.
            consumido = re.sub(re.escape(alias), " ", consumido)
    return tuple(encontradas)


def detectar_marcas(*textos: str | None) -> tuple[str, ...]:
    """Marcas de tarjeta mencionadas (Visa, Mastercard, ...)."""
    plano = " ".join(normalizar(t) for t in textos if t)
    return tuple(marca for marca in MARCAS if marca in plano)


def detectar_tope(*textos: str | None) -> float | None:
    """Tope de reintegro en pesos. None si no hay tope o no se pudo leer."""
    for texto in textos:
        if not texto:
            continue
        if _RE_SIN_TOPE.search(texto):
            return None
        coincidencia = _RE_TOPE.search(texto)
        if not coincidencia:
            continue
        crudo = coincidencia.group(1).replace(".", "").replace(",", ".")
        try:
            valor = float(crudo)
        except ValueError:
            continue
        # Los topes reales van de unos pocos miles a cientos de miles de pesos.
        # Fuera de ese rango casi siempre se capturo un numero de otra cosa.
        if 500 <= valor <= 2_000_000:
            return valor
    return None


def detectar_porcentaje(*textos: str | None) -> float | None:
    """Porcentaje de descuento leido del texto ("20% DE DESCUENTO" -> 20.0)."""
    for texto in textos:
        if not texto:
            continue
        coincidencia = _RE_PORCENTAJE.search(texto)
        if coincidencia:
            try:
                valor = float(coincidencia.group(1).replace(",", "."))
            except ValueError:
                continue
            if 0 < valor <= 100:
                return valor
    return None


def detectar_cuotas(*textos: str | None) -> int | None:
    """Cantidad de cuotas sin interes mencionada, si la hay."""
    for texto in textos:
        if not texto:
            continue
        coincidencia = _RE_CUOTAS.search(texto)
        if coincidencia:
            return int(coincidencia.group(1))
    return None
