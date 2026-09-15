# Criptografía: decisiones tras la evaluación

Resumen de lo que decidimos después de medir todos los algoritmos de
`confidential-crypto`. Los números completos, los criterios y las fuentes están en el registro `docs/crypto-evaluation.md`.

## El escenario

Queremos distribuir modelos LLM cifrados. Un **productor** cifra y firma el modelo; un **consumidor**
en Kubernetes lo descarga, verifica la firma, obtiene la clave de un Secret, descifra y carga el modelo.
Los modelos LLM pesan **GB**, así que hay tres preguntas:

1. ¿Qué cifrador uso para proteger el modelo?
2. ¿Qué esquema de firma uso para que el consumidor detecte si el archivo fue manipulado?
3. ¿Cómo aplico el cifrado a un archivo de GB sin que el consumidor se quede sin memoria?

## Qué se midió

Cada algoritmo se probó con archivos de 16, 64 y 256 MiB (con varias repeticiones):

- **Velocidad**: cuántos MiB por segundo cifra y descifra.
- **Memoria**: cuánto crece el uso de RAM al cifrar y al descifrar.
- **Espacio extra**: cuántos bytes añade al archivo (nonce + tag).
- **Seguridad**: puntuación 0–3 con criterios objetivos y fuentes.

> No se ha medido en este caso el cómputo de CPU. El rendimiento y mejora en CPU/hardware lo dejo fuera del scope.
> Me centro más en memoria.

## Cifrado (con archivos de 256 MiB)

| Algoritmo | Vel. cifra / descifra | Memoria | Ventajas | Inconvenientes |
|---|---|---|---|---|
| **aes-256-gcm** | ~1160 / ~1985 MiB/s | 768 MiB | estándar de facto (NIST), rapidísimo con AES-NI, ecosistema enorme | reutilizar el nonce lo rompe todo; sin AES-NI va lento y el software no es tiempo constante |
| **chacha20-poly1305** | ~890 / ~1290 MiB/s | 768 MiB | rápido sin hardware especial, tiempo constante, el plan B de TLS 1.3 | mismo problema del nonce; no está en la lista FIPS |
| **aes-256-gcm-siv** | ~480 / ~575 MiB/s | 768 MiB | el reuso de nonce casi no importa (solo delata si dos mensajes son iguales) | el más lento (hace dos pasadas), poco desplegado, requiere OpenSSL reciente |
| **xchacha20-poly1305** | ~645 / ~607 MiB/s | 1279 MiB | nonce de 192 bits: colisiones accidentales casi imposibles | sin RFC oficial (borrador caducado), más memoria, más lento |
| **aes-256-cbc-hmac-sha256** | ~347 / ~532 MiB/s | 1279 MiB | ninguno | composición casera CBC+HMAC, origen de los históricos *padding oracle*; **no apto para producción** |

Veredicto del ranking ponderado: `aes-256-gcm` (4.8) > `chacha20-poly1305` (4.2) > `aes-256-gcm-siv`
(3.7) > `xchacha20-poly1305` (3.1) > `aes-256-cbc-hmac-sha256` (0).

> **Elegimos `aes-256-gcm`**: el más rápido y el más estándar. Su único riesgo (el nonce) es
> controlable aquí porque solo cifra el productor, una vez por archivo.

## Esquemas de firma

| Esquema | Firmar / verificar | Clave pública / firma | Determinista | Ventajas | Inconvenientes |
|---|---|---|---|---|---|
| **ed25519** | 36.7 / 19.5 ms | 113 B / 64 B | sí | nada que fallar con aleatoriedad, tiempo constante por diseño, firmas diminutas, RFC 8032 / FIPS 186-5 | no es post-cuántico |
| **ecdsa-p256** | 8.1 / 8.5 ms | 178 B / 72 B | no | muy rápido, claves instantáneas | necesita un nonce secreto por firma: si se reutiliza se filtra la clave privada (casos reales: PS3, wallets de Bitcoin) |
| **rsa-pss-3072** | 96.6 / 8.6 ms | 625 B / 384 B | no | verificación rapidísima, décadas de auditoría | claves y firmas grandes, generar la clave tarda 320 ms |
| **rsa-pss-4096** | 211 / 8.3 ms | 800 B / 512 B | no | algo más de margen que 3072 | lo mismo pero más lento: 848 ms solo en generar la clave |
| **ml-dsa-65** | 31.5 / 30.6 ms | 2726 B / 3309 B | no | estándar post-cuántico de NIST (Dilithium) | claves y firmas enormes (~3 KB), implementaciones nuevas y poco auditadas |

