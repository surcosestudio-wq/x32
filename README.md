# GitHub Builder compatible

Este builder usa exactamente las revisiones asociadas al firmware base que reconoció correctamente las entradas y salidas locales.

Antes de subirlo a GitHub debe existir:

`prebuilt/dsp1.ldr`

Ese archivo debe ser el nuevo DSP1 compilado desde `../CrossCore/dsp1` en configuración Release.

El workflow reemplaza solamente:

- `/openx32/omc`
- `/openx32/dsp1.ldr`

No reemplaza DSP2, FPGA, kernel ni archivos de detección/control de las placas locales.
