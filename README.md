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
3. Acuerda un envase comun a todas las cadenas y, si fijaste una marca, la
   respeta; con eso elige en cada cadena el producto que corresponde.
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
- **Pasar `regionId` como parametro de la busqueda VTEX no hace nada.** El
  endpoint lo acepta y lo ignora: devuelve los mismos precios para CABA que para
  Cordoba. La zona se aplica con la cookie `vtex_segment`. Ver `precios/vtex.py`.

---

## Las seis decisiones que definen si la app dice la verdad

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

### 4. Comparar el mismo envase en todas las cadenas

Cuando no escribis el tamano, cada cadena elegia el suyo y la comparacion dejaba
de significar algo. Pedir `coca cola` traia una botella de 220 ml en Carrefour,
una de 600 ml en Coto y una de 354 ml en ChangoMas, y ganaba el envase mas
chico, no el mejor precio. Pedir `queso crema` traia un paquete de Cheetos de
43 gramos compitiendo contra potes de 290.

`nucleo/formato.py` acuerda primero **un solo envase para todas las cadenas**:
gana el tamano que mas cadenas tienen, y entre empates el que mejor coincide con
lo pedido. Recien despues se comparan precios dentro de ese envase. Eso tambien
resuelve el caso de los Cheetos sin necesidad de entender que son un snack: no
entran en el formato de 500 g que tienen cuatro de las cinco cadenas.

El acuerdo es una prediccion, y puede no ser la que queres. Por eso la pestana
**Detalle por producto** tiene un selector de envase por item: cambiarlo rehace
la comparacion al instante, sin volver a consultar los sitios.

El filtro por formato es una preferencia, no una condicion excluyente. Si pedis
1 kg y una cadena solo vende paquetes de 500 g, se sigue ofreciendo esa cadena
con dos paquetes en vez de declarar que no tiene el producto.

### 5. Comparar siempre la misma canasta

A una cadena que no tiene un producto se le suma lo que costaria conseguirlo en
otro lado, estimado con el precio tipico de las cadenas que si lo tienen (la
mediana, no el minimo: nadie cruza la ciudad por un solo producto).

Antes esto se resolvia ordenando primero por cobertura y era peor el remedio:
una cadena diez mil pesos mas cara quedaba primera solo por tener un producto
mas que las otras. Un item que **ninguna** cadena encontro no penaliza a nadie:
no es un faltante de esa cadena, es algo que la app no supo buscar.

### 6. La marca la elegis vos, y fijarla es excluyente

El envase se acuerda solo porque casi siempre hay una respuesta razonable. La
marca no: que la app elija por su cuenta entre Casancrem y la segunda marca de
cada cadena seria inventar una preferencia que nadie declaro. Por eso, sin
indicacion, no se fija ninguna y se compara por precio.

Cuando si la fijas, el filtro es **excluyente**, al reves que el de envase. Si
pediste Casancrem y una cadena no lo tiene, la respuesta correcta es que no lo
tiene: cotizarle otra marca seria contestar una pregunta que no hiciste. Esa
cadena queda con el item faltante y entra el mecanismo de la decision 5.

El selector muestra en cuantas cadenas existe cada marca, porque eso define que
tan completa va a ser la comparacion:

```
Casancrem  (5)     ->  comparacion entre las cinco
La Paulina (5)     ->  idem
Arla       (1)     ->  solo dice cuanto sale en Jumbo
```

Las cinco cadenas publican la marca en un campo propio y lo llenan bien, pero
cada una la escribe a su manera (`TREGAR`, `Tregar`, `LA PAULINA`,
`La Paulina`). `nucleo/marca.py` las agrupa por su forma normalizada y muestra
la grafia mas legible. Tambien mira el nombre del producto, para las fichas
donde el campo de marca quedo vacio o mal cargado.

Fijar una marca cambia los envases disponibles: los de Casancrem no son los de
La Paulina. Si el envase elegido antes deja de existir, se vuelve a acordar solo.

### Ademas: tamanos imposibles

