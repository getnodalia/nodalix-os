# Repositorio de paquetes `[nodalix]`

Los paquetes de cada release se publican en un repositorio pacman firmado para que
el sistema se actualice con `pacman -Syu` sin descargar archivos a mano.

## Cómo se construye

`tools/build-pacman-repo.sh PAQUETES SALIDA CLAVE` firma cada paquete (`.sig` separada),
crea la base de datos con `repo-add --sign` y deja copias reales de `nodalix.db` y
`nodalix.files` (los alojamientos estáticos no siguen enlaces simbólicos).

El CI lo prueba en cada PR (`signed-repo`): genera una clave desechable, construye el
repositorio con los paquetes del candidato, lo añade a un `pacman.conf` con
`SigLevel = Required DatabaseRequired TrustedOnly`, descarga `nodalix-store` verificando
la firma y comprueba que una base de datos manipulada se rechaza.

## Cómo se publica

El repositorio vive en GitHub Pages: `https://getnodalia.github.io/nodalix-os/x86_64`.
Lo publica el workflow **Publish pacman repository**. Se puede ejecutar
manualmente (`workflow_dispatch`) con el id de una ejecución correcta de CI
en `main`; además, cuando una actualización independiente de Brújula modifica
su PKGBUILD en `main`, la publicación se inicia automáticamente después de
completarse con éxito la CI de ese mismo commit. Tanto la ruta automática
como la manual requieren comprobar la identidad, el SHA y el estado de CI.
El workflow descarga los paquetes verificados
(`nodalix-0.4.0-candidate`). `tools/ci-publish-repo.sh`:

1. importa la clave privada del secreto `NODALIX_REPO_GPG_KEY` (y, si existe, su
   contraseña en `NODALIX_REPO_GPG_PASSPHRASE`) y comprueba que su huella es la del
   keyring (`3DE029728CDE1828E18B437930D356AC0F6AB1CF`);
2. se niega a publicar si los paquetes superan 900 MB (el límite de Pages es 1 GB);
3. firma los paquetes y la base de datos con `tools/build-pacman-repo.sh`.

Los secretos de firma deben estar en el *environment* `nodalix-repo-signing`
(Settings → Environments), restringido a la rama `main`, y no como secretos del
repositorio: así ninguna rama modificada puede ejecutar el workflow con la clave. El
workflow además comprueba que el id indicado es una ejecución correcta del CI de este
repositorio en `main` antes de firmar nada.

Para activarlo hay que habilitar Pages en el repositorio (Settings → Pages → Source:
GitHub Actions). Si algún día los paquetes no caben, el plan B es alojarlos en un release
fijo de GitHub y mantener solo la base de datos en Pages.

## Puesta en servicio y equipos ya instalados

La dirección del repositorio **solo debe añadirse a pacman una vez que**
`https://getnodalia.github.io/nodalix-os/x86_64/nodalix.db` y
`nodalix.db.sig` devuelvan HTTP 200. HTTP 404 significa que el repositorio
no se ha publicado aún; no es un problema de clave local. No desactivar
`SigLevel` para solucionarlo.

Primero configurar **Settings → Pages → GitHub Actions** en GitHub, así como
el entorno `nodalix-repo-signing` restringido a `main` con la clave GPG
existente (fingerprint `3DE029728CDE1828E18B437930D356AC0F6AB1CF`).
Comprobar que el workflow de publicación termina correctamente. No regenerar
la clave de firma sin un procedimiento de rotación.

Después, en cada sistema instalado, respaldar `/etc/pacman.conf` y añadir:

```ini
[nodalix]
SigLevel = Required DatabaseRequired TrustedOnly
Server = https://getnodalia.github.io/nodalix-os/$arch
```

La instalación debe tener `nodalix-keyring` y confiar en la clave oficial.
Ejecutar una actualización completa con `sudo pacman -Syu`, nunca una
actualización parcial. Los sistemas previamente instalados sin `[nodalix]`
no pueden descubrir automáticamente los paquetes de este repositorio.
La incorporación idempotente de ese repositorio a instalaciones nuevas y
migradas debe abordarse en el instalador/actualizador tras validar su
disponibilidad y firmas; no debe hacerse con `SigLevel = Never`.
