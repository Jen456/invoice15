"""Importa a una empresa los reportes .txt de Facturero Móvil (productos, clientes y proveedores). Ver core/pos/facturero.py.

  manage.py importar_facturero --empresa RUC [--productos F] [--clientes F] [--proveedores F]            ensayo (se deshace)
  manage.py importar_facturero --empresa RUC ... --aplicar [--informe informe.json]                      guarda

El titular de cada reporte («Generado por») debe ser la razón social de la empresa; --otro-titular lo omite.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.pos import facturero
from core.pos.models import Company


class Command(BaseCommand):
    help = 'Importa los reportes de Facturero Móvil a una empresa (ensayo salvo --aplicar).'

    def add_arguments(self, parser):
        parser.add_argument('--empresa', required=True, help='RUC de la empresa de destino.')
        for tipo in facturero.IMPORTADORES:
            parser.add_argument(f'--{tipo}', type=Path, help=f'Reporte de {tipo} (.txt de Facturero Móvil).')
        parser.add_argument('--aplicar', action='store_true', help='Guarda los datos (sin esto, todo se deshace).')
        parser.add_argument('--otro-titular', action='store_true', help='Acepta reportes de un titular con otro nombre.')
        parser.add_argument('--informe', type=Path, help='Guarda el informe completo en JSON.')

    def handle(self, *args, **opciones):
        empresas = list(Company.objects.filter(ruc=opciones['empresa']))
        if len(empresas) != 1:
            raise CommandError(f'Hay {len(empresas)} empresas con el RUC {opciones["empresa"]}.')
        empresa = empresas[0]
        reportes = {}
        for tipo in facturero.IMPORTADORES:
            if opciones[tipo] is None:
                continue
            try:
                reporte = facturero.leer_reporte(opciones[tipo].read_bytes(), tipo)
            except (OSError, ValueError) as error:
                raise CommandError(f'{opciones[tipo]}: {error}')
            if facturero.clave(reporte.titular) != facturero.clave(empresa.business_name) and not opciones['otro_titular']:
                raise CommandError(f'{opciones[tipo]}: el titular es «{reporte.titular}» y la empresa «{empresa.business_name}» '
                                   '(usa --otro-titular si es correcto).')
            reportes[tipo] = reporte
        if not reportes:
            raise CommandError('Indica al menos un reporte: --productos, --clientes o --proveedores.')
        informe = facturero.importar(empresa, reportes, aplicar=opciones['aplicar'])
        modo = 'GUARDADO' if opciones['aplicar'] else 'ENSAYO (deshecho, no se guardó nada)'
        self.stdout.write(f'{modo} — empresa {empresa.pk} {empresa.business_name} ({empresa.ruc})')
        for tipo, reporte in reportes.items():
            self.stdout.write(f'  {tipo}: {len(reporte.filas)} filas leídas')
        self.stdout.write('  creados: ' + ', '.join(f'{k} {v}' for k, v in informe.creados.items()))
        self.stdout.write(f'  omitidos: {len(informe.omitidos)}, avisos: {len(informe.avisos)}')
        for fila in informe.omitidos:
            self.stdout.write(f'  OMITIDO {fila["tipo"]} línea {fila["linea"]} {fila["referencia"]}: {fila["motivo"]}')
        for fila in informe.avisos:
            self.stdout.write(f'  AVISO {fila["tipo"]} línea {fila["linea"]} {fila["referencia"]}: {fila["aviso"]}')
        if opciones['informe']:
            datos = {'modo': 'aplicar' if opciones['aplicar'] else 'ensayo', 'empresa': empresa.ruc,
                     'filas': {t: len(r.filas) for t, r in reportes.items()}, 'creados': informe.creados,
                     'omitidos': informe.omitidos, 'avisos': informe.avisos}
            opciones['informe'].write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding='utf-8')
