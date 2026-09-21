# Donde me conviene comprar

Compara una lista de compras en **Carrefour, Coto, Jumbo, Dia y ChangoMas** con
los precios que esas cadenas publican en ese momento, y le aplica las
**promociones bancarias** vigentes de cada una para decir donde conviene comprar
hoy y que dia de la semana conviene mas.

```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## Que hace

1. Lee tu lista de compras en texto libre, una linea por producto.
2. Busca cada producto en las cinco cadenas, en paralelo.
3. Elige en cada cadena el producto que realmente corresponde a lo que pediste.
4. Suma el total de la canasta por cadena.
5. Aplica la mejor promocion bancaria disponible segun los bancos y billeteras
   que le digas que tenes.
6. Ordena las cadenas por lo que terminarias pagando, y proyecta los proximos
   siete dias para mostrarte si conviene esperar.

---

## De donde salen los datos

Ninguna de estas fuentes requiere clave privada ni login: son los mismos
endpoints publicos que consulta el navegador de cualquier visitante del sitio.

### Precios

| Cadena | Fuente | Formato |
|---|---|---|
| Carrefour | `www.carrefour.com.ar/api/catalog_system/pub/products/search` | VTEX |
| Jumbo | `www.jumbo.com.ar/api/catalog_system/pub/products/search` | VTEX |
| Dia | `diaonline.supermercadosdia.com.ar/api/catalog_system/...` | VTEX |
| ChangoMas | `www.masonline.com.ar/api/catalog_system/...` | VTEX |
| Coto | `ac.cnstrc.com/search/<termino>` | Constructor.io |

Coto no corre sobre VTEX: su tienda es una SPA que busca contra Constructor.io
con una clave publica embebida en su propio bundle `main.*.js`. Esa clave esta
en `precios/coto.py` como `CLAVE_BUSCADOR`. **Es el unico punto fragil del
cliente de precios**: si Coto la rota, hay que volver a leerla de esa pagina.

### Promociones bancarias

| Cadena | Fuente | Formato |
|---|---|---|
| Carrefour | `api/dataentities/BP/search` | VTEX Master Data |
| ChangoMas | `api/dataentities/BP/search` | VTEX Master Data (mismo esquema) |
| Jumbo | `api/dataentities/JN/documents/bankDiscount` | documento JSON unico |
| Coto | `rest/model/atg/actors/cProfileActor/getPromocionesMulticanal` | ATG |
| Dia | bloques de CMS incrustados en el HTML de su pagina de promociones | HTML |

Las cuatro primeras son datos estructurados con un campo por dia de la semana,
porcentaje, vigencia y letra chica. **Dia es la unica que no expone una API**:
sus promociones viajan serializadas dentro del HTML de la pagina. Si Dia cambia
la maquetacion, `promociones/dia.py` devuelve una lista vacia y la app avisa que
le falta esa fuente, en vez de romperse.

### Detalles de las APIs que costaron descubrir

Estan documentados en el codigo, pero conviene tenerlos a mano:

- **El WAF de Carrefour rechaza los espacios codificados como `+`.** Hay que
  mandar `%20`. Si se deja que `requests` arme la query string, responde
  `400 Bad Request! Scripts are not allowed!`. Ver `precios/vtex.py`.
- **La entidad `BP` responde 403 con `_fields=_all`** (`Cannot read private
  fields`): hay que enumerar los campos publicos uno por uno. Ver
  `promociones/vtex_bp.py`.
- **En Jumbo, `discount` es solo un numero y `discountText` es su sufijo.** El
  valor `12` con sufijo `"Cuotas sin interes"` son doce cuotas, no un 12% de
  descuento. Ver `_interpretar_descuento` en `promociones/jumbo.py`.
- **Coto devuelve un precio por cada sucursal**, no un precio unico. Ver
  `_precio_de_sucursal` en `precios/coto.py`.

---

## Las tres decisiones que definen si la app dice la verdad

### 1. No cotizar el producto equivocado

Los buscadores de las cadenas son generosos: pedir `leche` en Carrefour devuelve
`Pepitas artesanales dulce de leche` en el primer puesto. Comparar eso contra la
leche de otra cadena no es comparar precios.

`nucleo/coincidencias.py` vuelve a puntuar cada candidato por cuenta propia y
descarta lo que no llega al umbral. Si ninguna opcion convence, la app dice
**"no lo encontre en esta cadena"** en vez de cotizar cualquier cosa, y muestra
cuantos items le faltaron a cada cadena.

### 2. No dejarse enganar por fichas viejas

Los catalogos arrastran productos dados de baja que conservan el precio de hace
anios. Hoy conviven en Coto un arroz de 1 kg a $1.770 y otro, de nombre casi
identico, a $78,90. Tomar el segundo como "el precio de Coto" no seria encontrar
una oferta: seria un error.

`descartar_atipicos` corta contra la mediana de los propios candidatos de esa
busqueda, no contra un monto fijo, para que el criterio siga sirviendo cuando
los precios cambien.

### 3. Comparar el costo de cubrir lo que pediste, no el precio de la etiqueta

Si pedis 1 kg y una cadena solo vende paquetes de 500 g, hacen falta dos. Sin
ese ajuste gana siempre la cadena que vende el formato mas chico, que es justo
al reves de lo que conviene. La columna **Envases** del detalle muestra cuantos
se contaron.

---

## Como se aplican las promociones

- **Solo una promo por cadena.** Las promociones bancarias de supermercado no se
  acumulan: se paga con un medio y se obtiene un beneficio. La app elige la que
  mas ahorra.
- **Gana la que mas ahorra, no la del porcentaje mas alto.** Un 30% con tope de
  $10.000 ahorra menos que un 15% sin tope en una compra de $120.000.
- **MODO no es un banco.** Una promo de "40% con Credicoop a traves de MODO"
  exige la tarjeta de Credicoop; tener la app instalada no alcanza. La app solo
  la da por cumplida cuando MODO es lo unico que la promo nombra. Ver
  `tiene_medio` en `motor/decision.py`.
- **Sucursal y web tienen promos distintas.** El selector "Como vas a comprar"
  filtra las que no aplican.

---

## Limitaciones conocidas

- **El precio depende de la sucursal.** Las cadenas publican listas distintas
  por zona. Sin sucursal elegida, de Coto se toma el precio *mas frecuente*
  entre sus sucursales, no el minimo, para no hacerlo parecer sistematicamente
  mas barato de lo que es en CABA y GBA. Las cuatro cadenas VTEX devuelven la
  lista de su canal de venta por defecto; `precios/registro.py` tiene el campo
  `canal_venta` preparado para fijarla.
- **Los precios son los de la tienda online.** Pueden no coincidir exactamente
  con la gondola del local.
- **El banco se deduce del texto de la promo.** Ninguna cadena publica el
  emisor en un campo normalizado utilizable: Carrefour y Coto usan ids internos
  sin catalogo publico. El vocabulario esta en `promociones/bancos.py` y una
  promo con un emisor no listado queda sin entidad asignada. Esas promos se
  ocultan por defecto y se pueden mostrar con la casilla
  "Incluir promos sin banco identificado".
- **El calendario proyecta promociones, no precios.** Usa los precios de hoy
  para los siete dias. Las promos bancarias son semanales y conocidas de
  antemano; los precios no.
- **La app no compra ni reserva nada.** Solo informa.

---

## Estructura

```
app.py                    interfaz Streamlit; solo presentacion
nucleo/
  modelos.py              tipos que viajan entre capas
  texto.py                normalizacion y lectura de envases
  lista.py                parseo de la lista de compras
  coincidencias.py        puntuacion producto-pedido, atipicos, costo efectivo
precios/
  base.py                 sesion HTTP con reintentos y limites
  vtex.py                 Carrefour, Jumbo, Dia, ChangoMas
  coto.py                 Constructor.io
  registro.py             que cadena se consulta con que cliente
promociones/
  bancos.py               vocabulario de entidades, topes y porcentajes
  vtex_bp.py              Carrefour y ChangoMas
  jumbo.py                Jumbo
  dia.py                  Dia
  coto.py                 Coto
  agregador.py            las cinco en paralelo, tolerante a fallos
motor/
  canasta.py              cotiza la lista en cada cadena
  decision.py             aplica promos, rankea y arma el calendario
ui/
  tema.py                 paleta y CSS
```

Las dependencias van en una sola direccion: `app` depende de `motor`, `motor` de
`precios` y `promociones`, y todos de `nucleo`. `nucleo` no depende de nada.