> **Elegimos `ed25519`**: primero del ranking (4.4) y por las razones correctas: determinista,
> siempre tiempo constante y firmas diminutas. El hueco post-cuántico queda anotado — `ml-dsa-65` ya
> está registrado por si algún día migramos, sería un cambio de opción, no un rediseño.

## Modos de cifrado (cómo se aplica el cifrado al archivo)

| Modo | Memoria (256 MiB) cifrar / descifrar | Vel. archivo→archivo (aes-256-gcm) | ¿Autentica antes de liberar datos? | Ventajas | Inconvenientes |
|---|---|---|---|---|---|
| **one-shot** | ~512 MiB | 626 / 578 MiB/s | sí | el código más simple, garantía "todo o nada", 18/18 en la tabla de seguridad | la memoria crece con el archivo (~2×): inviable para pesos de GB |
| **chunked** | ~2.7 / ~3.5 MiB | 941 / 740 MiB/s | sí (por fragmento) | memoria plana siempre, misma seguridad que one-shot, y archivo a archivo no es más lento (de hecho en la medición sale más rápido) | formato v2, un tag por fragmento, más lógica delicada (nonce por fragmento, último fragmento, lecturas cortas) |
| **streaming-gcm** | ~1.5 / ~1.6 MiB | 698 / 643 MiB/s | **no** | memoria mínima, no cambia el formato | libera texto plano sin verificar: descartado para esto; solo funciona con AES-GCM |

## La decisión grande: chunked

Se podría argumentar one-shot por puntuar más en la tabla (18 vs 17), pero ese punto de ventaja es
todo **simplicidad del código y estabilidad de formato**, y la pieza que one-shot no puede dar es
justo la que necesitamos: **memoria constante**. Un modelo LLM de ~10 GB obligaría a ~20 GB de RAM en
el consumidor con one-shot; en un pod de Kubernetes eso no se pide.

**chunked** mantiene la memoria plana en ~3–4 MiB sin importar el tamaño del modelo, ofrece las
mismas garantías de seguridad (cada fragmento se autentica antes de escribirse, detecta truncados y
reordenamientos) y, medido archivo a archivo, **no pierde rendimiento**: en nuestras medidas incluso
gana, porque evita los buffers monstruosos que causan fallos de página en one-shot.

**streaming-gcm se descarta** aunque gaste la menor memoria de todos: libera datos antes de
verificar el tag, y un consumidor que carga el modelo directamente desde la salida descifrada no
puede permitirse eso. Es el ejemplo negativo documentado.

## Decisión final

| Decisión | Valor | Por qué |
|---|---|---|
| Cifrador | `aes-256-gcm` | el más rápido y estándar; el riesgo del nonce es controlable (solo cifra el productor) |
| Firma | `ed25519` | determinista, seguro por diseño, diminuta, nº 1 del ranking |
| Modo | **chunked** | memoria constante para pesos de GB, misma seguridad, sin penalización de velocidad |

El consumidor decide el modo a partir del byte de versión autenticado del artefacto, así que publicar
en chunked no rompe nada: si algún día hace falta (modelo pequeño, máquina con RAM de sobra),
seguiría existiendo one-shot como alternativa.

## Riesgos que quedan anotados

- **Nonce**: GCM con nonce aleatorio; como solo cifra el productor una vez por archivo, el límite de
  2^32 mensajes por clave no aplica.
- **Post-cuántico**: la confidencialidad ya es resistente a ordenadores cuánticos (clave de 256 bits);
  la firma no lo es. `ml-dsa-65` está medido y registrado por si migramos a híbrido.