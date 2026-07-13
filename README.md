# Surcos X32 EQ2404 — GitHub Builder

Este repositorio genera `Surcos-X32-EQ2404.run` en GitHub Actions sin volver a compilar CrossCore.

## Qué contiene

- `prebuilt/dsp1.ldr`: DSP1 compilado con EQ 2404 y Low Cut de cuarto orden.
- `prebuilt/dsp2.ldr`: DSP2 compilado desde la misma copia de trabajo.
- Archivos sustitutos limpios de OpenMixerControl:
  - LOW: 100 Hz fijo, Gain -15/+15 dB.
  - MID: 350 Hz–5 kHz y Gain -15/+15 dB.
  - HIGH: 10 kHz fijo, Gain -15/+15 dB.
  - AIR: 16 kHz fijo, Gain 0/+15 dB.
  - LOW CUT: 20–220 Hz, 24 dB/octava.
  - Q y tipo de filtro quedan fijos.
- Fuentes modificadas de DSP1 para poder reproducir futuras compilaciones en CrossCore.
- Workflow de GitHub que compila la GUI ARM y reemplaza `omc`, `dsp1.ldr` y `dsp2.ldr` dentro de una publicación oficial de OpenX32.

## Cómo usar en GitHub

1. Crea un repositorio nuevo y sube el contenido de este ZIP.
2. Abre **Actions**.
3. Selecciona **Build Surcos X32 EQ2404**.
4. Pulsa **Run workflow**.
5. Cuando termine, descarga el artifact `Surcos-X32-EQ2404`.
6. Dentro estará `Surcos-X32-EQ2404.run` y su SHA-256.

El workflow usa por defecto la publicación oficial `beta-2026-06-09--5` como base. Conserva el kernel, FPGA, sistema Linux y demás recursos oficiales; reemplaza solamente la GUI y los dos cargadores DSP.

## Advertencia importante

La consola del usuario es aproximadamente de 2017 y probablemente tiene FPGA Xilinx. El proyecto OpenX32 sigue marcando la variante Xilinx como no funcional. Generar el archivo `.run` no demuestra que sea seguro ni operativo en esa revisión. No renombres el archivo a `.update`. La primera prueba debe realizarse con salidas, amplificadores, parlantes y phantom desconectados.

## Fuentes fijadas

- OpenX32: `56cc9f46e711c869d3b7e580a5ee5279377b9c97`
- OpenMixerControl: `0291d836758b3bc36831dca5014c319c7048e59c`

Consulta `metadata/commits.txt` para hashes de los DSP.

## v0.2.1 correction

The repacker now locates the ramdisk uImage dynamically instead of relying on the incorrect hard-coded `0x310000` offset. OpenX32 currently writes it using `bs=512 seek=0x1A00`, which equals `0x340000`. The script also validates and rebuilds uImage CRCs automatically.