Los catalogos tambien tienen errores de tipeo en las unidades. Coto publica hoy
`Coca-Cola Sabor Liviano 1,75 Ml` para una botella de 1,75 litros. Leerlo al pie
de la letra metia un envase de dos mililitros entre las opciones. `nucleo/texto.py`
descarta las medidas fuera del rango plausible de un envase de supermercado.

---

## Zonas: CABA y Gran Buenos Aires

El precio del mismo producto cambia segun donde compres, y cada cadena resuelve
la zona de una forma distinta. `precios/zonas.py` traduce "compro en zona sur" a
lo que cada una necesita.

| Cadena | Como se le pide la zona |
|---|---|
| Carrefour, Dia, ChangoMas | cookie `vtex_segment` con el `regionId` que devuelve su API de regiones para un codigo postal |
| Coto | no regionaliza la busqueda: devuelve el precio de **todas** sus sucursales en la misma respuesta, y la zona se aplica al recibir |
| Jumbo | no expone ninguna forma publica; se informa el precio de su tienda online |

Zonas disponibles: **CABA**, **GBA Norte**, **GBA Oeste** y **GBA Sur**.

### Cuanto cambia realmente

Medido sobre la misma busqueda y comparando por EAN:

- **Carrefour y Dia**: cotizan igual en CABA y en todo el GBA. Recien cambian
  entre provincias.
- **ChangoMas**: CABA y GBA Norte comparten lista; **GBA Oeste y GBA Sur
  difieren**. La misma leche Las Tres Ninas de 1 L vale $2.749 en CABA y $2.719
  en zona sur, y en el sur aparecen marcas que en CABA no estan.
- **Jumbo**: sus canales de venta responden `sc is inactive` y su API de
  regiones devuelve un error. No hay zona que pedir.

Por eso las cadenas que no publican precios por zona lo dicen en su propia
tarjeta: con "GBA Sur" elegido arriba, nadie supondria que una de las cinco esta
mostrando otra cosa.

### Las sucursales de Coto se leen, no se escriben

El listado sale de `coto.com.ar/sucursales/index.asp`, que es una pagina plana
con las 122 sucursales, su numero, direccion y zona. Se lee al vuelo para que
abrir o cerrar una sucursal no obligue a tocar el codigo. Si la pagina falla,
Coto cotiza sin filtro de zona en vez de romperse.

Dentro de la zona se toma el precio **mas frecuente** entre sus sucursales, no
el minimo: el minimo suele ser una sucursal suelta con una promocion puntual, y
tomarlo haria parecer a Coto sistematicamente mas barato de lo que es.

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

- **Jumbo no tiene zona.** Las otras cuatro cotizan la zona elegida; Jumbo
  informa el precio de su tienda online porque es el unico que publica. Su
  tarjeta lo aclara.
- **La zona es del area metropolitana.** Estan CABA y las tres zonas del GBA.
  Para el interior hay que agregar la zona a `precios/zonas.py` con su codigo
  postal y su etiqueta de Coto.
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
  formato.py              acuerdo del envase comun entre cadenas
  marca.py                reconocimiento y fijado de marcas
precios/
  base.py                 sesion HTTP con reintentos y limites
  vtex.py                 Carrefour, Jumbo, Dia, ChangoMas
  coto.py                 Constructor.io
  registro.py             que cadena se consulta con que cliente
  zonas.py                CABA y GBA: regiones VTEX y sucursales de Coto
promociones/
  bancos.py               vocabulario de entidades, topes y porcentajes
  vtex_bp.py              Carrefour y ChangoMas
  jumbo.py                Jumbo
  dia.py                  Dia
  coto.py                 Coto
  agregador.py            las cinco en paralelo, tolerante a fallos
motor/
  canasta.py              busca candidatos y arma la cotizacion (dos pasadas)
  decision.py             aplica promos, rankea y arma el calendario
ui/
  tema.py                 paleta y CSS
```

Las dependencias van en una sola direccion: `app` depende de `motor`, `motor` de
`precios` y `promociones`, y todos de `nucleo`. `nucleo` no depende de nada.
